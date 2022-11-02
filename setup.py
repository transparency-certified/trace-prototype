#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = ["Click>=7.0", "waitress", "flask", "requests"]

test_requirements = [
    "pytest>=3",
]

setup(
    author="Kacper Kowalik",
    author_email="xarthisius.kk@gmail.com",
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    description=(
        "Proposed end-to-end prototype for TRACE project design discussions."
    ),
    entry_points={
        "console_scripts": [
            "trace-poc=trace_poc.cli:main",
            "trace-poc-serve=trace_poc.serve:main",
        ],
    },
    install_requires=requirements,
    license="BSD license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="trace_poc",
    name="trace_poc",
    packages=find_packages(include=["trace_poc", "trace_poc.*"]),
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/Xarthisius/trace_poc",
    version="0.1.0",
    zip_safe=False,
)
