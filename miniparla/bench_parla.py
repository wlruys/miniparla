import csv
import time
import argparse

from parla import Parla
from parla.tasks import spawn, TaskSpace

from sleep.core import bsleep, sleep_with_gil

free_sleep = bsleep
lock_sleep = sleep_with_gil


parser = argparse.ArgumentParser()
parser.add_argument("-workers", type=int, default=1)
parser.add_argument("-n", type=int, default=3)
parser.add_argument("-t", type=int, default=10)
parser.add_argument("-accesses", type=int, default=10)
parser.add_argument("-frac", type=float, default=0.5)
parser.add_argument('-sweep', type=int, default=0)
args = parser.parse_args()


def main(workers, n, t, accesses, frac):
    print("LAUNCH MAIN", flush=True)

    @spawn(vcus=0)
    async def task1():
        cost = 1.0/workers

        kernel_time = t / accesses
        free_time = kernel_time * (1 - frac)
        lock_time = kernel_time * frac

        start_t = time.perf_counter()
        T = TaskSpace("T")

        for i in range(n):
            print(i, flush=True)
            @spawn(T[i], vcus=cost)
            def task1():
                inner_start_t = time.perf_counter()
                for k in range(accesses):
                    free_sleep(free_time)
                    lock_sleep(lock_time)
                inner_end_t = time.perf_counter()
                print("Inner Time: ", inner_end_t - inner_start_t, flush=True)

        await T
        end_t = time.perf_counter()
        print(', '.join([str(workers), str(n), str(t), str(
            accesses), str(frac), str(end_t - start_t)]))

    # @spawn()
    # def test():
    #    print("HELLO", flush=True)


if __name__ == "__main__":

    print(', '.join([str('workers'), str('n'), str('task_time'), str(
        'accesses'), str('frac'), str('total_time')]))
    if not args.sweep:
        with Parla():
            main(args.workers, args.n, args.t, args.accesses, args.frac)
    else:
        for task_time in [100, 500, 1000, 3000, 5000, 7000, 9000, 11000, 13000]:
            for accesses in [1, 5, 10, 20, 50, 100]:
                for nworkers in range(1, args.workers):
                    for frac in [0, 0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]:
                        with Parla():
                            main(nworkers, args.n, task_time, accesses, frac)
