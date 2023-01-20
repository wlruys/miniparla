import argparse
import numpy as np
import numba
from numba import njit, jit

import math
import time

import nvtx

from miniparla import Parla
from miniparla.barriers import TaskSpace, Tasks
from miniparla.spawn import spawn

from sleep.core import bsleep, sleep_with_gil

free_sleep = bsleep
lock_sleep = sleep_with_gil


def waste_time(free_time, gil_time, accesses):
    for k in range(accesses):
        free_sleep(free_time)
        lock_sleep(gil_time)


@jit(nogil=True, parallel=False)
def increment(array, counter):
    for i in range(array.shape[0]):
        for j in range(array.shape[1]):
            array[i, j] += np.random.rand()


def increment_wrapper(array, counter):
    increment(array, counter)


def main(N, d, steps, NUM_WORKERS, WIDTH, cpu_array, sync_flag, vcu_flag,
         dep_flag, verbose, sleep_time, accesses, gil_fraction,
         sleep_flag, strong_flag, restrict_flag):

    @spawn(vcus=0)
    async def main_task():

        T = TaskSpace("Outer")

        start_t = time.perf_counter()
        for t in range(steps):

            if restrict_flag:
                odeps = [T[1, t-1, l] for l in range(WIDTH)]

            for ng in range(WIDTH):

                if not dep_flag or (t == 0):
                    deps = []
                else:
                    if restrict_flag:
                        deps = odeps
                    else:
                        deps = [T[1, t-1, ng]]

                vcus = 1.0/NUM_WORKERS

                kernel_time = sleep_time / accesses

                if strong_flag:
                    kernel_time = kernel_time / NUM_WORKERS

                free_time = kernel_time * (1.0 - gil_fraction)
                lock_time = kernel_time * gil_fraction

                @spawn(T[1, t, ng], dependencies=deps, vcus=vcus)
                def task():
                    nvtx.push_range(message="Outer", domain="compute")
                    if verbose:
                        print("Task", [1, ng, t], "Started.", flush=True)
                        inner_start_t = time.perf_counter()

                    if sleep_flag:
                        waste_time(free_time, lock_time, accesses)
                    else:
                        array = cpu_array[ng]
                        increment_wrapper(array, 100000)

                    if verbose:
                        inner_end_t = time.perf_counter()
                        inner_elapsed = inner_end_t - inner_start_t

                        print("Task", [1, ng, t], "Finished. I took ",
                              inner_elapsed, flush=True)
                        #print("I am task", [1, t, ng], ". I took ", inner_elapsed, ". on device", A.device, flush=True)
                    nvtx.pop_range(domain="compute")

            if sync_flag:
                if verbose:
                    print("Task WAIT ", t, flush=True)
                if restrict_flag:
                    await Tasks([T[1, t, l] for l in range(WIDTH)])
                else:
                    await T
                    if verbose:
                        print("Task WAKE ", t, flush=True)

        if not sync_flag:
            if restrict_flag:
                await Tasks([T[1, steps-1, l] for l in range(WIDTH)])
            else:
                await T
        end_t = time.perf_counter()

        elapsed = end_t - start_t
        print(', '.join([str(NUM_WORKERS), str(steps), str(sleep_time),
              str(accesses), str(gil_fraction), str(elapsed)]), flush=True)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--width', type=int, default=0)
    parser.add_argument('--steps', type=int, default=1)
    parser.add_argument('-d', type=int, default=7)
    parser.add_argument('-n', type=int, default=2**23)
    parser.add_argument('--isync', type=int, default=0)
    parser.add_argument('--vcus', type=int, default=0)
    parser.add_argument('--deps', type=int, default=1)
    parser.add_argument('--verbose', type=int, default=0)

    parser.add_argument("-t", type=int, default=10)
    parser.add_argument("--accesses", type=int, default=10)
    parser.add_argument("--frac", type=float, default=0)

    parser.add_argument('--strong', type=int, default=0)
    parser.add_argument('--sleep', type=int, default=1)
    parser.add_argument('--restrict', type=int, default=0)

    args = parser.parse_args()
    if args.width == 0:
        args.width = args.workers

    NUM_WORKERS = args.workers
    STEPS = args.steps
    N = args.n
    d = args.d
    isync = args.isync

    if args.strong:
        N = N//NUM_WORKERS

    cpu_array = []
    for ng in range(NUM_WORKERS):
        # cp.cuda.set_allocator(cp.cuda.MemoryAsyncPool().malloc)
        cpu_array.append(np.zeros([N, d]))
        increment_wrapper(cpu_array[ng], 1)

    def drange(start, stop):
        while start < stop:
            yield start
            start <<= 1


    nvtx.push_range(message="Main")

    print(', '.join([str('workers'), str('n'), str('task_time'), str(
        'accesses'), str('frac'), str('total_time')]), flush=True)
    for task_time in [10000]:
        for accesses in [1]:
            for nworkers in drange(1, args.workers):
                for frac in [0]:
                    with Parla():
                        main(N, d, STEPS, nworkers, nworkers, cpu_array, isync, args.vcus,
                             args.deps, args.verbose, task_time, accesses, frac,
                             args.sleep, args.strong, args.restrict)

    nvtx.pop_range()

