"""Python driver and command line tool for Honeywell Midas gas detectors."""
from sys import version_info

from setuptools import setup

if version_info < (3, 7):
    raise ImportError("This module requires Python >=3.7.  Use 0.4.4 for Python3.6")

with open('README.md', 'r') as in_file:
    long_description = in_file.read()

setup(
    name="midas",
    version="0.5.0",
    description="Python driver for Honeywell Midas gas detectors.",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url="http://github.com/numat/midas/",
    author="Patrick Fuller",
    author_email="pat@numat-tech.com",
    packages=['midas'],
    package_data={'midas': ['faults.csv']},
    install_requires=[
        'pymodbus>=2.4.0,<3; python_version == "3.7"',
        'pymodbus[serial]>=2.4.0; python_version == "3.8"',
        'pymodbus[serial]>=2.4.0; python_version == "3.9"',
        'pymodbus[serial]>=3.0.0; python_version >= "3.10"',
    ],
    extras_require={
        'test': [
            'pytest',
            'pytest-cov',
            'pytest-asyncio',
        ],
    },
    entry_points={
        'console_scripts': [('midas = midas:command_line')]
    },
    license='GPLv2',
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Scientific/Engineering :: Human Machine Interfaces'
    ]
)
