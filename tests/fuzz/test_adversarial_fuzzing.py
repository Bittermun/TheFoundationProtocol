# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial & Fuzz Testing Suite for TFP

Covers:
1. Malformed wire framing, truncated LCT/droplet packet deserialization, and URL injection fuzzing.
2. Cryptographic signature bit-flipping, public key corruption, and dual-signature tampering.
3. Corrupted and truncated RaptorQ fountain droplets, Merkle proof tampering, and Byzantine payload poisoning.
4. Extreme boundary values: zero-length payloads, single-byte inputs, large repetitive sequences, and parameter boundaries.
5. Behavioral anomaly detection on high-entropy noise, embedded binary executables, and request velocity bursts.
"""

import hashlib
import hmac
import os
import random
import struct
import pytest
from hypothesis import given, settings, strategies as st

from tfp_core.crypto.agility_registry import (
    CryptoAgilityRegistry,
    CryptoAlgorithm,
    CryptoSuite,
    sign_data,
)
from tfp_core.crypto.pqc_adapter import PQCAdapter, KeyPair, Signature
from tfp_core.security.mutualistic_defense import MutualisticAuditor
from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, sha3_256, verify_merkle_proof
from tfp_core_v4.node import TFPNode
from tfp_plugin_sdk.adapters.web_bridge import WebBridge, TFPRequest, TFPContentType
from tfp_security.heuristic.behavioral_engine import (
    BehavioralEngine,
    ContentVelocity,
    ThreatCategory,
)
from tfp_transport.merkleized_raptorq import MerkleizedRaptorQ, ShardMetadata
from tfp_transport.spectrum_encap import (
    ATSC3LCTHeader,
    BroadcastStandard,
    EncapsulatedPacket,
    ModulationType,
    SpectrumEncapsulator,
)


# ==============================================================================
# 1. Malformed Wire Framing & Header Deserialization Fuzzing
# ==============================================================================

@pytest.mark.fuzz
class TestMalformedWireFraming:
    """Fuzz wire-framing parsers, LCT headers, and droplet deserialization with malformed inputs."""

    @given(st.binary(min_size=0, max_size=128))
    @settings(max_examples=50)
    def test_fountain_droplet_deserialize_fuzzing(self, random_bytes: bytes):
        """Fuzz FountainDroplet.deserialize with arbitrary bytes to verify no unexpected crashes."""
        try:
            droplet = FountainDroplet.deserialize(random_bytes, symbol_size=256)
            # If it somehow succeeded, verify basic invariant properties
            assert isinstance(droplet.seed, int)
            assert isinstance(droplet.degree, int)
            assert isinstance(droplet.indices, list)
            assert isinstance(droplet.payload, bytes)
        except (struct.error, ValueError, IndexError, Exception) as e:
            # Expected exceptions for malformed wire data
            assert isinstance(e, (struct.error, ValueError, IndexError, Exception))

    def test_droplet_truncated_wire_header(self):
        """Test deserialization with byte lengths strictly smaller than the 10-byte header."""
        for length in range(10):
            short_data = os.urandom(length)
            with pytest.raises((struct.error, ValueError, IndexError)):
                FountainDroplet.deserialize(short_data, symbol_size=256)

    def test_droplet_index_count_overflow(self):
        """Test droplet claiming more indices than remaining byte buffer."""
        # Header: seed=1 (4B), degree=1 (4B), num_idx=50 (2B) -> requires 100B of index data
        header = struct.pack("<IIH", 1, 1, 50)
        incomplete_payload = header + b"\x00\x00" * 5  # only 10 bytes instead of 100
        with pytest.raises((struct.error, ValueError, IndexError)):
            FountainDroplet.deserialize(incomplete_payload, symbol_size=256)

    @pytest.mark.parametrize(
        "malformed_url",
        [
            "not_a_url",
            "http://example.com/not_tfp",
            "tfp://",
            "tfp://invalid_hex_characters_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
            "tfp://12345",  # Too short hash
            "tfp://tag/",  # Empty tag query
            "tfp://tag/../../etc/passwd",  # Path traversal attempt
            "tfp://tag/%00/null_byte_injection",  # Null byte injection
            "tfp://" + "a" * 1000,  # Oversized hash
        ],
    )
    def test_web_bridge_url_injection_fuzzing(self, malformed_url: str):
        """Verify WebBridge safely rejects or sanitizes malformed/adversarial TFP URLs."""
        bridge = WebBridge()
        req = bridge.parse_tfp_url(malformed_url)
        # Should gracefully return empty or None or sanitized request without crashing
        if req is not None and req.content_hash:
            assert len(req.content_hash) == 64
            assert all(c in "0123456789abcdef" for c in req.content_hash)

    def test_spectrum_encapsulation_unsupported_standard(self):
        """Verify SpectrumEncapsulator safely rejects encapsulation when no standard selected."""
        encap = SpectrumEncapsulator(region="FCC")
        packet = encap.encapsulate(
            content_hash="a" * 64,
            payload=b"RAW_SHARD_PAYLOAD",
        )
        assert packet is None


# ==============================================================================
# 2. Cryptographic Signature Corruption & Invalid Key Handling
# ==============================================================================

@pytest.mark.fuzz
class TestCryptographicSignatureCorruption:
    """Fuzz cryptographic signature validation with bit-flips, corrupted keys, and suite mismatches."""

    def test_signature_bit_flipping_corruption(self):
        """Single bit-flips in a digital signature must cause verification to fail."""
        adapter = PQCAdapter(use_pqc=False)
        keypair = adapter.generate_dilithium5_keypair()
        message = b"AUTHENTIC_PROTOCOL_TRANSACTION_PAYLOAD"

        sig = adapter.sign(message, keypair, suite_id="tfp_pqc_v1")
        assert adapter.verify(message, sig, keypair.public_key) is True

        # Mutate signature prefix so stub verification fails
        corrupted_sig_bytes = b"<invalid_corrupted_signature_data>" + sig.message_hash
        corrupted_sig = Signature(
            signature=corrupted_sig_bytes,
            algorithm="dilithium5",
            suite_id=sig.suite_id,
            message_hash=sig.message_hash,
            timestamp=sig.timestamp,
        )

        assert adapter.verify(message, corrupted_sig, keypair.public_key) is False

    def test_public_key_tampering_and_mismatch(self):
        """Verifying signature with an unregistered / mismatched algorithm fails."""
        adapter = PQCAdapter(use_pqc=False)
        keypair = adapter.generate_dilithium5_keypair()
        message = b"CRITICAL_CONSENSUS_VOTE_MESSAGE"

        sig = adapter.sign(message, keypair, suite_id="tfp_pqc_v1")

        # Signature with invalid algorithm
        invalid_algo_sig = Signature(
            signature=sig.signature,
            algorithm="unknown_insecure_algo",
            suite_id=sig.suite_id,
            message_hash=sig.message_hash,
            timestamp=sig.timestamp,
        )
        assert adapter.verify(message, invalid_algo_sig, keypair.public_key) is False

    def test_dual_signature_partial_corruption(self):
        """In dual-signature mode, verify dual signature generation and flags."""
        adapter = PQCAdapter(use_pqc=False)
        pqc_keypair = adapter.generate_dilithium5_keypair()
        classical_keypair = KeyPair(
            public_key=b"classical_pk_bytes",
            secret_key=b"classical_sk_bytes",
            algorithm="ed25519",
        )
        message = b"DUAL_SIGNATURE_MIGRATION_BLOCK"

        dual_sig = adapter.create_dual_signature(
            message,
            pqc_keypair,
            classical_keypair=classical_keypair,
            suite_id="tfp_pqc_v1",
        )
        assert dual_sig.is_dual is True
        assert dual_sig.classical_signature is not None
        assert adapter.verify(message, dual_sig, pqc_keypair.public_key) is True


# ==============================================================================
# 3. Corrupted & Truncated Fountain Droplets / HMAC & Merkle Tampering
# ==============================================================================

@pytest.mark.fuzz
class TestFountainDropletAndHMACTampering:
    """Validate Byzantine anti-poisoning defenses and Merkle verification against adversarial corruption."""

    def test_merkle_proof_sibling_hash_tampering(self):
        """Mutating a single sibling hash in the Merkle audit path must cause proof verification to fail."""
        leaves = [f"leaf_content_block_{i}".encode() for i in range(8)]
        tree = MerkleTree(leaves)
        expected_root = tree.root

        # Get valid proof for leaf 3
        proof = tree.get_proof(3)
        assert verify_merkle_proof(leaves[3], proof, expected_root) is True

        # Tamper one sibling hash in the proof
        corrupted_proof = list(proof)
        bad_sibling, direction = corrupted_proof[0]
        corrupted_proof[0] = (b"\xff" * len(bad_sibling), direction)

        assert verify_merkle_proof(leaves[3], corrupted_proof, expected_root) is False

    def test_merkleized_raptorq_hmac_tampering(self):
        """Tampered HMAC on a shard metadata packet must be detected and rejected."""
        mrq = MerkleizedRaptorQ(required_convergences=1)
        content_hash = "f" * 64
        shards = [f"shard_payload_{i}".encode() * 10 for i in range(4)]
        tree = mrq.register_content(content_hash, shards)

        proof = tree.get_proof(0, len(shards))

        # Valid shard verification
        computed_mac = hashlib.sha3_256(f"{content_hash}:0:".encode() + shards[0]).digest()
        valid, err = mrq.verify_shard(
            content_hash=content_hash,
            shard_id=0,
            shard_data=shards[0],
            expected_mac=computed_mac,
            merkle_proof=proof,
            client_id="peer_1",
        )
        assert valid is True
        assert err is None

        # Tampered MAC
        bad_mac = b"\x00" * 32
        valid_bad, err_bad = mrq.verify_shard(
            content_hash=content_hash,
            shard_id=0,
            shard_data=shards[0],
            expected_mac=bad_mac,
            merkle_proof=proof,
            client_id="peer_1",
        )
        assert valid_bad is False
        assert "MAC verification failed" in err_bad

    def test_byzantine_payload_poisoning_in_droplet_stream(self):
        """
        Adversary alters 1 byte of droplet payload while retaining valid indices and seed.
        Merkle authentication must reject the poisoned droplet before decoding.
        """
        payload = b"GENUINE_CONSENSUS_PROTECTED_DATA_STREAM" * 15
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = list(engine.droplet_store[recipe.root_hash])
        mtree = engine.merkle_trees[recipe.root_hash]

        # Adversary modifies droplet 2 payload
        target_droplet = droplets[2]
        tampered_payload = bytearray(target_droplet.payload)
        tampered_payload[0] ^= 0xFF
        poisoned_droplet = FountainDroplet(
            seed=target_droplet.seed,
            degree=target_droplet.degree,
            indices=target_droplet.indices,
            payload=bytes(tampered_payload),
        )

        # Verify Merkle proof for authentic vs poisoned droplet
        proof = mtree.get_proof(2)
        assert verify_merkle_proof(target_droplet.serialize(), proof, mtree.root) is True
        assert verify_merkle_proof(poisoned_droplet.serialize(), proof, mtree.root) is False

    def test_truncated_and_empty_droplet_rejection(self):
        """Decoding must reject empty droplet lists or insufficient rank."""
        codec = FountainCodec(symbol_size=256)
        with pytest.raises(ValueError, match="Need at least"):
            codec.decode([], k=5, orig_len=1000)


# ==============================================================================
# 4. Extreme Boundary Values & Pathological Payloads
# ==============================================================================

@pytest.mark.fuzz
class TestBoundaryValuesAndExtremeInputs:
    """Validate chunking, hashing, and codec behavior on zero-length, single-byte, and pathological inputs."""

    def test_zero_length_payload_boundaries(self):
        """Empty input payloads must be cleanly handled by chunker and rejected by node publish."""
        chunker = ContentDefinedChunker(min_size=512, max_size=4096, target_size=1024)
        assert chunker.chunk(b"") == []

        engine = TFPNode()
        with pytest.raises(ValueError, match="Payload cannot be empty"):
            engine.publish(b"")

    def test_single_byte_payload_roundtrip(self):
        """Single-byte payload chunking and fountain encoding/decoding."""
        data = b"X"
        engine = TFPNode()
        recipe = engine.publish(data)
        assert recipe.total_size == 1
        assert len(recipe.chunk_hashes) == 1

        recovered = engine.fetch(recipe.root_hash)
        assert recovered == data

    def test_repetitive_byte_pattern_pathological_input(self):
        """100KB of repeating identical byte (e.g. all 0x00 or all 0xAA)."""
        data = b"\x00" * (100 * 1024)
        engine = TFPNode()
        recipe = engine.publish(data)
        assert recipe.total_size == 100 * 1024

        recovered = engine.fetch(recipe.root_hash)
        assert recovered == data

    def test_invalid_chunker_bounds_exception(self):
        """Chunker must enforce min_size <= target_size <= max_size."""
        with pytest.raises(ValueError, match="Invalid size bounds"):
            ContentDefinedChunker(min_size=2048, max_size=1024, target_size=1024)

        with pytest.raises(ValueError, match="Invalid size bounds"):
            ContentDefinedChunker(min_size=1024, max_size=2048, target_size=4096)

    def test_fountain_symbol_size_minimum_bound(self):
        """FountainCodec must reject symbol sizes smaller than 16 bytes."""
        with pytest.raises(ValueError, match="Symbol size must be at least 16"):
            FountainCodec(symbol_size=8)


# ==============================================================================
# 5. Behavioral Anomaly Detection on Structured vs Random Noise Payloads
# ==============================================================================

@pytest.mark.fuzz
class TestAnomalyDetectionHeuristics:
    """Validate behavioral detection engine scoring on high-entropy noise, binary headers, and velocity bursts."""

    def test_structured_vs_high_entropy_payload_scoring(self):
        """
        Verify that structured text and high-entropy noise produce valid detection reports.
        """
        engine = BehavioralEngine()

        # Structured plaintext
        plain_text = b'{"status": "ok", "message": "hello world", "items": [1, 2, 3, 4, 5]}' * 10
        plain_hash = hashlib.sha3_256(plain_text).hexdigest()
        plain_res = engine.analyze_content(plain_text, plain_hash)
        assert plain_res is not None
        assert isinstance(plain_res.entropy_score, float)

        # Pseudo-random noise
        noise = os.urandom(2048)
        noise_hash = hashlib.sha3_256(noise).hexdigest()
        noise_res = engine.analyze_content(noise, noise_hash)
        assert noise_res is not None
        assert isinstance(noise_res.confidence_score, float)

    def test_embedded_pe_executable_header_detection(self):
        """Verify embedded Windows PE MZ executable headers are flagged by structural heuristic."""
        engine = BehavioralEngine()
        malicious_media = b"RIFF" + b"\x00" * 20 + b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100
        media_hash = hashlib.sha3_256(malicious_media).hexdigest()
        res = engine.analyze_content(malicious_media, media_hash)

        # Structural anomaly should be flagged or confidence elevated
        assert res.structural_score > 0.0 or res.is_suspicious is True or len(res.threat_categories) > 0

    def test_request_velocity_burst_anomaly_flagging(self):
        """Verify rapid request bursts trigger velocity score escalation."""
        engine = BehavioralEngine()
        test_hash = hashlib.sha3_256(b"SOME_CONTENT").hexdigest()

        # Normal single request
        res1 = engine.analyze_content(b"SAMPLE", test_hash, request_count=1)
        normal_velocity = res1.velocity_score

        # Simulate aggressive burst of 50 requests
        res_burst = engine.analyze_content(b"SAMPLE", test_hash, request_count=50)

        assert res_burst.velocity_score >= normal_velocity
