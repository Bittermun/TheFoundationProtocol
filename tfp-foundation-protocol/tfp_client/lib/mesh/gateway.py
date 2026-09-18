# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Community Swarm Gateway Node for TFP v4.0.

Bridges incoming long-range broadcast streams to local Wi-Fi peer meshes,
maintaining an LRU content cache and serving reconstructed chunks to mobile edge peers.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple

_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_core_v4.cdc import ChunkRecipe
from tfp_core_v4.fountain import FountainDroplet
from tfp_core_v4.mesh import MeshPeer
from tfp_client.lib.cache.content_cache import ContentCache
from tfp_client.lib.media.stream_packager import MediaManifest

log = logging.getLogger("tfp.mesh.gateway")


class MeshGatewayNode(MeshPeer):
    """
    Autonomous community gateway node.
    Caches verified content in a thread-safe LRU ContentCache, responds to peer
    reconciliation queries, and bridges broadcast data to edge peers.
    """

    def __init__(
        self,
        node_id: str = "gateway_node",
        cache_max_items: int = 500,
        cache_ttl_seconds: Optional[int] = 3600,
        loss_rate: float = 0.0,
        symbol_size: int = 256,
    ):
        super().__init__(node_id=node_id, loss_rate=loss_rate, symbol_size=symbol_size)
        self.cache = ContentCache(maxsize=cache_max_items, ttl_seconds=cache_ttl_seconds)
        self.manifest_registry: Dict[str, MediaManifest] = {}
        self.served_from_cache: int = 0
        self.served_from_droplets: int = 0

    def cache_media(self, manifest: MediaManifest, payload: bytes):
        """Store verified reconstructed media stream in local gateway cache."""
        self.manifest_registry[manifest.manifest_id] = manifest
        self.manifest_registry[manifest.merkle_root] = manifest

        # Cache full payload
        self.cache.put(manifest.manifest_id, payload)
        self.cache.put(manifest.merkle_root, payload)

        # Pre-seed internal reconstruction store for mesh peers
        self.reconstructed_payloads[manifest.merkle_root] = payload
        self.reconstructed_payloads[manifest.manifest_id] = payload

    def get_cached_media(self, identifier: str) -> Optional[bytes]:
        """Query gateway LRU cache for content bytes by manifest ID or Merkle root."""
        cached = self.cache.get(identifier)
        if cached is not None:
            self.served_from_cache += 1
        return cached

    async def serve_peer_request(self, root_hash: str) -> List[FountainDroplet]:
        """
        Serve droplets to a requesting peer. If payload is cached, dynamically
        synthesizes full-rank droplets.
        """
        droplets = await self.request_droplets(root_hash)
        if droplets:
            self.served_from_droplets += len(droplets)
        return droplets
