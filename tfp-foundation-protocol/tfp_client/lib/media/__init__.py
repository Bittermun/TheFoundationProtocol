# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Resilient Media & Video Streaming Subsystem for The Foundation Protocol.

Combines FastCDC boundary chunking, Merkle verification trees, and rateless
Fountain codes with O(1) anti-pollution packet authentication to deliver
high-efficiency video and audio streaming across lossy wireless channels.
"""

from .stream_packager import MediaManifest, MediaStreamPackager
from .fountain_streamer import FountainStreamer, MediaDropletPacket
from .receiver import FountainStreamReceiver

__all__ = [
    "MediaManifest",
    "MediaStreamPackager",
    "FountainStreamer",
    "MediaDropletPacket",
    "FountainStreamReceiver",
]
