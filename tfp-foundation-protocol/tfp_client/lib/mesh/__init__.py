# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Offline Mesh & Community Swarm Networking Subsystem for TFP.

Connects local community gateways, peer-to-peer Wi-Fi swarms, and broadcast
streams with content-addressed LRU caching and seed reconciliation.
"""

from .gateway import MeshGatewayNode
from .peer_sync import PeerSyncManager, DropletReconciliationMessage

__all__ = [
    "MeshGatewayNode",
    "PeerSyncManager",
    "DropletReconciliationMessage",
]
