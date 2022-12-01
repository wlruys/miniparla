#!/usr/bin/env python

import os
from setuptools import setup, Extension
from Cython.Build import cythonize

"""
cython_modules = cythonize('parla/*.pyx')

cache_filler_modules = []
for i in range(128):
      module_name = 'cache_filler_' + str(i)
      module = Extension("parla." + module_name,
                          define_macros = [('MODULE_NAME', module_name)],
                          sources = ['cache_filler.c'])
      cache_filler_modules.append(module)
"""

setup(name = "miniparla",
      version = "0",
      url = "https://github.com/ut-parla/Parla.py",
      description = "Parla: A heterogenous Python Tasking system",
      packages = ['miniparla'],
      #ext_modules = cache_filler_modules + cython_modules,
      )
