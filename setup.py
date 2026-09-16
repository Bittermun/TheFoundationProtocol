# SPDX-License-Identifier: Apache-2.0
"""Package the root tools and protocol implementation as one distribution.

The source layout predates the unified install. Explicit package directories
allow wheels to work outside a checkout without sys.path or editable installs.
Root packages take precedence over older copies in the protocol directory.
"""
from setuptools import find_packages, setup

EXCLUDE = ["tests*", "*.tests*", "*.test*", "tfp_testbed*", "*_test*"]
packages = {}
for directory in ("tfp-foundation-protocol", "."):
    for package in find_packages(directory, include=["tfp_*", "demo"], exclude=EXCLUDE):
        packages[package] = f"{directory}/{package.replace('.', '/')}"

setup(packages=sorted(packages), package_dir=packages)
