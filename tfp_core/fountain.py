# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Core Fountain Module

Provides vectorized rateless fountain codecs, deterministic repair seed schedules,
and anti-pollution verification filters.
"""

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    LubyTransformCodec,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)

__all__ = [
    "FountainCodec",
    "FountainDecoder",
    "FountainDroplet",
    "FountainEncoder",
    "LubyTransformCodec",
    "derive_repair_seed_schedule",
    "verify_droplet_seed_authenticity",
]
