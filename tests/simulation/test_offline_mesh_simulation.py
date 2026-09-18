# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Offline Mesh & Community Swarm Networking.

Verifies:
1. Gateway LRU cache bridging and media lookups.
2. PeerSyncManager missing-seed reconciliation with minimal wire overhead.
3. 5-node community swarm reconstruction when upstream tower cuts off midway.
4. Node churn survival (peer disconnects and reconnects during sync).
"""

import asyncio
import hashlib
from pathlib import Path
import random
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork
from tfp_client.lib.mesh.gateway import MeshGatewayNode
from tfp_client.lib.mesh.peer_sync import PeerSyncManager
from tfp_client.lib.media.stream_packager import MediaManifest


def test_gateway_lru_cache_bridge():
    """Verify MeshGatewayNode caches media and responds to lookups."""
    gateway = MeshGatewayNode("gateway_test", cache_max_items=10)
    manifest = MediaManifest(
        manifest_id="test_manifest_id_123",
        media_type="application/octet-stream",
        total_size=1024,
        chunk_count=2,
        merkle_root="abc123merkle",
        chunk_hashes=["hash1", "hash2"],
        chunk_sizes=[512, 512],
    )
    payload = b"LOCAL-CLINIC-CACHED-PAYLOAD-" * 32
    gateway.cache_media(manifest, payload)

    assert gateway.get_cached_media(manifest.manifest_id) == payload
    assert gateway.get_cached_media(manifest.merkle_root) == payload
    assert gateway.served_from_cache == 2


@pytest.mark.asyncio
async def test_peer_sync_minimal_wire_reconciliation():
    """Verify PeerSyncManager transmits only non-overlapping missing droplets."""
    codec = FountainCodec(symbol_size=128)
    data = b"RECONCILIATION-TEST-PAYLOAD:" * 64
    droplets, k, orig_len = codec.encode(data, redundancy=0.50)

    node_a = MeshPeer("node_a", symbol_size=128)
    node_b = MeshPeer("node_b", symbol_size=128)
    node_a.connect(node_b)

    # Node A holds first 10 droplets, Node B holds droplets 5..15
    for d in droplets[:10]:
        if "root" not in node_a.droplet_store:
            node_a.droplet_store["root"] = {}
        node_a.droplet_store["root"][d.seed] = d

    for d in droplets[5:15]:
        if "root" not in node_b.droplet_store:
            node_b.droplet_store["root"] = {}
        node_b.droplet_store["root"][d.seed] = d

    # Pre-reconciliation check
    assert len(node_a.droplet_store["root"]) == 10
    assert len(node_b.droplet_store["root"]) == 10

    sent_a_to_b, sent_b_to_a = await PeerSyncManager.reconcile(node_a, node_b, "root")

    # Seeds 0..4 missing in B (5 droplets sent from A to B)
    assert sent_a_to_b == 5
    # Seeds 10..14 missing in A (5 droplets sent from B to A)
    assert sent_b_to_a == 5

    # Both nodes now hold all 15 droplets
    assert len(node_a.droplet_store["root"]) == 15
    assert len(node_b.droplet_store["root"]) == 15


@pytest.mark.asyncio
async def test_offline_swarm_recovery_under_broadcast_cutoff():
    """Verify 4-node swarm bit-exact recovery after upstream broadcast terminates early."""
    payload = b"OFFLINE-SWARM-EMERGENCY-DISPATCH:" * 64
    expected_hash = hashlib.sha3_256(payload).hexdigest()

    codec = FountainCodec(symbol_size=128)
    droplets, k, orig_len = codec.encode(payload, redundancy=0.60)
    total_droplets = len(droplets)

    net = SwarmNetwork()
    gateway = MeshGatewayNode("gateway_clinic", symbol_size=128)
    alice = net.add_peer("peer_alice", symbol_size=128)
    bob = net.add_peer("peer_bob", symbol_size=128)
    charlie = net.add_peer("peer_charlie", symbol_size=128)

    gateway.connect(alice)
    alice.connect(bob)
    bob.connect(charlie)

    # Partial broadcast simulation:
    chunker = ContentDefinedChunker(min_size=512, target_size=1024, max_size=2048)
    recipe, _ = chunker.create_recipe(payload)

    # Tower cuts off after sending 35% to Alice, 35% to Bob, 20% to Charlie
    alice.store_content(recipe, droplets[: int(total_droplets * 0.35)], "root")
    bob.store_content(recipe, droplets[int(total_droplets * 0.30): int(total_droplets * 0.65)], "root")
    charlie.store_content(recipe, droplets[int(total_droplets * 0.60): int(total_droplets * 0.85)], "root")
    gateway.store_content(recipe, droplets[int(total_droplets * 0.70):], "root")

    # Reconcile peer links
    await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    await PeerSyncManager.reconcile(bob, charlie, recipe.root_hash)
    await PeerSyncManager.reconcile(gateway, alice, recipe.root_hash)
    await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    await PeerSyncManager.reconcile(bob, charlie, recipe.root_hash)

    # All nodes must achieve bit-exact reconstruction
    for peer in [gateway, alice, bob, charlie]:
        held = list(peer.droplet_store[recipe.root_hash].values())
        recovered = codec.decode(held, k=k, orig_len=orig_len)
        assert hashlib.sha3_256(recovered).hexdigest() == expected_hash


@pytest.mark.asyncio
async def test_mesh_churn_resilience():
    """Verify nodes survive intermittent churn (disconnects/reconnects) and complete sync."""
    payload = b"CRITICAL-RESILIENCE-TELEMETRY:" * 32
    codec = FountainCodec(symbol_size=128)
    droplets, k, orig_len = codec.encode(payload, redundancy=0.50)

    chunker = ContentDefinedChunker(min_size=512, target_size=1024, max_size=2048)
    recipe, _ = chunker.create_recipe(payload)

    alice = MeshPeer("alice", symbol_size=128)
    bob = MeshPeer("bob", symbol_size=128)
    alice.connect(bob)

    alice.store_content(recipe, droplets[:k], "root")
    bob.store_content(recipe, droplets[k:], "root")

    # Bob goes temporarily offline (simulating battery save / out of range)
    bob.is_alive = False
    sent_a, sent_b = await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    assert sent_a == 0 and sent_b == 0  # no transfer while offline

    # Bob comes back online
    bob.is_alive = True
    sent_a, sent_b = await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    assert sent_a > 0
    assert sent_b > 0

    # Both nodes decode successfully
    recovered_alice = codec.decode(list(alice.droplet_store[recipe.root_hash].values()), k, orig_len)
    recovered_bob = codec.decode(list(bob.droplet_store[recipe.root_hash].values()), k, orig_len)

    assert recovered_alice == payload
    assert recovered_bob == payload
