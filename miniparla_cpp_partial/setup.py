#!/usr/bin/env python
import sys
import os
from setuptools import setup, Extension
from Cython.Build import cythonize


def scandir(dir, files=[]):
    for file in os.listdir(dir):
        path = os.path.join(dir, file)
        if os.path.isfile(path) and path.endswith(".pyx"):
            files.append(path.replace(os.path.sep, ".")[:-4])
        elif os.path.isdir(path):
            scandir(path, files)
    return files


def makeExtension(extName):
    extPath = extName.replace(".", os.path.sep)+".pyx"

    return Extension(
        extName,
        [extPath],
        language='c++',
        extra_compile_args=["-std=c++20", "-fopenmp", "-lpthread", "-lgomp",
                            "-lm"]
        #       extra_compile_args=["-std=c++11","--expt-extended-lambda", "-Xcudafe","--diag_suppress=esa_on_defaulted_function_ignored"]
    )


extensions = []
extensions.append(Extension("miniparla.task_states", ["miniparla/task_states.pyx"],
                            include_dirs=['miniparla'],
                            library_dirs=['miniparla'],
                            language="c++",
                            extra_compile_args=["-std=c++20", "-fopenmp", "-lpthread", "-lgomp", "-lm"]))

extensions.append(Extension("miniparla.runtime", ["miniparla/runtime.pyx",
                            "miniparla/cpp_runtime.cpp"],
                            include_dirs=['miniparla'],
                            library_dirs=['miniparla'],
                            depends=['miniparla/cpp_runtime.hpp'],
                            extra_compile_args=[
                                "-std=c++20", "-fopenmp", "-lpthread", "-lgomp", "-lm"],
                            language="c++"))


setup(name="miniparla",
      version="0",
      url="https://github.com/ut-parla/Parla.py",
      description="Parla: A heterogenous Python Tasking system",
      packages=['miniparla'],
      ext_modules=cythonize(extensions, language_level="3"),
      include_package_data=True,
      zip_safe=False
      # ext_modules = cache_filler_modules + cython_modules,
      )
