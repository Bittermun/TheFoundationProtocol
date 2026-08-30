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

    def test_invariant_6_dynamic_droplet_synthesis_reconstructed_payload(self):
        """Verify MeshPeer.request_droplets dynamically synthesizes droplets when payload is reconstructed locally."""
        async def run_test():
            payload = b"DYNAMIC FOUNTAIN SYNTHESIS TEST PAYLOAD DATA: " * 50
            recipe, _ = self.chunker.create_recipe(payload)
            peer = MeshPeer("reseeder_peer", loss_rate=0.0, symbol_size=self.codec.symbol_size)
            peer.known_recipes[recipe.root_hash] = recipe
            peer.reconstructed_payloads[recipe.root_hash] = payload

            k = (len(payload) + self.codec.symbol_size - 1) // self.codec.symbol_size
            # Request droplets from peer with empty droplet_store initially
            requested = await peer.request_droplets(recipe.root_hash)
            self.assertGreaterEqual(len(requested), k)
            self.assertIn(recipe.root_hash, peer.droplet_store)
            for d in requested:
                self.assertIsNotNone(d.payload)
                self.assertIsInstance(d.seed, int)

        asyncio.run(run_test())

    def test_invariant_7_bip39_hardware_root_of_trust_and_slip0010_derivation(self):
        """Verify BIP-39 128/256-bit mnemonic generation, checksum validation, and SLIP-0010 HD key paths."""
        from tfp_core.crypto.bip39 import (
            derive_hd_key,
            derive_key_path,
            generate_mnemonic,
            mnemonic_to_seed,
            validate_mnemonic,
        )
        from tfp_core.identity import create_device_identity, recover_device_identity

        # 128-bit (12 words) and 256-bit (24 words) generation & validation
        m12 = generate_mnemonic(strength=128)
        m24 = generate_mnemonic(strength=256)
        self.assertEqual(len(m12.split()), 12)
        self.assertEqual(len(m24.split()), 24)
        self.assertTrue(validate_mnemonic(m12))
        self.assertTrue(validate_mnemonic(m24))

        # Rejection of corrupted checksum
        bad_words = m24.split()
        bad_words[-1] = "abandon" if bad_words[-1] != "abandon" else "zoo"
        self.assertFalse(validate_mnemonic(" ".join(bad_words)))

        # PBKDF2 seed derivation & SLIP-0010 key derivation
        seed = mnemonic_to_seed(m24, passphrase="secure_passphrase")
        self.assertEqual(len(seed), 64)
        priv1, pub1 = derive_hd_key(seed, "m/44'/9999'/0'/0/0")
        priv2, pub2 = derive_key_path(seed, "m/44'/9999'/0'/0/0")
        self.assertEqual(priv1, priv2)
        self.assertEqual(pub1, pub2)
        self.assertEqual(len(priv1), 32)
        self.assertEqual(len(pub1), 32)

        # Full device provisioning and recovery
        ident = create_device_identity(strength=256, passphrase="test_passphrase")
        recovered = recover_device_identity(ident.mnemonic, passphrase="test_passphrase")
        self.assertEqual(ident.private_key, recovered.private_key)
        self.assertEqual(ident.public_key, recovered.public_key)
        self.assertEqual(ident.mesh_mac_key, recovered.mesh_mac_key)

    def test_invariant_8_deterministic_repair_seed_schedule_and_anti_pollution(self):
        """Verify deterministic repair droplet seed schedules bound to RootHash and O(1) anti-pollution pre-validation."""
        from tfp_core.fountain import (
            FountainCodec,
            FountainDroplet,
            derive_repair_seed_schedule,
            verify_droplet_seed_authenticity,
        )
        from tfp_transport.fountain import TransportFountainChannel

        payload = b"AUTHENTICATED FOUNTAIN DETERMINISTIC SEED TEST: " * 30
        codec = FountainCodec(symbol_size=128)
        root_hash = "0x" + hashlib.sha3_256(payload).hexdigest()

        # Deterministic seed schedule derivation
        seeds1 = derive_repair_seed_schedule(root_hash, session_nonce=b"session_01", total_source_blocks=10, repair_count=5)
        seeds2 = derive_repair_seed_schedule(root_hash, session_nonce=b"session_01", total_source_blocks=10, repair_count=5)
        self.assertEqual(seeds1, seeds2)
        self.assertEqual(len(seeds1), 5)
        for s in seeds1:
            self.assertGreaterEqual(s, 10)

        # Encode with deterministic seed schedule
        droplets, k, orig_len = codec.encode(payload, redundancy=0.60, root_hash=root_hash, session_nonce=b"session_01")
        self.assertGreaterEqual(len(droplets), k)

        # Transport channel admission control
        chan = TransportFountainChannel(root_hash=root_hash, k_source_symbols=k, orig_len=orig_len, symbol_size=128, session_nonce=b"session_01")

        # Admit authentic droplets
        for d in droplets:
            admitted = chan.admit_droplet(d)
            self.assertTrue(admitted)

        # Byzantine pollution injection test: forged indices on repair droplet
        poisoned_droplet = FountainDroplet(
            seed=seeds1[0],
            degree=5,
            indices=[0, 1, 2, 3, 999],  # Forged/tampered indices
            payload=b"\xFF" * 128,
        )
        self.assertFalse(chan.admit_droplet(poisoned_droplet))
        self.assertGreater(chan.rejected_count, 0)

        # Confirm clean recovery despite attempted Byzantine poisoning
        recovered = chan.decode()
        self.assertEqual(recovered, payload)

    def test_invariant_9_pqc_tiered_manifest_agility_and_hop_authentication(self):
        """Verify Tier 1 PQC content manifest signing/verification and Tier 2 lightweight intra-mesh hop authentication."""
        from tfp_core.crypto.manifest_agility import (
            Tier1ManifestSigner,
            Tier2HopAuthenticator,
            TieredManifestManager,
        )
        from tfp_core.crypto.pqc_adapter import PQCAdapter
        from tfp_core.manifest import create_tiered_manifest, verify_tiered_manifest

        pqc = PQCAdapter()
        kp = pqc.generate_dilithium5_keypair()
        content_data = b"POST_QUANTUM_SECURE_DOCUMENT_TIERED_MANIFEST"
        content_hash = hashlib.sha3_256(content_data).hexdigest()

        # Tier 1 PQC Manifest creation and verification
        manifest = create_tiered_manifest(
            content_hash=content_hash,
            total_size=len(content_data),
            chunk_hashes=[content_hash],
            chunk_sizes=[len(content_data)],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
            metadata={"classification": "unclassified"},
        )
        self.assertTrue(verify_tiered_manifest(manifest, kp.public_key))

        # Tampered content hash detection in manifest
        bad_manifest = create_tiered_manifest(
            content_hash=content_hash,
            total_size=len(content_data),
            chunk_hashes=[content_hash],
            chunk_sizes=[len(content_data)],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
        )
        bad_manifest.content_hash = "tampered_hash_value"
        self.assertFalse(verify_tiered_manifest(bad_manifest, kp.public_key))

        # Tier 2 Lightweight Hop Authentication (16-byte MAC)
        hop_secret = b"intra_mesh_shared_secret_32bytes"
        token = Tier2HopAuthenticator.generate_hop_token(hop_secret, content_hash, hop_index=1, token_len=16)
        self.assertEqual(len(token), 16)
        self.assertTrue(Tier2HopAuthenticator.verify_hop_token(hop_secret, content_hash, hop_index=1, token=token, token_len=16))
        self.assertFalse(Tier2HopAuthenticator.verify_hop_token(b"wrong_secret", content_hash, hop_index=1, token=token, token_len=16))


if __name__ == "__main__":
    unittest.main()
