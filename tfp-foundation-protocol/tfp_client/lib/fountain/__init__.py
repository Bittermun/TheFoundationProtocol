# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Fountain & Erasure Coding Module for The Foundation Protocol.
"""

from tfp_client.lib.fountain.fountain_real import (
    BinaryLinearErasureCodec,
    IntegrityError,
    RealRaptorQAdapter,
)

__all__ = [
    "BinaryLinearErasureCodec",
    "IntegrityError",
    "RealRaptorQAdapter",
]
