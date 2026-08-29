# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer-to-Peer Mesh & Swarm Network Transport for TFP v4.0

Supports asynchronous gossip recipe announcements, lossy swarm transfer,
and origin node churn survival.
"""

import asyncio
from dataclasses import dataclass
import hashlib
import random
from typing import Dict, List, Optional, Set

from .cdc import ChunkRecipe
from .fountain import FountainCodec, FountainDroplet


@dataclass
class GossipMessage:
    """A peer-to-peer announcement message."""

    msg_id: str
    sender_id: str
    recipe: ChunkRecipe
    merkle_root: str
    ttl: int = 4


class MeshPeer:
    """An autonomous node in the TFP decentralized mesh network."""

    def __init__(self, node_id: str, loss_rate: float = 0.0):
        self.node_id = node_id
        self.loss_rate = loss_rate
        self.neighbors: Set["MeshPeer"] = set()
        self.known_recipes: Dict[str, ChunkRecipe] = {}
        self.merkle_roots: Dict[str, str] = {}
        self.droplet_store: Dict[str, Dict[int, FountainDroplet]] = {}
        self.reconstructed_payloads: Dict[str, bytes] = {}
        self.seen_gossip: Set[str] = set()
        self.codec = FountainCodec(symbol_size=256)
        self.is_alive = True

    def connect(self, peer: "MeshPeer"):
        """Establish bidirectional link with another peer."""
        self.neighbors.add(peer)
        peer.neighbors.add(self)

    def store_content(self, recipe: ChunkRecipe, droplets: List[FountainDroplet], merkle_root: str):
        """Store locally published or received content."""
        root = recipe.root_hash
        self.known_recipes[root] = recipe
        self.merkle_roots[root] = merkle_root
        if root not in self.droplet_store:
            self.droplet_store[root] = {}
        for d in droplets:
            self.droplet_store[root][d.seed] = d

    async def broadcast_gossip(self, recipe: ChunkRecipe, merkle_root: str):
        """Broadcast recipe announcement to all connected neighbors."""
        msg_id = hashlib.sha3_256(f"{self.node_id}:{recipe.root_hash}:{random.random()}".encode()).hexdigest()  # nosec B311
        msg = GossipMessage(
            msg_id=msg_id,
            sender_id=self.node_id,
            recipe=recipe,
            merkle_root=merkle_root,
        )
        self.seen_gossip.add(msg_id)
        for neighbor in list(self.neighbors):
            if neighbor.is_alive:
                asyncio.create_task(neighbor.receive_gossip(msg))

    async def receive_gossip(self, msg: GossipMessage):
        """Handle incoming gossip announcement and forward if not seen."""
        if not self.is_alive or msg.msg_id in self.seen_gossip:
            return
        self.seen_gossip.add(msg.msg_id)
        self.known_recipes[msg.recipe.root_hash] = msg.recipe
        self.merkle_roots[msg.recipe.root_hash] = msg.merkle_root

        # Forward gossip with decremented TTL
        if msg.ttl > 1:
            fwd_msg = GossipMessage(
                msg_id=msg.msg_id,
                sender_id=self.node_id,
                recipe=msg.recipe,
                merkle_root=msg.merkle_root,
                ttl=msg.ttl - 1,
            )
            for neighbor in list(self.neighbors):
                if neighbor.is_alive and neighbor.node_id != msg.sender_id:
                    asyncio.create_task(neighbor.receive_gossip(fwd_msg))

    async def request_droplets(self, root_hash: str) -> List[FountainDroplet]:
        """Request available droplets from this peer subject to link loss."""
        if not self.is_alive:
            return []
        if root_hash not in self.droplet_store:
            return []
        results = []
        for d in self.droplet_store[root_hash].values():
            if random.random() >= self.loss_rate:  # nosec B311: Network loss simulator
                results.append(d)
        return results

    async def swarm_fetch(self, root_hash: str) -> Optional[bytes]:
        """Gather fountain droplets from all reachable peers and reconstruct payload."""
        if not self.is_alive:
            return None
        if root_hash in self.reconstructed_payloads:
            return self.reconstructed_payloads[root_hash]
        if root_hash not in self.known_recipes:
            raise KeyError(f"Unknown root hash: {root_hash}")

        recipe = self.known_recipes[root_hash]
        k = (recipe.total_size + self.codec.symbol_size - 1) // self.codec.symbol_size

        gathered_droplets: Dict[int, FountainDroplet] = {}
        if root_hash in self.droplet_store:
            gathered_droplets.update(self.droplet_store[root_hash])

        # Query all live neighbors in parallel
        peers_to_query = [p for p in self.neighbors if p.is_alive]
        for peer in peers_to_query:
            incoming = await peer.request_droplets(root_hash)
            for d in incoming:
                gathered_droplets[d.seed] = d
                if len(gathered_droplets) >= k:
                    # Attempt decode
                    try:
                        recovered = self.codec.decode(
                            list(gathered_droplets.values()),
                            k=k,
                            orig_len=recipe.total_size,
                        )
                        self.reconstructed_payloads[root_hash] = recovered
                        self.droplet_store[root_hash] = gathered_droplets
                        return recovered
                    except Exception:  # nosec B112: Try decoding on each incoming droplet
                        continue

        # Final decode attempt if rank was achieved
        if len(gathered_droplets) >= k:
            try:
                recovered = self.codec.decode(
                    list(gathered_droplets.values()),
                    k=k,
                    orig_len=recipe.total_size,
                )
                self.reconstructed_payloads[root_hash] = recovered
                return recovered
            except Exception as e:
                raise RuntimeError(f"Swarm decoding failed: {e}")

        raise RuntimeError(f"Insufficient droplets gathered: {len(gathered_droplets)} < {k}")


class SwarmNetwork:
    """Manages multi-node virtual mesh topologies for verification and simulation."""

    def __init__(self):
        self.peers: Dict[str, MeshPeer] = {}

    def add_peer(self, node_id: str, loss_rate: float = 0.0) -> MeshPeer:
        peer = MeshPeer(node_id, loss_rate=loss_rate)
        self.peers[node_id] = peer
        return peer

    def connect_all(self):
        """Full mesh interconnection."""
        nodes = list(self.peers.values())
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                nodes[i].connect(nodes[j])
