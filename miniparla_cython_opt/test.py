from miniparla import Parla
from miniparla.spawn import spawn
from miniparla.barriers import TaskSpace

def main():

    T = TaskSpace("T")

    @spawn(vcus=0.5)
    async def task1():

        print("HELLO OUTER 0", flush=True)

        @spawn(T[0], vcus=0.5)
        async def task2():
            print("HELLO INNER 0", flush=True)

        await T
        print("HELLO OUTER 1", flush=True)

    #@spawn()
    #def test():
    #    print("HELLO", flush=True)



if __name__ == "__main__":
    with Parla():
        main()
