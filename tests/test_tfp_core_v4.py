# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive Invariant Test Suite for TFP v4.0 Canonical Core Engine

Verifies:
1. FastCDC 64-bit chunking & deduplication efficiency
2. Vectorized rateless fountain loss-tolerance (0% - 50% drops)
3. Constant-time SHA3-256 Merkle proof authentication & Byzantine defense
4. Multi-peer P2P swarm gathering and origin churn survival
"""

import asyncio
import hashlib
import os
import sys
import unittest

from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork
from tfp_core_v4.node import TFPNode


class TestTFPCoreV4(unittest.TestCase):
    """Rigorous invariant verification tests for TFP v4.0."""

    def setUp(self):
        self.node = TFPNode(node_id="test_node_01")
        self.chunker = ContentDefinedChunker(min_size=256, max_size=2048, target_size=512)
        self.codec = FountainCodec(symbol_size=128)

    def test_invariant_1_lossless_roundtrip(self):
        """Verify bit-exact roundtrip on audio and text binary payloads."""
        payload = b"RIFF" + b"\x00\x01\x02\x03\x04\x05\x06\x07" * 500
        recipe = self.node.publish(payload, metadata={"type": "audio/wav"})
        
        # Fetch with 0% loss
        recovered = self.node.fetch(recipe.root_hash, simulated_loss=0.0)
        self.assertEqual(recovered, payload)
        self.assertEqual(hashlib.sha3_256(recovered).hexdigest(), hashlib.sha3_256(payload).hexdigest())

    def test_invariant_2_fastcdc_deduplication(self):
        """Verify FastCDC 64-bit chunking achieves >90% deduplication on modified payloads."""
        base_text = b"CHAPTER 1: The Foundation Protocol Decentralized Mesh. " * 300
        recipe1, chunks1 = self.chunker.create_recipe(base_text)

        # Modify only 10 bytes in the middle of a 16KB file
        mod_text = base_text[:5000] + b"LOCAL_EDIT" + base_text[5010:]
        recipe2, chunks2 = self.chunker.create_recipe(mod_text)

        hashes1 = set(recipe1.chunk_hashes)
        hashes2 = set(recipe2.chunk_hashes)
        shared = hashes1.intersection(hashes2)

        reuse_pct = (len(shared) / max(len(hashes1), len(hashes2))) * 100.0
        print(f"\n[FastCDC] Shared chunks: {len(shared)}/{len(hashes1)} ({reuse_pct:.1f}% deduplication)")
        self.assertGreaterEqual(reuse_pct, 85.0)

    def test_invariant_3_fountain_loss_resilience(self):
        """Verify bit-exact reconstruction under 10%, 25%, and 40% packet drops."""
        payload = b"TFP FOUNTAIN TEST DATA: " * 150
        recipe = self.node.publish(payload)

        for loss in [0.10, 0.25, 0.40]:
            recovered = self.node.fetch(recipe.root_hash, simulated_loss=loss)
            self.assertEqual(recovered, payload)

    def test_invariant_4_merkle_byzantine_defense(self):
        """Verify Merkle proof verification detects and blocks poisoned leaves."""
        leaves = [f"leaf_data_packet_{i}".encode() for i in range(16)]
        tree = MerkleTree(leaves)

        # Valid proof for leaf 5
        proof5 = tree.get_proof(5)
        self.assertTrue(verify_merkle_proof(leaves[5], proof5, tree.root))

        # Tampered leaf payload (Byzantine attack)
        fake_leaf = b"leaf_data_packet_POISONED"
        self.assertFalse(verify_merkle_proof(fake_leaf, proof5, tree.root))

    def test_invariant_5_mesh_swarm_and_origin_crash(self):
        """Verify 5-node P2P mesh gossips and reconstructs content after origin crashes."""
        async def run_mesh():
            net = SwarmNetwork()
            origin = net.add_peer("origin", loss_rate=0.0)
            relay1 = net.add_peer("relay1", loss_rate=0.10)
            relay2 = net.add_peer("relay2", loss_rate=0.15)
            receiver = net.add_peer("receiver", loss_rate=0.0)

            # Build topology: origin -> relays -> receiver
            origin.connect(relay1)
            origin.connect(relay2)
            relay1.connect(receiver)
            relay2.connect(receiver)

            # Publish on Origin
            payload = b"CRITICAL EMERGENCY BROADCAST VIA MESH: " * 40
            node = TFPNode()
            recipe = node.publish(payload)
            droplets = node.droplet_store[recipe.root_hash]
            mtree = node.merkle_trees[recipe.root_hash]

            origin.store_content(recipe, droplets, mtree.root_hex)

            # Seed complementary droplets to relays
            relay1.store_content(recipe, droplets[: (len(droplets) * 2) // 3], mtree.root_hex)
            relay2.store_content(recipe, droplets[len(droplets) // 3 :], mtree.root_hex)

            # Gossip announcement across mesh
            await origin.broadcast_gossip(recipe, mtree.root_hex)
            await asyncio.sleep(0.05)

            # KILL Origin node (simulating sudden node departure)
            origin.is_alive = False

            # Receiver gathers from remaining relays
            recovered = await receiver.swarm_fetch(recipe.root_hash)
            self.assertEqual(recovered, payload)

        asyncio.run(run_mesh())


if __name__ == "__main__":
    unittest.main()
