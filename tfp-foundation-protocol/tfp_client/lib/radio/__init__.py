# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Sub-GHz / LoRa & Physical Radio Packet Subsystem for TFP v4.0.

Provides MTU-constrained packet framing (<240 bytes), CRC16 error detection,
and KISS TNC serial interface for low-bandwidth, long-range amateur radio,
LoRa mesh, and emergency communications infrastructure.
"""

from .framing import RadioPacket, RadioFramePacker, RadioFrameReassembler
from .kiss_interface import KISSInterface, KISSPacket

__all__ = [
    "RadioPacket",
    "RadioFramePacker",
    "RadioFrameReassembler",
    "KISSInterface",
    "KISSPacket",
]
