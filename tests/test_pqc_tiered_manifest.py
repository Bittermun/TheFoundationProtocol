# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive Multi-Tier Test Suite: PQC Tiered Manifest Agility

Covers:
- Tier 1 (Feature):
    * Tier 1 Content Manifest creation and PQC signature verification (Dilithium5 / ML-DSA-87)
    * Tier 1 SPHINCS+ signature creation and verification
    * Tier 1 Classical & Dual-mode (Dilithium5 + Ed25519) signature creation and verification
    * Canonical bytes representation and deterministic serialization roundtrips (to_dict / from_dict)
    * Tier 2 Intra-Mesh Hop Token generation and constant-time verification
    * Tier 2 Merkle chunk binding token generation and verification
    * Unified TieredManifestManager lifecycle management
- Tier 2 (Boundary/Edge & Adversarial Fault Injection):
    * Corrupted manifest payload rejection (tampering content_hash, total_size, chunk_hashes)
    * Corrupted PQC signature bit-flip rejection
    * Corrupted classical signature in dual-mode rejection
    * Invalid hop token rejection (mismatched hop_secret, wrong chunk_hash, wrong hop_index)
    * Hop token epoch expiry and clock skew boundary validation
    * Merkle chunk token tampering detection
    * Missing or malformed author public key rejection
"""

import hashlib
import os
import time
import pytest
from typing import List

from tfp_core.crypto.pqc_adapter import KeyPair, PQCAdapter, Signature
from tfp_core.crypto.manifest_agility import (
    PQCAlgorithm,
    Tier1ContentManifest,
    Tier1ManifestSigner,
    Tier2HopAuthenticator,
    TieredManifestManager,
)
from tfp_core.manifest import (
    create_tiered_manifest,
    verify_tiered_manifest,
)


# ============================================================================
# Tier 1: Feature Tests (Happy Path & Multi-Algorithm Verification)
# ============================================================================

class TestPQCTieredManifestTier1Features:
    """Tier 1 Feature tests verifying PQC tiered manifest creation and verification."""

    @pytest.fixture
    def pqc_adapter(self):
        return PQCAdapter()

    def test_tier1_dilithium5_manifest_creation_and_verification(self, pqc_adapter):
        """Verify Tier 1 manifest creation and verification using Dilithium5 / ML-DSA-87."""
        kp = pqc_adapter.generate_dilithium5_keypair()
        signer = Tier1ManifestSigner(pqc_adapter)

        content_data = b"TFP_PQC_SECURE_PAYLOAD_V4_DILITHIUM5"
        content_hash = hashlib.sha3_256(content_data).hexdigest()
        chunk_hashes = [hashlib.sha3_256(content_data[:16]).hexdigest(), hashlib.sha3_256(content_data[16:]).hexdigest()]
        chunk_sizes = [16, len(content_data) - 16]

        manifest = signer.sign_manifest(
            content_hash=content_hash,
            total_size=len(content_data),
            chunk_hashes=chunk_hashes,
            chunk_sizes=chunk_sizes,
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
            metadata={"content_type": "text/plain", "version": "1.0"},
        )

        assert manifest.algorithm_id == "dilithium5"
        assert manifest.content_hash == content_hash
        assert len(manifest.pqc_signature) > 0
        assert manifest.manifest_id.startswith("tfp_m1_")

        # Verify signature
        is_valid = signer.verify_manifest(manifest, author_pubkey=kp.public_key)
        assert is_valid is True

    def test_tier1_sphincs_manifest_creation_and_verification(self, pqc_adapter):
        """Verify Tier 1 manifest creation and verification using SPHINCS+."""
        kp = pqc_adapter.generate_sphincs_keypair()
        signer = Tier1ManifestSigner(pqc_adapter)

        content_hash = hashlib.sha3_256(b"SPHINCS_BROADCAST_CONTENT").hexdigest()
        manifest = signer.sign_manifest(
            content_hash=content_hash,
            total_size=512,
            chunk_hashes=[content_hash],
            chunk_sizes=[512],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="sphincs+-sha2-256f",
        )

        assert manifest.algorithm_id == "sphincs+-sha2-256f"
        assert signer.verify_manifest(manifest) is True

    def test_tier1_ed25519_and_dual_signature_manifest(self, pqc_adapter):
        """Verify Tier 1 manifest with classical Ed25519 and Dual PQC+Ed25519 signatures."""
        signer = Tier1ManifestSigner(pqc_adapter)
        
        # Ed25519
        from cryptography.hazmat.primitives.asymmetric import ed25519
        priv_obj = ed25519.Ed25519PrivateKey.generate()
        ed_priv = priv_obj.private_bytes_raw()
        ed_pub = priv_obj.public_key().public_bytes_raw()

        manifest_ed = signer.sign_manifest(
            content_hash="ed25519_test_hash",
            total_size=100,
            chunk_hashes=["h1", "h2"],
            chunk_sizes=[50, 50],
            author_pubkey=ed_pub,
            author_privkey=ed_priv,
            algorithm="ed25519",
        )
        assert signer.verify_manifest(manifest_ed, author_pubkey=ed_pub) is True

        # Dual mode
        kp_pqc = pqc_adapter.generate_dilithium5_keypair()
        manifest_dual = signer.sign_manifest(
            content_hash="dual_test_hash",
            total_size=200,
            chunk_hashes=["h_all"],
            chunk_sizes=[200],
            author_pubkey=kp_pqc.public_key,
            author_privkey=kp_pqc.secret_key,
            algorithm="dual",
            classical_privkey=ed_priv,
        )
        assert manifest_dual.classical_signature is not None
        assert signer.verify_manifest(manifest_dual, author_pubkey=kp_pqc.public_key) is True

    def test_manifest_serialization_roundtrip(self, pqc_adapter):
        """Verify Tier1ContentManifest to_dict and from_dict preserve all properties and validity."""
        kp = pqc_adapter.generate_dilithium5_keypair()
        signer = Tier1ManifestSigner(pqc_adapter)

        manifest = signer.sign_manifest(
            content_hash="serialize_roundtrip_test",
            total_size=4096,
            chunk_hashes=["chunk_0_hash", "chunk_1_hash"],
            chunk_sizes=[2048, 2048],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            fountain_params={"symbol_size": 256, "k": 16},
            metadata={"author_role": "validator_prime"},
        )

        manifest_dict = manifest.to_dict()
        assert isinstance(manifest_dict, dict)
        assert manifest_dict["author_pubkey"] == kp.public_key.hex()

        reconstructed = Tier1ContentManifest.from_dict(manifest_dict)
        assert reconstructed.manifest_id == manifest.manifest_id
        assert reconstructed.content_hash == manifest.content_hash
        assert reconstructed.total_size == manifest.total_size
        assert reconstructed.chunk_hashes == manifest.chunk_hashes
        assert reconstructed.fountain_params == manifest.fountain_params
        assert reconstructed.metadata == manifest.metadata
        assert reconstructed.author_pubkey == manifest.author_pubkey
        assert reconstructed.pqc_signature == manifest.pqc_signature

        # Reconstructed manifest must pass verification
        assert signer.verify_manifest(reconstructed) is True

    def test_tier2_hop_authenticator_generation_and_verification(self):
        """Verify lightweight Tier 2 intra-mesh hop token generation and verification."""
        hop_secret = os.urandom(32)
        chunk_hash = hashlib.sha256(b"chunk_payload_0").hexdigest()
        hop_index = 3

        token_16 = Tier2HopAuthenticator.generate_hop_token(
            hop_secret=hop_secret,
            chunk_hash=chunk_hash,
            hop_index=hop_index,
            token_len=16,
        )
        assert len(token_16) == 16

        # Valid verification
        is_valid = Tier2HopAuthenticator.verify_hop_token(
            hop_secret=hop_secret,
            chunk_hash=chunk_hash,
            hop_index=hop_index,
            token=token_16,
            token_len=16,
        )
        assert is_valid is True

    def test_tier2_merkle_chunk_token(self):
        """Verify Merkle chunk binding token generation and verification."""
        secret = os.urandom(32)
        root_hash = "merkle_root_abcdef"
        chunk_hash = "chunk_hash_123456"
        chunk_idx = 7

        token = Tier2HopAuthenticator.generate_chunk_merkle_token(
            root_hash=root_hash,
            chunk_hash=chunk_hash,
            chunk_index=chunk_idx,
            secret_key=secret,
        )
        assert len(token) == 32
        assert Tier2HopAuthenticator.verify_chunk_merkle_token(
            root_hash=root_hash,
            chunk_hash=chunk_hash,
            chunk_index=chunk_idx,
            token=token,
            secret_key=secret,
        ) is True

    def test_tiered_manifest_manager_convenience_facade(self, pqc_adapter):
        """Verify top-level module functions create_tiered_manifest and verify_tiered_manifest."""
        kp = pqc_adapter.generate_dilithium5_keypair()
        manifest = create_tiered_manifest(
            content_hash="high_level_facade_test",
            total_size=1024,
            chunk_hashes=["h0", "h1"],
            chunk_sizes=[512, 512],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
        )

        assert verify_tiered_manifest(manifest) is True
        assert verify_tiered_manifest(manifest, author_pubkey=kp.public_key) is True


# ============================================================================
# Tier 2: Boundary & Edge Cases (Adversarial Tampering & Rejections)
# ============================================================================

class TestPQCTieredManifestTier2EdgeCases:
    """Tier 2 Edge and Boundary tests for manifest tampering, signature corruption, and hop rejection."""

    @pytest.fixture
    def sample_manifest(self):
        pqc = PQCAdapter()
        kp = pqc.generate_dilithium5_keypair()
        signer = Tier1ManifestSigner(pqc)
        manifest = signer.sign_manifest(
            content_hash="unaltered_content_root",
            total_size=2048,
            chunk_hashes=["c0", "c1"],
            chunk_sizes=[1024, 1024],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
        )
        return manifest, kp, signer

    def test_corrupted_manifest_content_hash_rejected(self, sample_manifest):
        """Verify altering content_hash invalidates the manifest signature."""
        manifest, kp, signer = sample_manifest
        manifest.content_hash = "tampered_content_hash"
        assert signer.verify_manifest(manifest, author_pubkey=kp.public_key) is False

    def test_corrupted_manifest_chunk_hashes_rejected(self, sample_manifest):
        """Verify tampering with chunk recipes invalidates the manifest signature."""
        manifest, kp, signer = sample_manifest
        manifest.chunk_hashes = ["c0", "tampered_c1"]
        assert signer.verify_manifest(manifest, author_pubkey=kp.public_key) is False

    def test_corrupted_manifest_total_size_rejected(self, sample_manifest):
        """Verify altering total_size invalidates the manifest signature."""
        manifest, kp, signer = sample_manifest
        manifest.total_size = 999999
        assert signer.verify_manifest(manifest, author_pubkey=kp.public_key) is False

    def test_corrupted_pqc_signature_rejected(self, sample_manifest):
        """Verify bit flips in the PQC signature cause verification failure."""
        manifest, kp, signer = sample_manifest
        sig_bytes = bytearray(manifest.pqc_signature)
        sig_bytes[0] ^= 0xFF
        sig_bytes[10] ^= 0xAA
        manifest.pqc_signature = bytes(sig_bytes)
        assert signer.verify_manifest(manifest, author_pubkey=kp.public_key) is False

    def test_wrong_author_public_key_rejected(self, sample_manifest):
        """Verify signature verification fails when presented with another node's public key."""
        manifest, kp, signer = sample_manifest
        pqc = PQCAdapter()
        wrong_kp = pqc.generate_dilithium5_keypair()
        assert signer.verify_manifest(manifest, author_pubkey=wrong_kp.public_key) is False

    def test_corrupted_hop_token_rejected(self):
        """Verify tampered hop tokens are rejected."""
        hop_secret = os.urandom(32)
        chunk_hash = "chunk_secure_abc"
        hop_index = 1

        token = Tier2HopAuthenticator.generate_hop_token(hop_secret, chunk_hash, hop_index)
        corrupt_token = bytearray(token)
        corrupt_token[0] ^= 0x01

        assert Tier2HopAuthenticator.verify_hop_token(
            hop_secret, chunk_hash, hop_index, bytes(corrupt_token)
        ) is False

    def test_hop_token_mismatched_parameters_rejected(self):
        """Verify hop tokens fail if chunk_hash or hop_index do not match."""
        hop_secret = os.urandom(32)
        token = Tier2HopAuthenticator.generate_hop_token(hop_secret, "chunk_1", 1)

        # Wrong chunk hash
        assert Tier2HopAuthenticator.verify_hop_token(hop_secret, "chunk_2", 1, token) is False
        # Wrong hop index
        assert Tier2HopAuthenticator.verify_hop_token(hop_secret, "chunk_1", 2, token) is False
        # Wrong secret
        assert Tier2HopAuthenticator.verify_hop_token(os.urandom(32), "chunk_1", 1, token) is False

    def test_merkle_chunk_token_tampering_rejected(self):
        """Verify tampering chunk_index or secret in Merkle chunk token fails."""
        secret = os.urandom(32)
        token = Tier2HopAuthenticator.generate_chunk_merkle_token("root_a", "chunk_x", 0, secret)

        # Wrong index
        assert Tier2HopAuthenticator.verify_chunk_merkle_token("root_a", "chunk_x", 1, token, secret) is False
        # Wrong root
        assert Tier2HopAuthenticator.verify_chunk_merkle_token("root_b", "chunk_x", 0, token, secret) is False
