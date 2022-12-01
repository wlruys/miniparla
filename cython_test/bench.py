from miniparla import Parla
from miniparla.spawn import spawn
from miniparla.barriers import TaskSpace

from sleep.core import bsleep

import argparse
import time

parser = argparse.ArgumentParser()
parser.add_argument("-workers", type=int, default=1)
parser.add_argument("-n", type=int, default=3)
parser.add_argument("-t", type=int, default=10)
args = parser.parse_args()

def main():

    @spawn(vcus=0)
    async def task1():
        cost = 1.0/args.workers

        start_t = time.perf_counter()
        T = TaskSpace("T")

        for i in range(args.n):
            @spawn(T[i], vcus=cost)
            async def task1():
                bsleep(args.t)

        await T
        end_t = time.perf_counter()
        print("Time: ", end_t - start_t, flush=True)

    #@spawn()
    #def test():
    #    print("HELLO", flush=True)



if __name__ == "__main__":
    with Parla():
        main()
