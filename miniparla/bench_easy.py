from miniparla import Parla
from miniparla.runtime import spawn, TaskSpace

from sleep.core import bsleep

import argparse
import time

class Parser:
    pass

args = Parser()
args.workers = 4
args.n = 10
args.t = 50000

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
