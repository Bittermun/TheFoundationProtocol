# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from .ndn_real import Data, Interest, RealNDNAdapter


class NDNAdapter(RealNDNAdapter):
    """Production Named Data Networking (NDN) adapter backed by blob store and async transport."""
    pass
