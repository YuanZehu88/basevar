"""Setup file and install script for BaseVar.

Version 1.0.0 (Dec 16, 2018)
Copyright (C) 2018 Shujia Huang <huangshujia9@gmail.com>
"""
import os
from Cython.Distutils import build_ext

try:
    from setuptools import setup, find_packages, Extension

    _has_setuptools = True
except ImportError:
    from distutils.core import setup, find_packages
    from distutils.extension import Extension

DESCRIPTION = "BaseVar: A python software for calling variants from ultra low pass WGS data."
DISTNAME = 'basevar'
MAINTAINER = 'Shujia Huang & Siyang Liu'
MAINTAINER_EMAIL = 'huangshujia9@gmail.com'
URL = 'https://github.com/ShujiaHuang/basevar'
LICENSE = 'BSD (3-clause)'
DOWNLOAD_URL = 'https://github.com/ShujiaHuang/basevar'
VERSION = "0.0.1.3"

INCLUDE_DIR = os.path.split(os.path.realpath(__file__))[0] + "/basevar/caller"
CALLER_PRE = 'basevar.caller'
MOD_NAMES = [
    CALLER_PRE + '.algorithm',
]


def make_extension(modname):
    the_cython_file = modname.replace('.', os.path.sep) + '.pyx'
    return Extension(modname, sources=[the_cython_file], language='c', include_dirs=INCLUDE_DIR)


if __name__ == "__main__":
    # requirements_file = os.path.split(os.path.realpath(__file__))[0] + "/requirements.txt"
    long_description = os.path.split(os.path.realpath(__file__))[0] + "/README.rst"
    extensions = [make_extension(name) for name in MOD_NAMES]

    setup(
        name=DISTNAME,
        version=VERSION,
        author=MAINTAINER,
        author_email=MAINTAINER_EMAIL,
        maintainer=MAINTAINER,
        maintainer_email=MAINTAINER_EMAIL,
        description=DESCRIPTION,
        long_description=(open(long_description).read()),
        license=LICENSE,
        url=URL,
        download_url=DOWNLOAD_URL,
        packages=find_packages(),
        include_package_data=True,
        ext_modules=extensions,
        cmdclass={'build_ext': build_ext},
        # install_requires=requirements,
        install_requires=[
            'numpy==1.15.4',
            'pysam==0.12.0.1',
            'scikit-learn==0.20.2',
            'scipy==1.1.0'
        ],

        # scripts=[],
        entry_points={

            'console_scripts': [
                'basevar = basevar.BaseVar:main'
            ]
        },
        classifiers=[
            'Intended Audience :: Science/Research',
            'Programming Language :: Python :: 2.7',
            'Programming Language :: Python :: 3.7',
            'License :: OSI Approved :: BSD License',
            'Topic :: Scientific/Engineering :: Bio-Informatics',
            'Operating System :: POSIX',
            'Operating System :: POSIX :: Linux',
            'Operating System :: MacOS']
    )
