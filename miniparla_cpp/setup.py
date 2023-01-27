#!/usr/bin/env python
import sys
import os
from setuptools import setup, Extension
from Cython.Build import cythonize

logging = False
debug = True

nvtx_include = os.getenv("NVTX_INCLUDE", None)

nvtx_flag = False

if nvtx_include is not None:
    nvtx_flag = True

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

compile_args =["-std=c++20", "-fopenmp", "-lpthread", "-lgomp", "-lm", "-O3"]
compile_args_debug = ["-std=c++20", "-fopenmp", "-lpthread", "-lgomp", "-lm", "-g", "-O0"]

if debug:
    compile_args = compile_args_debug

compile_args += ["-ldl", "-fno-stack-protector"]

if nvtx_flag:
    include_dirs = [nvtx_include]
    compile_args += ["-DNVTX_ENABLE"]
    print("BUILDING WITH NVTX SUPPORT")
else:
    include_dirs = []



if logging:
    log_include = "/home/will/workspace/binlog/install/usr/local/include/"
    log_lib = "/home/will/workspace/binlog/install/usr/local/lib/"
    compile_args += ["-DPARLA_LOGGING"]
else:
    log_include = ""
    log_lib = ""

#python_include = "/home/will/miniconda3/include/python3.9/"

if logging:
    include_dirs += [log_include]
    library_dirs = [log_lib]
else:
    include_dirs += []
    library_dirs = []

extensions = []
extensions.append(Extension("miniparla.task_states", ["miniparla/task_states.pyx"],
                            include_dirs=['miniparla']+include_dirs,
                            library_dirs=['miniparla']+library_dirs,
                            emit_linenums=True,
                            extra_compile_args=compile_args,
                            language="c++"
                            )
                  )

extensions.append(Extension("miniparla.runtime", ["miniparla/runtime.pyx",
                            "miniparla/cpp_runtime.cpp"],
                            include_dirs=['miniparla']+include_dirs,
                            library_dirs=['miniparla']+library_dirs,
                            depends=['miniparla/cpp_runtime.hpp'],
                            extra_compile_args=compile_args,
                            emit_linenums=True,
                            language="c++"
                            )
                  )


setup(name="miniparla",
      version="0",
      url="https://github.com/ut-parla/Parla.py",
      description="Parla: A heterogenous Python Tasking system",
      packages=['miniparla'],
      ext_modules=cythonize(extensions, language_level="3", emit_linenums=True),
      include_package_data=True,
      zip_safe=False
      # ext_modules = cache_filler_modules + cython_modules,
      )
