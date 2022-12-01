
from miniparla.task_states import TaskRunning, TaskCompleted, TaskState, TaskException
from collections import namedtuple, defaultdict, deque
import threading
import time
from abc import abstractmethod, ABCMeta
from contextlib import contextmanager
from typing import Awaitable, Collection, Iterable, Tuple, Union, List, Dict, Any

import inspect
import logging

logger = logging.getLogger(__name__)


TaskAwaitTasks = namedtuple("AwaitTasks", ["dependencies", "value_task"])


class WorkerThreadException(RuntimeError):
    pass


class TaskID:

    def __init__(self, name, id):
        self._name = name
        self._id = id
        self._task = None

    @property
    def task(self):
        if not self._task:
            return None
        return self._task

    @property
    def inner_task(self):
        if not self._task:
            return None
        return self._task.inner_task

    @task.setter
    def task(self, v):
        assert not self._task
        self._task = v

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def full_name(self):
        return "_".join(str(i) for i in (self._name, *self._id))

    @property
    def dependencies(self):
        return self._dependencies

    @dependencies.setter
    def dependencies(self, v):
        self._dependencies = v

    def __hash__(self):
        return hash(self.full_name)

    def __await__(self):
        return (yield TaskAwaitTasks([self.task], self.task))


class InnerTask:

    def __init__(self, id, dependencies):

        self.complete = False
        self.id = id

        self._mutex = threading.Condition(threading.Lock())
        self._dependents = []
        self.dependencies = dependencies

    @property
    def dependencies(self):
        with self._mutex:
            return self._dependencies

    @dependencies.setter
    def dependencies(self, v):
        with self._mutex:
            self._dependencies = list(v)
            self._num_dependencies = len(self._dependencies)

            for dependency in self._dependencies:
                if not dependency.add_dependent(self):
                    self._num_dependencies -= 1

    def blocked(self):
        with self._mutex:
            return self._num_dependencies > 0

    def blocked_unsafe(self):
        return self._num_dependencies > 0

    def add_dependent(self, task):
        with self._mutex:
            if self.complete:
                return False
            else:
                self._dependents.append(task)
                return True

    def notify_dependents(self):
        #print(self._dependents, len(self._dependents), flush=True)
        self._notify_list = []

        with self._mutex:
            for task in self._dependents:
                #print(task, flush=True)
                if task.dependency_completed():
                    self._notify_list.append(task)
            self._dependents = []
            self.complete = True

        return self._notify_list

    def dependency_completed(self):
        with self._mutex:
            self._num_dependencies -= 1

            if self._num_dependencies == 0:
                return True
            else:
                return False

    def add_dependency(self, task):
        with self._mutex:
            if task.complete:
                return False
            else:
                self._dependencies.append(task)
                self._num_dependencies += 1
                task.add_dependent(self)
                return True


class Task:

    def __init__(self, func, args, dependencies, taskid, req, name):
        self._mutex = threading.Lock()

        with self._mutex:
            self.id = id(self)
            self._func = func
            self._args = args
            self._taskid = taskid
            self._taskid._task = self
            self._req = req
            self._name = name

            self._state = TaskRunning(func, args, dependencies)

            flat_deps = [dep.task.inner_task for dep in dependencies]
            self.inner_task = InnerTask(self.id, flat_deps)

            self.context = get_scheduler_context()

            self.context.scheduler.incr_active_tasks()

            self.context.scheduler._task_dict.add(self)

            if not self.blocked_unsafe():
                self.context.scheduler.enqueue_task(self)

    @property
    def req(self):
        return self._req

    @property
    def task(self):
        return self

    def _execute_task(self):
        return self._state.func(self, *self._state.args)

    def _finish(self, ctx):
        # ctx.remove_vcus(self.req.vcus)
        pass

    def run(self):
        try:
            with self._mutex:
                task_state = TaskException(RuntimeError("Unknown Error"))

                try:
                    assert isinstance(self._state, TaskRunning)

                    task_state = self._execute_task()

                    task_state = task_state or TaskCompleted(None)

                except Exception as e:
                    task_state = TaskException(e)

                finally:
                    ctx = get_scheduler_context()
                    if isinstance(task_state, TaskCompleted):
                        self._notify_dependents()
                    self._set_state(task_state, ctx)
                    self._finish(ctx)
        except Exception as e:
            raise e

    def _cleanup(self):
        self._func = None
        self._args = None

    def _set_state(self, new_state, ctx):

        self._state = new_state

        if isinstance(new_state, TaskException):
            print(TaskException)
            ctx.scheduler.stop()

        elif isinstance(new_state, TaskRunning):
            if new_state.dependencies is not None:
                flat_deps = [dep.inner_task for dep in new_state.dependencies]
            else:
                flat_deps = None
            self.dependencies = flat_deps
            if not self.blocked_unsafe():
                ctx.scheduler.enqueue_task(self)
            new_state.dependencies = []

        if new_state.is_terminal:
            # Remove from TaskDict
            ctx.scheduler._task_dict.remove(self)

            # Decrease active task count
            ctx.scheduler.decr_active_task()

    def __await__(self):
        return (yield TaskAwaitTasks([self], self))

    def _notify_dependents(self):
        notify_list = self.inner_task.notify_dependents()
        ctx = self.context
        #print(notify_list, len(notify_list))
        for dependent_inner in notify_list:
            dependent = ctx.scheduler._task_dict.get(dependent_inner)
            if dependent:
                ctx.scheduler.enqueue_task(dependent)

    def _add_dependency(self, task):
        self.inner_task.add_dependency(task)

    def _add_dependent(self, task):
        self.inner_task.add_dependent(task)

    def blocked(self):
        return self.inner_task.blocked()

    def blocked_unsafe(self):
        return self.inner_task.blocked()

    @property
    def dependencies(self):
        return self.inner_task.dependencies

    @dependencies.setter
    def dependencies(self, v):
        self.inner_task.dependencies = v


class _TaskLocals(threading.local):
    def __init__(self):
        super(_TaskLocals, self).__init__()
        self.task_scopes = []

    @property
    def ctx(self):
        return getatrr(self, "_ctx", None)

    @ctx.setter
    def ctx(self, v):
        self._ctx = v

    @property
    def global_tasks(self):
        return getattr(self, "_global_tasks", [])

    @global_tasks.setter
    def global_tasks(self, v):
        self._global_tasks = v


task_locals = _TaskLocals()


class SchedulerContext:

    def spawn_task(self, function, args, dependencies, taskid, req, name):
        return Task(function, args, dependencies=dependencies, taskid=taskid, req=req, name=name)

    def __enter__(self):
        # print("INNER")
        _scheduler_locals._scheduler_context_stack.append(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _scheduler_locals._scheduler_context_stack.pop()


class _SchedulerLocals(threading.local):
    def __init__(self):
        super(_SchedulerLocals, self).__init__()
        self._scheduler_context_stack = []

    @property
    def scheduler_context(self):
        if self._scheduler_context_stack:
            return self._scheduler_context_stack[-1]
        else:
            raise Exception("No scheduler context")


_scheduler_locals = _SchedulerLocals()


def get_scheduler_context():
    return _scheduler_locals.scheduler_context


class ControllableThread(threading.Thread):

    def __init__(self):
        super().__init__()
        self._should_run = True

    def stop(self):
        with self._monitor:
            self._should_run = False
            self._monitor.notify_all()

    def run(self):
        pass


class WorkerThread(ControllableThread, SchedulerContext):
    def __init__(self, scheduler, index):
        super().__init__()
        self._scheduler = scheduler
        self._monitor = threading.Condition(threading.Lock())
        self.index = index
        self.task = None

    @property
    def scheduler(self):
        return self._scheduler

    # @profile
    def assign_task(self, task):
        with self._monitor:
            if self.task:
                raise Exception("Worker already has a task")
            self.task = task
            self.scheduler.incr_running_tasks()
            self.scheduler.decr_resources(task.req.vcus)
            self._monitor.notify()

    def _remove_task(self):
        with self._monitor:
            if not self.task:
                raise Exception("Worker does not have a task")
            self.scheduler.incr_resources(self.task.req.vcus)
            self.task = None
            self.scheduler.decr_running_tasks()

    def run(self):
        try:

            with self:
                self.scheduler.append_free_thread(self)

                while self._should_run:
                    with self._monitor:
                        #print("THREAD WAITING: ", self.index, flush=True)
                        if not self.task:
                            self._monitor.wait()

                    #print("THREAD ACTIVE", self.index, flush=True)
                    if self.task:
                        #print("TASK ACTIVE", self.index, flush=True)
                        self.task.run()
                        self._remove_task()
                        self.scheduler.append_free_thread(self)
                        self.scheduler.start_scheduler_callbacks()
                        #print("FINISHED TASK")

                    elif not self.task and self._should_run:
                        raise WorkerThreadException("How did I get here?")

        except Exception as e:
            self.scheduler.stop()
            raise e

    def stop(self):
        super().stop()
        #print("Stopping Thread", self.index, flush=True)


class TaskDict:

    def __init__(self):

        self.__dict = {}
        self.__mutex = threading.Condition(threading.Lock())

    def add(self, task):
        with self.__mutex:
            self.__dict[task.id] = task

    def get(self, task_inner):
        with self.__mutex:
            return self.__dict.get(task_inner.id, None)

    def remove(self, task):
        with self.__mutex:
            del self.__dict[task.id]


class Scheduler(ControllableThread, SchedulerContext):

    def __init__(self, n_threads=8, period=0.001):
        super().__init__()
        self._monitor = threading.Condition(threading.Lock())
        self._n_threads = n_threads
        self._period = period
        self._exceptions = []

        self._task_dict = TaskDict()

        self._running_tasks = 0
        self._running_tasks_monitor = threading.Condition(threading.Lock())

        self._active_tasks = 1
        self._active_tasks_monitor = threading.Condition(threading.Lock())

        self._vcus = 1
        self._resource_monior = threading.Condition(threading.Lock())

        self._ready_queue = deque()
        self._ready_queue_monitor = threading.Condition(threading.Lock())

        self._free_worker_threads = deque()
        self._thread_queue_monitor = threading.Condition(threading.Lock())
        self._worker_threads = [WorkerThread(
            self, i) for i in range(n_threads)]

        self._scheduling_phase_monitor = threading.Condition(threading.Lock())
        self._launching_phase_monitor = threading.Condition(threading.Lock())

        for t in self._worker_threads:
            t.start()

        while True:
            with self._thread_queue_monitor:
                if len(self._free_worker_threads) > 0:
                    break

        self.start()

    @property
    def scheduler(self):
        return self

    def __enter__(self):
        if self._active_tasks != 1:
            raise Exception("Scheduler context can only be entered once")
        return super().__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        super().__exit__(exc_type, exc_val, exc_tb)
        self.decr_active_task()

        with self._monitor:
            while self._should_run:
                self._monitor.wait()
            for t in self._worker_threads:
                t.join()

            if self._exceptions:
                raise self._exceptions[0]

    def append_free_thread(self, thread):
        with self._thread_queue_monitor:
            self._free_worker_threads.append(thread)
            self._thread_queue_monitor.notify()

    def incr_resources(self, vcus):
        with self._resource_monior:
            self._vcus += vcus
            #print("+VCUS", self._vcus, flush=True)

    def decr_resources(self, vcus):
        with self._resource_monior:
            self._vcus -= vcus
            #print("-VCUS", self._vcus, flush=True)

    def current_resources(self):
        with self._resource_monior:
            return self._vcus
            print("=VCUS", self._vcus, flush=True)

    def incr_active_tasks(self):
        with self._active_tasks_monitor:
            self._active_tasks += 1
            #print("+ACTIVE", self._active_tasks, flush=True)

    def decr_active_task(self):
        done = False

        with self._active_tasks_monitor:
            self._active_tasks -= 1
            #print("-ACTIVE", self._active_tasks, flush=True)

            if self._active_tasks == 0:
                done = True

        if done:
            self.stop()

    def num_active_tasks(self):
        with self._active_tasks_monitor:
            return self._active_tasks

    def incr_running_tasks(self):
        with self._running_tasks_monitor:
            self._running_tasks += 1

    def decr_running_tasks(self):
        with self._running_tasks_monitor:
            self._running_tasks -= 1

    def num_running_tasks(self):
        with self._running_tasks_monitor:
            return self._running_tasks

    def enqueue_task(self, task):
        with self._ready_queue_monitor:
            self._ready_queue.appendleft(task)

    def enqueue_task_unsafe(self, task):
        self._ready_queue.appendleft(task)

    # @profile
    def _launch_task(self, queue):
        try:
            while len(queue):
                task = queue.pop()
                worker = self._free_worker_threads.pop()

                if isinstance(task._state, TaskCompleted):
                    continue

                vcus = task.req.vcus
                if (self.current_resources() - vcus) < 0:
                    self.enqueue_task_unsafe(task)
                    break

                worker.assign_task(task)

        except IndexError:
            self.enqueue_task_unsafe(task)

    # @profile
    def _launch_tasks(self):
        with self._ready_queue_monitor:
            self._launch_task(self._ready_queue)

    def start_scheduler_callbacks(self):
        launch_succeed = self._launch_tasks_callback()
        while self.num_running_tasks() == 0 and self.num_active_tasks() > 0:
            launch_succeed = self._launch_tasks_callback()
            time.sleep(self._period)

    # @profile
    def _launch_tasks_callback(self):
        condition = len(
            self._free_worker_threads) > 0 and self.num_active_tasks() != 0

        if condition and self._launching_phase_monitor.acquire(blocking=False):
            self._launch_tasks()
            self._launching_phase_monitor.release()
            return True

        return False

    def run(self):
        try:
            while self._should_run:
                time.sleep(self._period)
                self.start_scheduler_callbacks()

        except Exception as e:
            self.stop()

    def stop(self):
        super().stop()

        for w in self._worker_threads:
            w.stop()
        #print("ALL STOPPED", flush=True)


class Resources:

    def __init__(self, vcus):
        self.vcus = vcus


# @profile
def _task_callback(task, body) -> TaskState:
    """
    A function which forwards to a python function in the appropriate device context.
    """
    try:
        body = body

        if inspect.iscoroutinefunction(body):
            body = body()

        if inspect.iscoroutine(body):
            try:
                in_value_task = getattr(task, "value_task", None)
                in_value = in_value_task and in_value_task.result

                new_task_info = body.send(in_value)
                task.value_task = None
                if not isinstance(new_task_info, TaskAwaitTasks):
                    raise TypeError(
                        "Parla coroutine tasks must yield a TaskAwaitTasks")
                dependencies = new_task_info.dependencies
                value_task = new_task_info.value_task
                if value_task:
                    assert isinstance(value_task, Task)
                    task.value_task = value_task
                return TaskRunning(_task_callback, (body,), dependencies)
            except StopIteration as e:
                result = None
                if e.args:
                    (result,) = e.args
                return TaskCompleted(result)
        else:
            result = body()
            return TaskCompleted(result)
    finally:
        pass
    assert False


def _make_cell(val):
    """
    Create a new Python closure cell object.

    You should not be using this. I shouldn't be either, but I don't know a way around Python's broken semantics.
    """
    x = val

    def closure():
        return x

    return closure.__closure__[0]


def spawn(taskid=None,  dependencies=[], vcus=1):

    if not taskid:
        taskid = TaskID("global_" + str(len(task_locals.global_tasks)),
                        (len(task_locals.global_tasks),))

        task_locals.global_tasks += [taskid]

    # @profile
    def decorator(body):
        nonlocal vcus
        req = Resources(vcus)

        if inspect.iscoroutine(body):
            separated_body = body
        else:
            separated_body = type(body)(
                body.__code__, body.__globals__, body.__name__, body.__defaults__,
                closure=body.__closure__ and tuple(_make_cell(x.cell_contents) for x in body.__closure__))
            separated_body.__annotations__ = body.__annotations__
            separated_body.__doc__ = body.__doc__
            separated_body.__kwdefaults__ = body.__kwdefaults__
            separated_body.__module__ = body.__module__

        taskid.dependencies = dependencies
        processed_dependencies = Tasks(*dependencies)._flat_tasks

        scheduler = get_scheduler_context()

        if isinstance(scheduler, WorkerThread):
            scheduler = scheduler.scheduler

        task = scheduler.spawn_task(function=_task_callback, args=(
            separated_body,), dependencies=processed_dependencies, taskid=taskid, req=req, name=getattr(body, "___name__", None))

        scheduler.start_scheduler_callbacks()

        return task

    return decorator


class TaskSet(Awaitable, Collection):

    def _tasks(self):
        pass

    @property
    def _flat_tasks(self):
        dependencies = []
        for ds in self._tasks:
            if not isinstance(ds, Iterable):
                ds = (ds,)
            for d in ds:
                if hasattr(d, "task"):
                    if d.task is not None:
                        d = d.task
                dependencies.append(d)

        return dependencies

    def __await__(self):
        return (yield TaskAwaitTasks(self._flat_tasks, None))

    def __len__(self):
        return len(self._tasks)

    def __iter__(self):
        return iter(self._tasks)

    def __contains__(self, x):
        return x in self._tasks

    def __repr__(self):
        return "tasks({})".format(", ".join(repr(x) for x in self._tasks))


class Tasks(TaskSet):

    @property
    def _tasks(self):
        return self.args

    def __init__(self, *args):
        self.args = args


def parse_index(prefix, index,  step,  stop):
    """Traverse :param:`index`, update :param:`prefix` by applying :param:`step`, :param:`stop` at leaf calls.

    :param prefix: the initial state
    :param index: the index tuple containing subindexes
    :param step: a function with 2 input arguments (current_state, subindex) which returns the next state, applied for each subindex.
    :param stop: a function with 1 input argument (final_state), applied each time subindexes exhaust.
    """
    if len(index) > 0:
        i, *rest = index
        if isinstance(i, slice):
            for v in range(i.start or 0, i.stop, i.step or 1):
                parse_index(step(prefix, v), rest, step, stop)
        elif isinstance(i, Iterable):
            for v in i:
                parse_index(step(prefix, v), rest, step, stop)
        else:
            parse_index(step(prefix, i), rest, step, stop)
    else:
        stop(prefix)


class TaskSpace(TaskSet):

    @property
    def _tasks(self):
        return self._data.values()

    def __init__(self, name="", members=None):
        self._data = members or {}
        self._name = name

    def __getitem__(self, index):

        if not isinstance(index, tuple):
            index = (index,)
        ret = []

        parse_index((), index, lambda x, i: x + (i,),
                    lambda x: ret.append(self._data.setdefault(x, TaskID(self._name, x))))
        #print("index ret", ret, flush=True)
        if len(ret) == 1:
            return ret[0]
        return ret

    def __repr__(self):
        return "TaskSpace({self._name}, {_data})".format(**self.__dict__)
