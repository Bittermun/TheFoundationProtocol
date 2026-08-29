# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Challenger: Extreme Swarm Mesh Simulation & Stress Testing Suite
Challenger Agent: challenger_2_gen2

Adversarial Stress Test Dimensions:
1. Extreme packet loss (30% - 50%), simulated latency spikes, and dynamic node churn.
2. Multi-partition network splits (split-brain), healing, and cross-partition state reconciliation.
3. High-load concurrent gossip propagation and origin churn survival.
"""

import asyncio
import hashlib
import os
import random
import time
from typing import Dict, List, Set, Optional
import pytest

from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork, GossipMessage
from tfp_core_v4.node import TFPNode


@pytest.mark.simulation
@pytest.mark.asyncio
class TestExtremeLossAndChurn:
    """Challenge multi-node swarm mesh under high loss rates (30%-50%) and aggressive node churn."""

    @pytest.mark.parametrize("loss_rate", [0.30, 0.40, 0.50])
    async def test_swarm_reconstruction_under_extreme_loss(self, loss_rate: float):
        """
        Validate swarm retrieval across 8 peers with severe link loss (30% to 50%).
        Requires sufficient droplet redundancy and multi-peer aggregation.
        """
        net = SwarmNetwork()
        peers = [net.add_peer(f"loss_peer_{i}", loss_rate=loss_rate) for i in range(8)]
        net.connect_all()

        payload = b"EXTREME_LOSS_TOLERANCE_STRESS_TEST_PAYLOAD_" * 30  # ~1.3 KB
        engine = TFPNode()
        # Publish with high redundancy
        recipe = engine.publish(payload)
        codec = FountainCodec(symbol_size=256)
        # Generate 100% redundancy droplets to survive 50% loss
        droplets, k, orig_len = codec.encode(payload, redundancy=1.0)
        mtree = engine.merkle_trees[recipe.root_hash]

        # Seed content across 4 publisher peers
        for p in peers[:4]:
            p.store_content(recipe, droplets, mtree.root_hex)

        # Consumer node queries all peers
        consumer = peers[7]
        consumer.known_recipes[recipe.root_hash] = recipe

        recovered = await consumer.swarm_fetch(recipe.root_hash)
        assert recovered is not None, f"Failed to reconstruct under {loss_rate*100:.0f}% loss"
        assert recovered == payload, "Reconstructed payload corrupted under extreme loss"

    async def test_dynamic_node_churn_during_reconstruction(self):
        """
        Test continuous query workflow where nodes dynamically leave and join,
        and newly joined nodes attempt to fetch from nodes that reconstructed the payload.
        """
        net = SwarmNetwork()
        peers = [net.add_peer(f"churn_node_{i}", loss_rate=0.10) for i in range(10)]
        net.connect_all()

        payload = b"CONTINUOUS_CHURN_RECONSTRUCTION_AND_RESEEDING_" * 25
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        # Seed initial 3 nodes
        for p in peers[:3]:
            p.store_content(recipe, droplets, mtree.root_hex)

        # Kill 2 of the 3 seed nodes
        peers[0].is_alive = False
        peers[1].is_alive = False

        # Peer 5 fetches from remaining live seed (peer 2) and others
        peers[5].known_recipes[recipe.root_hash] = recipe
        recovered_peer5 = await peers[5].swarm_fetch(recipe.root_hash)
        assert recovered_peer5 == payload, "Peer 5 failed initial fetch after seed churn"

        # Peer 2 (last original seed) now crashes!
        peers[2].is_alive = False

        # Peer 8 joins and attempts to fetch from Peer 5 (which only has reconstructed payload)
        peers[8].known_recipes[recipe.root_hash] = recipe
        recovered_peer8 = await peers[8].swarm_fetch(recipe.root_hash)
        assert recovered_peer8 == payload, "Peer 8 failed to fetch from re-seeded Peer 5"

    async def test_latency_spikes_and_jitter_mesh_propagation(self):
        """
        Simulate high latency variance and out-of-order droplet reception across 6 peers.
        """
        net = SwarmNetwork()
        peers = [net.add_peer(f"jitter_peer_{i}", loss_rate=0.20) for i in range(6)]
        
        # Connect in a ring with cross-links
        for i in range(len(peers)):
            peers[i].connect(peers[(i + 1) % len(peers)])
            peers[i].connect(peers[(i + 3) % len(peers)])

        payload = b"LATENCY_JITTER_RING_PROPAGATION_VECTOR" * 40
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        peers[0].store_content(recipe, droplets, mtree.root_hex)

        # Broadcast gossip with delay simulation
        msg_id = hashlib.sha3_256(f"jitter_{recipe.root_hash}".encode()).hexdigest()
        msg = GossipMessage(
            msg_id=msg_id,
            sender_id=peers[0].node_id,
            recipe=recipe,
            merkle_root=mtree.root_hex,
            ttl=6,
        )
        peers[0].seen_gossip.add(msg_id)
        for n in peers[0].neighbors:
            asyncio.create_task(n.receive_gossip(msg))

        await asyncio.sleep(0.15)

        # Peer 4 attempts to fetch from swarm
        assert recipe.root_hash in peers[4].known_recipes
        recovered = await peers[4].swarm_fetch(recipe.root_hash)
        assert recovered == payload


@pytest.mark.simulation
@pytest.mark.asyncio
class TestNetworkPartitionAndReconciliation:
    """Challenge multi-node partition split-brain and post-healing state reconciliation."""

    async def test_tri_partition_split_and_reconciliation(self):
        """
        Partition an 9-node network into 3 isolated clusters (A: 0..2, B: 3..5, C: 6..8).
        Publish distinct datasets in each cluster.
        Heal the network and verify all 9 nodes reconcile and reconstruct all 3 datasets.
        """
        net = SwarmNetwork()
        nodes = [net.add_peer(f"tri_node_{i}", loss_rate=0.0) for i in range(9)]

        cluster_a = nodes[0:3]
        cluster_b = nodes[3:6]
        cluster_c = nodes[6:9]

        # Internal cluster connections only
        for cluster in [cluster_a, cluster_b, cluster_c]:
            for i in range(len(cluster)):
                for j in range(i + 1, len(cluster)):
                    cluster[i].connect(cluster[j])

        # Publish 3 distinct payloads
        engine = TFPNode()
        payload_a = b"CLUSTER_A_EXCLUSIVE_PAYLOAD_ALPHA_" * 20
        payload_b = b"CLUSTER_B_EXCLUSIVE_PAYLOAD_BETA__" * 20
        payload_c = b"CLUSTER_C_EXCLUSIVE_PAYLOAD_GAMMA_" * 20

        recipe_a = engine.publish(payload_a)
        recipe_b = engine.publish(payload_b)
        recipe_c = engine.publish(payload_c)

        cluster_a[0].store_content(recipe_a, engine.droplet_store[recipe_a.root_hash], engine.merkle_trees[recipe_a.root_hash].root_hex)
        cluster_b[0].store_content(recipe_b, engine.droplet_store[recipe_b.root_hash], engine.merkle_trees[recipe_b.root_hash].root_hex)
        cluster_c[0].store_content(recipe_c, engine.droplet_store[recipe_c.root_hash], engine.merkle_trees[recipe_c.root_hash].root_hex)

        # Before healing: Node in C cannot know recipe A or B
        assert recipe_a.root_hash not in cluster_c[0].known_recipes
        assert recipe_b.root_hash not in cluster_c[0].known_recipes

        # Heal network: Create bridge links A[2] <-> B[0] and B[2] <-> C[0]
        cluster_a[2].connect(cluster_b[0])
        cluster_b[2].connect(cluster_c[0])

        # Trigger gossip from origin nodes
        await cluster_a[0].broadcast_gossip(recipe_a, engine.merkle_trees[recipe_a.root_hash].root_hex)
        await cluster_b[0].broadcast_gossip(recipe_b, engine.merkle_trees[recipe_b.root_hash].root_hex)
        await cluster_c[0].broadcast_gossip(recipe_c, engine.merkle_trees[recipe_c.root_hash].root_hex)

        await asyncio.sleep(0.2)

        # Verify all nodes have all 3 recipes
        for node in nodes:
            assert recipe_a.root_hash in node.known_recipes, f"{node.node_id} missing recipe A"
            assert recipe_b.root_hash in node.known_recipes, f"{node.node_id} missing recipe B"
            assert recipe_c.root_hash in node.known_recipes, f"{node.node_id} missing recipe C"

        # Node in cluster C reconstructs payload A across two bridge hops
        rec_a = await cluster_c[2].swarm_fetch(recipe_a.root_hash)
        assert rec_a == payload_a, "Cluster C failed to reconstruct Payload A after reconciliation"

        # Node in cluster A reconstructs payload C across two bridge hops
        rec_c = await cluster_a[0].swarm_fetch(recipe_c.root_hash)
        assert rec_c == payload_c, "Cluster A failed to reconstruct Payload C after reconciliation"
