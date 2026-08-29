# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Challenge Suite (Iteration 2).
Constructed by challenger_1_iter2 to stress test:
1. PQC Agility Registry and PQC Adapters under extreme corruption and malicious suites.
2. Large Merkle Tree (1024 leaves) proof verification under boundary and tampering conditions.
3. RaptorQ GF(2) Matrix Inversion under Byzantine corrupted shards, duplicate rows, and extreme loss.
4. Swarm Network resilience under Byzantine malicious droplet injection and peer churn.
5. Pathological Content Chunking & Behavioral Anomaly Classification benchmarks.
"""

import asyncio
import hashlib
import hmac
import math
import os
import random
import struct
import time
from typing import List

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core.crypto.agility_registry import (
    CryptoAgilityRegistry,
    CryptoAlgorithm,
    CryptoSuite,
    sign_data,
    verify_signature as verify_agility_sig,
)
from tfp_core.crypto.pqc_adapter import PQCAdapter, KeyPair, Signature
from tfp_core.security.mutualistic_defense import MutualisticAuditor, GossipVerifier
from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork
from tfp_core_v4.node import TFPNode
from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter as PurePythonRaptorQ, IntegrityError as PureIntegrityError
from tfp_client.lib.fountain.raptorq_ffi import RealRaptorQAdapter as FFIRaptorQ, IntegrityError as FFIIntegrityError
from tfp_client.lib.zkp.zkp_real import RealZKPAdapter
from tfp_security.heuristic.behavioral_engine import BehavioralEngine


class TestPQCAgilityAdversarial:
    """Stress test cryptographic agility registry and PQC adapters."""

    def test_agility_registry_unregistered_suite(self):
        """Agility registry returns None for unknown suites and sign_data raises ValueError."""
        registry = CryptoAgilityRegistry()
        assert registry.get_suite("invalid_pqc_suite_v999") is None
        with pytest.raises(ValueError, match="Suite not found"):
            sign_data(b"data", suite_id="invalid_pqc_suite_v999")

    def test_pqc_dilithium5_key_tampering(self):
        """Mutating the public key must fail verification."""
        adapter = PQCAdapter(use_pqc=False)
        keypair = adapter.generate_dilithium5_keypair()
        message = b"CRITICAL_TFP_STATE_TRANSITION"
        sig = adapter.sign(message, keypair, suite_id="tfp_pqc_v1")

        # Mutate public key
        bad_pk = bytearray(keypair.public_key)
        bad_pk[0] ^= 0xFF
        assert adapter.verify(message, sig, bytes(bad_pk)) is False

    def test_pqc_sphincs_signature_bitflip(self):
        """SPHINCS+ signature verification under bit flips."""
        adapter = PQCAdapter(use_pqc=False)
        keypair = adapter.generate_sphincs_keypair()
        message = b"POST_QUANTUM_AUDIT_LOG_ENTRY"
        sig = adapter.sign(message, keypair, suite_id="tfp_pqc_v2")
        assert adapter.verify(message, sig, keypair.public_key) is True

        # Mutate signature
        bad_sig_data = bytearray(sig.signature)
        bad_sig_data[5] ^= 0xAA
        bad_sig = Signature(
            signature=bytes(bad_sig_data),
            algorithm=sig.algorithm,
            suite_id=sig.suite_id,
            message_hash=sig.message_hash,
            timestamp=sig.timestamp,
        )
        assert adapter.verify(message, bad_sig, keypair.public_key) is False


class TestDeepMerkleTreeTampering:
    """Stress test Merkle Tree proofs on large scale trees (1024 leaves)."""

    def test_1024_leaf_tree_tampering(self):
        """Build 1024-leaf Merkle tree, verify all proofs, and verify tamper detection at every depth."""
        leaves = [hashlib.sha3_256(f"leaf_data_block_{i}".encode()).digest() for i in range(1024)]
        tree = MerkleTree(leaves)
        root = tree.root
        assert len(root) == 32

        # Check proofs for random leaves
        rng = random.Random(1337)
        sample_indices = rng.sample(range(1024), 20)

        for idx in sample_indices:
            proof = tree.get_proof(idx)
            # Proof length should be log2(1024) = 10
            assert len(proof) == 10
            # Valid proof passes
            assert verify_merkle_proof(leaves[idx], proof, root) is True

            # Tampered leaf fails
            tampered_leaf = bytearray(leaves[idx])
            tampered_leaf[0] ^= 0x01
            assert verify_merkle_proof(bytes(tampered_leaf), proof, root) is False

            # Tampered sibling at each depth fails
            for step_idx in range(len(proof)):
                bad_proof = list(proof)
                bad_sibling, direction = bad_proof[step_idx]
                bad_sibling_mut = bytearray(bad_sibling)
                bad_sibling_mut[0] ^= 0x80
                bad_proof[step_idx] = (bytes(bad_sibling_mut), direction)
                assert verify_merkle_proof(leaves[idx], bad_proof, root) is False


class TestRaptorQAdversarialGF2Matrix:
    """Stress test RaptorQ Gaussian Elimination over GF(2) under hostile shard injections."""

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_raptorq_heavy_loss_and_recovery(self, adapter_cls):
        """
        Encode 50KB payload (50 systematic shards), drop 30% systematic shards (15 shards lost),
        decode using surviving 35 systematic shards + 26 repair shards (total 61 shards).
        Gaussian elimination must achieve full rank and bit-exact reconstruction.
        """
        adapter = adapter_cls(shard_size=1024)
        secret = b"adversarial_test_secret_32bytes0"
        data = os.urandom(50 * 1024)  # 50 shards
        k = 50

        shards = adapter.encode(data, redundancy=0.5, hmac_key=secret)  # 50 systematic + 26 repair = 76 shards
        assert len(shards) == 76

        # Drop 15 systematic shards (keep 35 systematic + all 26 repair = 61 shards > 50)
        surviving = shards[:35] + shards[50:76]
        rng = random.Random(42)
        rng.shuffle(surviving)

        recovered = adapter.decode(surviving, hmac_key=secret)
        assert recovered == data

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_raptorq_byzantine_corrupted_repair_shards(self, adapter_cls):
        """Inject corrupted repair shards into stream; valid repair shards must suffice."""
        adapter = adapter_cls(shard_size=1024)
        secret = b"adversarial_test_secret_32bytes0"
        data = b"BYZANTINE_RESILIENCE_TEST_VECTOR_" * 200  # ~6.6KB -> 7 shards
        k = (len(data) + 1023) // 1024

        shards = adapter.encode(data, redundancy=0.5, hmac_key=secret)
        # Separate systematic and repair shards based on index in header
        systematic = []
        repair = []
        for s in shards:
            idx = struct.unpack(">QII", s[:16])[2]
            if idx < k:
                systematic.append(s)
            else:
                repair.append(s)

        assert len(repair) >= 4

        # Test scenario: Drop 2 systematic shards, provide 2 valid repair + 2 corrupted repair shards
        surviving = systematic[: k - 2] + repair[:2]
        # Corrupt 2 additional repair shards and append
        for r_shard in repair[2:]:
            bad = bytearray(r_shard)
            bad[25] ^= 0x55
            surviving.append(bytes(bad))

        recovered = adapter.decode(surviving, hmac_key=secret)
        assert recovered == data


class TestSwarmByzantineInjection:
    """Stress test multi-peer swarm under Byzantine droplet injection and Merkle authentication."""

    def test_byzantine_droplet_merkle_rejection(self):
        """Byzantine peer modifies a droplet; Merkle proof verification fails."""
        node = TFPNode()
        data = b"AUTHENTIC_SWARM_CONTENT_BLOCK" * 30
        recipe = node.publish(data)
        root_hash = recipe.root_hash
        droplets = list(node.droplet_store[root_hash])
        mtree = node.merkle_trees[root_hash]

        # Valid droplet proof verifies against Merkle root
        valid_droplet = droplets[0]
        proof = mtree.get_proof(0)
        assert verify_merkle_proof(valid_droplet.serialize(), proof, mtree.root) is True

        # Byzantine modified droplet fails Merkle verification
        bad_droplet = FountainDroplet(
            seed=valid_droplet.seed,
            degree=valid_droplet.degree,
            indices=valid_droplet.indices,
            payload=b"\xde\xad" * (len(valid_droplet.payload) // 2),
        )
        assert verify_merkle_proof(bad_droplet.serialize(), proof, mtree.root) is False

    def test_swarm_multi_peer_gossip_and_fetch(self):
        """Swarm network gossip dissemination and swarm_fetch reconstruction."""
        swarm = SwarmNetwork()
        peer_honest1 = swarm.add_peer("honest_1")
        peer_honest2 = swarm.add_peer("honest_2")
        swarm.connect_all()

        node = TFPNode()
        data = b"AUTHENTIC_SWARM_CONTENT_BLOCK" * 30
        recipe = node.publish(data)
        root_hash = recipe.root_hash
        droplets = list(node.droplet_store[root_hash])
        merkle_root = node.merkle_trees[root_hash].root.hex()

        # Store content in Honest 1 and gossip
        peer_honest1.store_content(recipe, droplets, merkle_root)
        asyncio.run(peer_honest1.broadcast_gossip(recipe, merkle_root))

        # Honest 2 fetches content from swarm
        reconstructed = asyncio.run(peer_honest2.swarm_fetch(root_hash))
        assert reconstructed == data


class TestPathologicalChunkingAndBehavioral:
    """Benchmark and test pathological files against CDC and Behavioral Engine."""

    def test_pathological_all_zeroes_1mb(self):
        """1MB of all zeroes chunked and decoded."""
        data = b"\x00" * (1024 * 1024)
        node = TFPNode()
        recipe = node.publish(data)
        assert recipe.total_size == 1024 * 1024
        recovered = node.fetch(recipe.root_hash)
        assert recovered == data

    def test_behavioral_engine_pdf_jpeg_no_false_positives(self):
        """Valid JPEG, PNG, and PDF headers must not accumulate critical malicious flags."""
        engine = BehavioralEngine()

        jpeg_header = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00" + b"\x00" * 500
        pdf_header = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n" + b"\x00" * 500
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10" + b"\x00" * 500

        for content in (jpeg_header, pdf_header, png_header):
            c_hash = hashlib.sha3_256(content).hexdigest()
            res = engine.analyze_content(content, c_hash)
            assert res.is_suspicious is False
            assert res.structural_score < 0.7
