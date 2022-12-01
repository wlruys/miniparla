from miniparla import Parla
from miniparla.spawn import spawn
from miniparla.barriers import TaskSpace

from sleep.core import bsleep


def main():

    T = TaskSpace("T")

    @spawn(T[0], vcus=0.5)
    def task1():
        print("+HELLO OUTER 0", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 0", flush=True)
    
    @spawn(T[2], vcus=0.5, dependencies=[])
    def task2():
        print("+HELLO OUTER 2", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 2", flush=True)

    @spawn(T[1], vcus=0.5)
    def task1():
        print("+HELLO OUTER 1", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 1", flush=True)
    
    # @spawn()
    # def test():
    #    print("HELLO", flush=True)


if __name__ == "__main__":
    with Parla():
        main()
