
from miniparla.task_states import TaskRunning, TaskCompleted, TaskState, TaskException
from collections import namedtuple, defaultdict, deque
import threading
import time
from abc import abstractmethod, ABCMeta
from contextlib import contextmanager
from typing import Awaitable, Collection, Iterable, Tuple, Union, List, Dict, Any

import inspect
import logging

import cython
cimport cython
from libcpp cimport bool
from libcpp.string cimport string

logger = logging.getLogger(__name__)


TaskAwaitTasks = namedtuple("AwaitTasks", ["dependencies", "value_task"])

cdef extern from "cpp_runtime.hpp" nogil:
    ctypedef void (*callerfunc)(void* f, void* python_task, void* python_worker);
    ctypedef void (*stopfunc)(void* f);
    ctypedef void* launcherfunc;

    int log_write(string file);

    void launch_task_callback(callerfunc func, void* f, void* python_task,void* python_worker) except +

    cdef cppclass InnerWorker:
        void* worker

        InnerWorker() except +
        InnerWorker(void* worker) except +

    cdef cppclass InnerTask:
        long id
        void* python_task
        bool complete
        float vcus

        InnerTask() except +
        InnerTask(long i, void* python_task, float vcus) except +

        void set_task(void* task) except +
        void set_name(string name) except +

        void add_dependency_unsafe(InnerTask* task) except +
        void add_dependency(InnerTask* task) except +
        void clear_dependencies() except +

        bool add_dependent(InnerTask* task) except +
        void notify_dependents(InnerScheduler* scheduler) except +
        bool notify() except +

        bool blocked_unsafe() except +
        bool blocked() except +

        int get_num_deps() except +

        void set_type(int t ) except +
        void set_type_unsafe(int t) except +

    cdef cppclass InnerScheduler:
        bool should_run

        InnerScheduler() except +
        InnerScheduler(callerfunc func, float resources, int nthreads) except +

        void set_python_callback(callerfunc call, stopfunc stop, void* func) except +
        void set_nthreads(int nthreads) except +
        void set_resources(float resources) except +

        void enqueue_task(InnerTask* task) except +
        void enqueue_task_unsafe(InnerTask* task) except +

        void run_scheduler() except +
        void run_launcher() except +
        void launch_task(InnerTask* task) except +

        void run() except +
        void stop() except +

        void incr_running_tasks() except +
        void decr_running_tasks() except +
        int get_running_tasks() except +
        int get_running_tasks_unsafe() except +

        void incr_active_tasks() except +
        bool decr_active_tasks() except +
        int get_active_tasks() except +
        int get_active_tasks_unsafe() except +

        void incr_free_threads() except +
        void decr_free_threads() except +
        int get_free_threads() except +
        int get_free_threads_unsafe() except +
        void enqueue_worker(InnerWorker* worker) except +
        InnerWorker* dequeue_worker() except +


        void incr_resources(float resources) except +
        void incr_resources_unsafe(float resources) except +
        void decr_resources(float resources) except +
        void decr_resources_unsafe(float resources) except +
        float get_resources() except +
        float get_resources_unsafe() except +



def hello(task):
    print("Hello from python", flush=True)
    print(task.id)


def log_finalize(filename):
    mystring_ = filename.encode('utf-8')
    log_write(mystring_)

cdef void callback_add(void* python_scheduler, void* python_task, void*
        python_worker) nogil:
    with gil:
        #print("Inside callback to cython", flush=True)
        task = <object>python_task
        scheduler = <object>python_scheduler
        worker = <object>python_worker

        scheduler.cpp_callback(task, worker)
        #print("Done with callback", flush=True)
        #(<object>python_function)(<object>python_input)

cdef void callback_stop(void* python_function) nogil:
    with gil:
        #print("Inside callback to cython (stop)", flush=True)
        scheduler = <object>python_function
        scheduler.stop()

        #(<object>python_function)(<object>python_input)




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

cdef class PyInnerTask:
    cdef InnerTask* task

    def __cinit__(self):
        #print("Made new task (C)", flush=True)
        cdef InnerTask* temp
        temp = new InnerTask()
        self.task = temp

    def __init__(self, long id, object python_task, float vcus):
        cdef InnerTask* temp = self.task

        temp.id = id
        temp.vcus = vcus

        temp.set_task(<void*> python_task)
        name = python_task._taskid.full_name
        name = name.encode('utf-8')
        temp.set_name(name)
        #print("Made new task (Python)", flush=True)
        #print("Task id", self.task.id, flush=True)


    cpdef set_dependencies(self, dependencies):
        for dependency in dependencies:
            inner_dep = dependency.inner_task
            self.add_dependency(inner_dep)

    cpdef add_dependency(self, PyInnerTask dependency):
        task = dependency.task
        cdef InnerTask* p_dep = task
        cdef InnerTask* p_task = self.task
        with nogil:
            p_task.add_dependency(p_dep)

    cpdef blocked(self):
        cdef InnerTask* p_task = self.task
        cdef bool ret = False
        with nogil:
            ret = p_task.blocked()
        return ret

    cpdef blocked_unsafe(self):
        cdef InnerTask* p_task = self.task
        cdef bool ret = False
        with nogil:
            ret = p_task.blocked_unsafe()
        return ret

    cpdef notify_dependents(self, PyInnerScheduler scheduler):
        #print("Notifying dependents (python)", flush=True)
        cdef InnerScheduler* p_sched = scheduler.scheduler
        cdef InnerTask* p_task = self.task
        with nogil:
            p_task.notify_dependents(p_sched)

    cpdef get_num_deps(self):
        return self.task.get_num_deps()

    def __dealloc__(self):
        del self.task

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

            #flat_deps = [dep.task.inner_task for dep in dependencies]
            self.inner_task = PyInnerTask(self.id, self, req.vcus)
            self.inner_task.set_dependencies(dependencies)

            self.context = get_scheduler_context()

            self.result = None

            #self.context.scheduler._task_dict.add(self)
            self.context.scheduler.incr_active_tasks()

            if not self.blocked_unsafe():
                self.context.scheduler.enqueue_task(self)

    @property
    def req(self):
        return self._req

    def _execute_task(self):
        return self._state.func(self, *self._state.args)

    @property
    def task(self):
        return self

    def _finish(self, ctx):
        #ctx.remove_vcus(self.req.vcus)
        pass

    def run(self):
        #print("Running task", self._name, self.id, flush=True)


        try:
            with self._mutex:
                task_state = TaskException(RuntimeError("Unknown Error"))

                try:
                    assert isinstance(self._state, TaskRunning)
                    task_state = self._execute_task()
                    task_state = task_state or TaskCompleted(None)
                except Exception as e:
                    task_state = TaskException(e)
                    print(e)
                finally:
                    ctx = get_scheduler_context()
                    #print("Task Body Finished", flush=True)
                    if isinstance(task_state, TaskCompleted):
                        #print("Task Completed", flush=True)
                        self._notify_dependents(ctx.scheduler.inner_scheduler)
                    self._set_state(task_state, ctx)
                    self._finish(ctx)
        except Exception as e:
            raise e

    def _cleanup(self):
        self._func = None
        self._args = None

    #@profile
    def _set_state(self, new_state, ctx):
        #print("Setting state", new_state, flush=True)
        self._state = new_state

        if isinstance(new_state, TaskException):
            print(TaskException.exc)
            ctx.scheduler.stop()

        elif isinstance(new_state, TaskRunning):
            #print("Spawning Continuation", flush=True)
            #if new_state.dependencies is not None:
            #    flat_deps = [dep.inner_task for dep in new_state.dependencies]
            #else:
            #    flat_deps = None

            #self.inner_task.task.set_type_unsafe(1);
            #print("Task Spawning Continuation", len(new_state.dependencies), flush=True)
            self.set_dependencies(new_state.dependencies)
            #print("Task Spawning Continuation Filtered Deps",
            #        self.inner_task.task.get_num_deps(), flush=True)

            if not self.blocked_unsafe():
                print("Task Queueing Cont.", flush=True)
                ctx.scheduler.enqueue_task(self)
            new_state.dependencies.clear()

        if new_state.is_terminal:
            #self.inner_task.set_complete()
            #Remove from TaskDict
            #ctx.scheduler._task_dict.remove(self)

            #Decrease active task count
            ctx.scheduler.decr_active_task()


    def __await__(self):
        return (yield TaskAwaitTasks([self], self))

    def _notify_dependents(self, scheduler):
        self.inner_task.notify_dependents(scheduler)

    def _add_dependency(self, task):
        self.inner_task.add_dependency(task)

    def blocked(self):
        return self.inner_task.blocked()

    def blocked_unsafe(self):
        return self.inner_task.blocked_unsafe()

    def set_dependencies(self, v):
        #print("Setting dependencies of", self._taskid, flush=True)
        self.inner_task.set_dependencies(v)


class _TaskLocals(threading.local):
    def __init__(self):
        super(_TaskLocals, self).__init__()
        self.task_scopes = []

    @property
    def ctx(self):
        return getattr(self, "_ctx", None)

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
        #print("INNER")
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

cdef class PyInnerWorker:
    cdef InnerWorker* inner_worker

    def __cinit__(self, worker):
        self.inner_worker = new InnerWorker(<void*> worker)
        #print("Created Inner Worker", flush=True)

class WorkerThread(ControllableThread, SchedulerContext):
    def __init__(self, scheduler, index):
        super().__init__()
        self._scheduler = scheduler
        self._monitor = threading.Condition(threading.Lock())
        self.worker = PyInnerWorker(self)
        self.index = index
        self.task = None

    @property
    def scheduler(self):
        return self._scheduler

    def assign_task(self, task):
        #print("Trying to assign task", flush=True)
        with self._monitor:
            #print("Inisde monitor", flush=True)
            if self.task:
                raise Exception("Worker already has a task")
            #print("Assigning task %s to worker %s" % (task.id, self.index), flush=True)
            self.task = task
            #print("Notifying", flush=True)
            self._monitor.notify()

    def _remove_task(self):
        with self._monitor:
            if not self.task:
                raise Exception("Worker does not have a task")
            self.scheduler.decr_running_tasks()
            self.scheduler.incr_resources(self.task.req.vcus)
            self.task = None

    def run(self):
        try:

            with self:
                # print("Starting Task", flush=True)
                self.scheduler.enqueue_worker(self)
                # print("Enqueued worker", flush=True)

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
                        self.scheduler.enqueue_worker(self)
                        #self.scheduler.run_scheduler()
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


cdef class PyInnerScheduler:

    cdef InnerScheduler* scheduler

    def __cinit__(self):
        self.scheduler = new InnerScheduler()

    def __init__(self, int num_threads, float max_resources):
        cdef InnerScheduler* s = self.scheduler
        cdef float c_resources = max_resources
        #with nogil:
        #    s.set_resources(c_resources)

        s.set_resources(c_resources)
        #self.scheduler.set_nthreads(0)

    def set_callback(self, obj):
        #print("Setting callback")
        #print("Setting function", obj)
        cdef callerfunc c_f = <callerfunc> callback_add
        cdef stopfunc c_stop = <stopfunc> callback_stop
        cdef void* c_i = <void*> obj

        cdef InnerScheduler* s = self.scheduler

        #with nogil:
        #    s.set_python_callback(c_f, c_stop, c_i)

        s.set_python_callback(c_f, c_stop, c_i)

    def __dealloc__(self):
        del self.scheduler

    def run(self):
        cdef InnerScheduler* s = self.scheduler
        with nogil:
            s.run()

    def stop(self):
        cdef InnerScheduler* s = self.scheduler
        with nogil:
            s.stop()

    def incr_active_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        # with nogil:
            # s.incr_active_tasks()
        s.incr_active_tasks()

    def decr_active_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        # with nogil:
            # s.decr_active_tasks()
        s.decr_active_tasks()

    def incr_running_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        # with nogil:
            # s.incr_running_tasks()
        s.incr_running_tasks()

    def decr_running_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        #with nogil:
        #    s.decr_running_tasks()
        self.scheduler.decr_running_tasks()

    def incr_free_threads(self):
        cdef InnerScheduler* s = self.scheduler
        with nogil:
            s.incr_free_threads()
        #self.scheduler.incr_free_threads()

    def decr_free_threads(self):
        cdef InnerScheduler* s = self.scheduler
        with nogil:
            s.decr_free_threads()
        #self.scheduler.decr_free_threads()

    def incr_resources(self, float resources):
        cdef InnerScheduler* s = self.scheduler
        cdef float r = resources
        #with nogil:
        #    s.incr_resources(r)
        s.incr_resources(r)
        #self.scheduler.incr_resources(resources)

    def decr_resources(self, float resources):
        cdef InnerScheduler* s = self.scheduler
        cdef float r = resources
        #with nogil:
        #    s.decr_resources(r)
        s.decr_resources(r)
        #self.scheduler.decr_resources(resources)

    def get_active_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        cdef int ret = 0
        #with nogil:
        #    ret = s.get_active_tasks()
        ret = s.get_active_tasks()
        return ret
        #return self.scheduler.get_active_tasks()

    def get_running_tasks(self):
        cdef InnerScheduler* s = self.scheduler
        cdef int ret = 0
        with nogil:
            ret = s.get_running_tasks()
        ret = s.get_running_tasks()
        return ret
        #return self.scheduler.get_running_tasks()

    def get_free_threads(self):
        cdef InnerScheduler* s = self.scheduler
        cdef int ret = 0
        with nogil:
            ret = s.get_free_threads()
        return ret

    def run_scheduler(self):
        cdef InnerScheduler* s = self.scheduler
        with nogil:
            s.run_scheduler()
        #self.scheduler.run_scheduler()

    def enqueue_task(self, PyInnerTask task):
        cdef InnerScheduler* s = self.scheduler
        cdef InnerTask* t = task.task
        #with nogil:
        #    s.enqueue_task(t)
        s.enqueue_task(t)
        #self.scheduler.enqueue_task(task.task)

    def enqueue_worker(self, PyInnerWorker worker):
        cdef InnerScheduler* s = self.scheduler
        cdef InnerWorker* w = worker.inner_worker
        #with nogil:
        #    s.enqueue_worker(w)
        s.enqueue_worker(w)
        #self.scheduler.enqueue_task(task.task)

    def get_status(self):
        return self.scheduler.should_run



class Scheduler(ControllableThread, SchedulerContext):

    def __init__(self, n_threads=8, period=0.001):
        super().__init__()
        self._monitor = threading.Condition(threading.Lock())
        self._exceptions = []

        self.inner_scheduler = PyInnerScheduler(n_threads, 1.0)

        self._worker_threads = [WorkerThread(self, i) for i in range(n_threads)]

        self._launching_phase_monitor = threading.Condition(threading.Lock())

        self.inner_scheduler.set_callback(self)

        for t in self._worker_threads:
            t.start()

        while True:
            if self.get_free_threads() > 0:
                break
            time.sleep(0.0001)

        #print("Scheduler ready", flush=True)
        self.start()


    @property
    def scheduler(self):
        return self

    def __enter__(self):
        if self.get_active_tasks() != 1:
            raise Exception("Scheduler context can only be entered once")
        return super().__enter__()



    def __exit__(self, exc_type, exc_val, exc_tb):
        super().__exit__(exc_type, exc_val, exc_tb)
        self.decr_active_task()

        with self._monitor:
            while self.inner_scheduler.get_status():
                self._monitor.wait()

            for t in self._worker_threads:
                t.join()

            log_finalize("parla.log")

            if self._exceptions:
                raise self._exceptions[0]

    def incr_resources(self, vcus):
        self.inner_scheduler.incr_resources(vcus)

    def decr_resources(self, vcus):
        self.inner_scheduler.decr_resources(vcus)

    def current_resources(self):
        return self.inner_scheduler.get_resources()

    def incr_active_tasks(self):
        self.inner_scheduler.incr_active_tasks()

    def decr_active_task(self):
        done = self.inner_scheduler.decr_active_tasks()
        if done:
            self.stop()

    def cpp_callback(self, task, worker):
        success = False
        worker.assign_task(task)
        success = True
        return success

    def incr_free_threads(self):
        self.inner_scheduler.incr_free_threads()

    def decr_free_threads(self):
        self.inner_scheduler.decr_free_threads()

    def get_free_threads(self):
        return self.inner_scheduler.get_free_threads()

    def get_active_tasks(self):
        return self.inner_scheduler.get_active_tasks()

    def incr_running_tasks(self):
        self.inner_scheduler.incr_running_tasks()

    def decr_running_tasks(self):
        self.inner_scheduler.decr_running_tasks()

    def get_running_tasks(self):
        return self.inner_scheduler.get_running_tasks()

    def enqueue_worker(self, worker):
        self.inner_scheduler.enqueue_worker(worker.worker)

    def enqueue_task(self, task):
        self.inner_scheduler.enqueue_task(task.inner_task)

    def enqueue_task_unsafe(self, task):
        self.inner_scheduler.enqueue_task_unsafe(task.inner_task)

    def run(self):
        self.inner_scheduler.run()

    def stop(self):
        super().stop()

        for w in self._worker_threads:
            w.stop()
        #print("ALL STOPPED", flush=True)

    def run_scheduler(self):
        self.inner_scheduler.run_scheduler()





class Resources:

    def __init__(self, vcus):
        self.vcus = vcus



def _task_callback(task, body):
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


