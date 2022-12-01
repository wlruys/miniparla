from miniparla import Parla
from miniparla.runtime import spawn, TaskSpace

from sleep.core import bsleep


def main():

    T = TaskSpace("T")

    @spawn(T[0], vcus=0.5)
    def task1():
        print("+HELLO OUTER 0", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 0", flush=True)

    @spawn(T[1], vcus=0.5)
    def task1():
        print("+HELLO OUTER 1", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 1", flush=True)

    @spawn(T[2], vcus=0.5, dependencies=[T[0], T[1]])
    def task2():
        print("+HELLO OUTER 2", flush=True)
        bsleep(1000)
        print("-HELLO OUTER 2", flush=True)

    # @spawn()
    # def test():
    #    print("HELLO", flush=True)


if __name__ == "__main__":
    with Parla():
        main()
