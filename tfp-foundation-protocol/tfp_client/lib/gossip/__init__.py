# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Gossip protocol for P2P mesh networking.

Implements TTL-based message propagation, peer announcements,
and network-wide information dissemination using NostrBridge.
"""

from .gossip_protocol import GossipProtocol, GossipMessage, GossipConfig

__all__ = [
    "GossipProtocol",
    "GossipMessage",
    "GossipConfig",
]
