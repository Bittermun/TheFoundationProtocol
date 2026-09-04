# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer networking module for P2P mesh functionality.

This module provides peer discovery, connection management, and
related P2P networking capabilities for The Foundation Protocol.
"""

from .peer_models import (
    PeerCapabilities,
    PeerInfo,
    Peer,
    ConnectionMetrics,
    PeerConnection,
    PeerFilters,
    PeerDiscoverRequest,
    PeerDiscoverResponse,
    PeerHandshakeRequest,
    PeerHandshakeResponse,
    PeerAnnounceRequest,
    ContentShard,
    ShardLocation,
    MeshRoute,
    GossipMessage,
)
from .peer_repository import PeerRepository
from .peer_discovery import PeerDiscovery, PeerHandshake, CapabilityExchange

__all__ = [
    "PeerCapabilities",
    "PeerInfo", 
    "Peer",
    "ConnectionMetrics",
    "PeerConnection",
    "PeerFilters",
    "PeerDiscoverRequest",
    "PeerDiscoverResponse",
    "PeerHandshakeRequest",
    "PeerHandshakeResponse",
    "PeerAnnounceRequest",
    "ContentShard",
    "ShardLocation",
    "MeshRoute",
    "GossipMessage",
    "PeerRepository",
    "PeerDiscovery",
    "PeerHandshake",
    "CapabilityExchange",
]