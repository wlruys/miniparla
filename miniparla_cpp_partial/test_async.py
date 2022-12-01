from miniparla import Parla
from miniparla.spawn import spawn
from miniparla.barriers import TaskSpace

from sleep.core import bsleep


def main():

    @spawn(vcus=0)
    async def task1():

        T = TaskSpace("T")

        @spawn(T[0], vcus=0.5)
        def task1():
            print("+HELLO Inner 0", flush=True)
            bsleep(1000)
            print("-HELLO Inner 0", flush=True)
        
        print("Reached Barrier 0", flush=True)
        await T
        print("Passed Barrier 0", flush=True)

        @spawn(T[2], vcus=0.5)
        def task2():
            print("+HELLO Inner 2", flush=True)
            bsleep(1000)
            print("-HELLO Inner 2", flush=True)

        print("Reached Barrier 1", flush=True)
        await T
        print("Passed Barrier 1", flush=True)

        @spawn(T[1], vcus=0.5)
        def task1():
            print("+HELLO Inner 3", flush=True)
            bsleep(1000)
            print("-HELLO Inner 3", flush=True)

    
    # @spawn()
    # def test():
    #    print("HELLO", flush=True)


if __name__ == "__main__":
    with Parla():
        main()
