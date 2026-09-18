# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer-to-Peer Droplet Reconciliation and Sync Engine for TFP v4.0.

Provides efficient seed set reconciliation between adjacent mesh nodes,
minimizing wireless channel utilization by transmitting only missing droplets.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple

_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.fountain import FountainDroplet
from tfp_core_v4.mesh import MeshPeer

log = logging.getLogger("tfp.mesh.sync")


@dataclass
class DropletReconciliationMessage:
    """Message carrying a set of held droplet seeds for a specific content hash."""

    sender_id: str
    root_hash: str
    held_seeds: Set[int]


class PeerSyncManager:
    """
    Coordinates minimal-bandwidth droplet synchronization between mesh peers.
    """

    @staticmethod
    def compute_missing_seeds(held_by_peer: Set[int], held_locally: Set[int]) -> Set[int]:
        """Compute the set of seeds that local node has but peer lacks."""
        return held_locally - held_by_peer

    @classmethod
    async def reconcile(
        cls,
        node_a: MeshPeer,
        node_b: MeshPeer,
        root_hash: str,
    ) -> Tuple[int, int]:
        """
        Bidirectionally reconcile droplets for root_hash between node_a and node_b.
        Transmits only the complementary missing droplets.

        Returns:
            (droplets_sent_a_to_b, droplets_sent_b_to_a)
        """
        if not (node_a.is_alive and node_b.is_alive):
            return (0, 0)

        seeds_a = set(node_a.droplet_store.get(root_hash, {}).keys())
        seeds_b = set(node_b.droplet_store.get(root_hash, {}).keys())

        missing_in_b = cls.compute_missing_seeds(held_by_peer=seeds_b, held_locally=seeds_a)
        missing_in_a = cls.compute_missing_seeds(held_by_peer=seeds_a, held_locally=seeds_b)

        sent_a_to_b = 0
        sent_b_to_a = 0

        # Transfer missing droplets from A to B
        store_a = node_a.droplet_store.get(root_hash, {})
        if root_hash not in node_b.droplet_store:
            node_b.droplet_store[root_hash] = {}
        for seed in missing_in_b:
            if seed in store_a:
                node_b.droplet_store[root_hash][seed] = store_a[seed]
                sent_a_to_b += 1

        # Transfer missing droplets from B to A
        store_b = node_b.droplet_store.get(root_hash, {})
        if root_hash not in node_a.droplet_store:
            node_a.droplet_store[root_hash] = {}
        for seed in missing_in_a:
            if seed in store_b:
                node_a.droplet_store[root_hash][seed] = store_b[seed]
                sent_b_to_a += 1

        # Share recipe if known
        if root_hash in node_a.known_recipes and root_hash not in node_b.known_recipes:
            node_b.known_recipes[root_hash] = node_a.known_recipes[root_hash]
        elif root_hash in node_b.known_recipes and root_hash not in node_a.known_recipes:
            node_a.known_recipes[root_hash] = node_b.known_recipes[root_hash]

        return (sent_a_to_b, sent_b_to_a)
