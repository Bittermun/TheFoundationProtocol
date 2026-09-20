# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Stress & Cryptographic Validation Test Harness.

Constructed by challenger_1_gen2 to stress-test:
1. Malformed packets, bit-flipped signatures, truncated payloads against MutualisticAuditor & GossipVerifier.
2. Zero-entropy, uniform, and high-entropy edge cases in Shannon entropy calculations.
3. Corrupted RaptorQ chunks and HMAC tampering rejection (FFI & Pure Python).
4. Session token forgery, receipt replay attempts, and PUF/ZKP access gates.
"""

import collections
import hashlib
import hmac as _hmac
import math
import os
import secrets
import struct
import time
from typing import List

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from tfp_core.crypto.agility_registry import (
    CryptoAgilityRegistry,
    CryptoSuite,
    sign_data,
)
from tfp_core.crypto.pqc_adapter import PQCAdapter, KeyPair, Signature
from tfp_core.security.mutualistic_defense import (
    AuditorProfile,
    ContentTag,
    GossipVerifier,
    HeuristicPack,
    LocalTrustCache,
    MutualisticAuditor,
    TrustLevel,
)
from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.node import TFPNode
from tfp_client.lib.core.tfp_engine import TFPClient, SecurityError
from tfp_client.lib.credit.ledger import CreditLedger, Receipt
from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter as PurePythonRaptorQ, IntegrityError as PureIntegrityError
from tfp_client.lib.fountain.raptorq_ffi import RealRaptorQAdapter as FFIRaptorQ, IntegrityError as FFIIntegrityError
from tfp_client.lib.zkp.zkp_real import RealZKPAdapter
from tfp_demo.server import app, _RateLimiter


def _make_sig(puf_entropy: bytes, message: str) -> str:
    """Compute HMAC-SHA-256(puf_entropy, message) as hex."""
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


# ==============================================================================
# Suite 1: Mutualistic Defense & Gossip Cryptographic Validation Stress
# ==============================================================================

class TestMutualisticDefenseAdversarialStress:
    """Stress test MutualisticAuditor, GossipVerifier, and HeuristicPack under hostile inputs."""

    def test_heuristic_pack_ed25519_genuine_and_bit_flipped(self):
        """Verify Ed25519 asymmetric signatures on HeuristicPack and rejection of bit-flipped signatures."""
        privkey = ed25519.Ed25519PrivateKey.generate()
        pubkey = privkey.public_key().public_bytes_raw()

        version = "v3.0.0"
        rules = {"r1": {"pattern": "badpattern", "severity": "critical", "category": "binary"}}
        data = f"{version}:{str(rules)}".encode()
        valid_sig = privkey.sign(data).hex()

        # 1. Valid signature passes
        pack_valid = HeuristicPack(version=version, signature=valid_sig, rules=rules)
        assert pack_valid.verify_signature(pubkey) is True

        # 2. Bit-flipped signature must fail
        sig_bytes = bytearray(bytes.fromhex(valid_sig))
        sig_bytes[0] ^= 0x01
        pack_flipped = HeuristicPack(version=version, signature=sig_bytes.hex(), rules=rules)
        assert pack_flipped.verify_signature(pubkey) is False

        # 3. Truncated signature must fail
        pack_truncated = HeuristicPack(version=version, signature=valid_sig[:32], rules=rules)
        assert pack_truncated.verify_signature(pubkey) is False

        # 4. Mismatched public key must fail
        other_pubkey = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        assert pack_valid.verify_signature(other_pubkey) is False

        # 5. Empty public key or empty signature must fail
        assert pack_valid.verify_signature(b"") is False
        pack_empty_sig = HeuristicPack(version=version, signature="", rules=rules)
        assert pack_empty_sig.verify_signature(pubkey) is False

        # 6. Forged unkeyed hash (CRIT-03 exploit attempt) must fail
        forged_unkeyed_sig = hashlib.sha3_256(data).hexdigest()[:16]
        pack_forged = HeuristicPack(version=version, signature=forged_unkeyed_sig, rules=rules)
        assert pack_forged.verify_signature(pubkey) is False

    def test_gossip_verifier_signal_signing_and_tampering(self):
        """Verify GossipVerifier keyed HMAC signatures, tamper rejection, and expiry."""
        gv_alice = GossipVerifier("device_alice")
        gv_bob = GossipVerifier("device_bob")

        # 1. Alice broadcasts a legitimate trust signal
        signal = gv_alice.broadcast_trust_signal("auditor_x", outcome=True, category="video")
        assert signal["reporter"] == "device_alice"
        assert signal["auditor"] == "auditor_x"
        assert signal["outcome"] is True
        assert len(signal["signature"]) == 16

        # 2. Bob receives Alice's authentic signal
        assert gv_bob.receive_trust_signal(signal) is True
        score, count = gv_bob.aggregate_signals("auditor_x")
        assert count == 1
        assert score == 1.0

        # 3. Adversary tampers with outcome (replaces True with False without re-signing)
        tampered_signal_outcome = dict(signal)
        tampered_signal_outcome["outcome"] = False
        assert gv_bob.receive_trust_signal(tampered_signal_outcome) is False

        # 4. Adversary tampers with auditor ID
        tampered_signal_auditor = dict(signal)
        tampered_signal_auditor["auditor"] = "auditor_innocent"
        assert gv_bob.receive_trust_signal(tampered_signal_auditor) is False

        # 5. Adversary tampers with signature
        tampered_signal_sig = dict(signal)
        tampered_signal_sig["signature"] = "0011223344556677"
        assert gv_bob.receive_trust_signal(tampered_signal_sig) is False

        # 6. Adversary sends empty/malformed signal dictionary
        assert gv_bob.receive_trust_signal({}) is False
        assert gv_bob.receive_trust_signal({"reporter": "", "signature": ""}) is False

        # 7. Expired signal (> 24 hours old) must be rejected
        expired_signal = dict(signal)
        expired_signal["timestamp"] = time.time() - (25 * 3600)
        assert gv_bob.receive_trust_signal(expired_signal) is False

    def test_mutualistic_auditor_adversarial_payload_audit(self):
        """Test MutualisticAuditor under adversarial payloads, high entropy, and rapid sampling."""
        auditor = MutualisticAuditor(device_id="node_auditor_1")

        # Zero-length payload
        res_empty = auditor.audit_content("hash_0", b"", "video", request_count=150)
        assert res_empty["status"] == "audited"
        assert res_empty["confidence"] <= 0.5

        # All-zero payload (zero entropy)
        zero_payload = b"\x00" * 1024
        res_zero = auditor.audit_content("hash_zero", zero_payload, "video", request_count=150)
        assert res_zero["status"] == "audited"
        assert "high_entropy" not in res_zero["tags"]

        # High entropy payload (> 7.8 bits/byte)
        high_entropy_payload = os.urandom(2048)
        res_high = auditor.audit_content("hash_high", high_entropy_payload, "archive", request_count=150)
        assert res_high["status"] == "audited"
        assert "high_entropy" in res_high["tags"]
        assert res_high["confidence"] > 0.5


# ==============================================================================
# Suite 2: Shannon Entropy Calculation Bounds & Invariant Stress
# ==============================================================================

class TestShannonEntropyCalculationInvariants:
    """Exhaustive boundary testing of Shannon entropy formula across mathematical extremes."""

    @pytest.fixture
    def auditor(self):
        return MutualisticAuditor(device_id="entropy_auditor")

    def test_entropy_empty_bytes(self, auditor):
        """H("") = 0.0 bits/byte."""
        assert auditor._calculate_entropy(b"") == 0.0

    def test_entropy_single_byte(self, auditor):
        """H("A") = 0.0 bits/byte."""
        assert auditor._calculate_entropy(b"A") == 0.0
        assert auditor._calculate_entropy(b"\x00") == 0.0
        assert auditor._calculate_entropy(b"\xff") == 0.0

    def test_entropy_monotonous_repeated_bytes(self, auditor):
        """H(c^N) = 0.0 bits/byte for any N >= 1."""
        for byte_val in (0x00, 0x55, 0xAA, 0xFF):
            payload = bytes([byte_val]) * 10000
            assert auditor._calculate_entropy(payload) == 0.0

    def test_entropy_two_uniform_bytes(self, auditor):
        """H(X) with 2 equally probable bytes = log2(2) = 1.000000 bit/byte."""
        payload = b"\x00\x01" * 5000
        entropy = auditor._calculate_entropy(payload)
        assert math.isclose(entropy, 1.0, rel_tol=1e-6)

    def test_entropy_four_uniform_bytes(self, auditor):
        """H(X) with 4 equally probable bytes = log2(4) = 2.000000 bits/byte."""
        payload = b"\x00\x01\x02\x03" * 2500
        entropy = auditor._calculate_entropy(payload)
        assert math.isclose(entropy, 2.0, rel_tol=1e-6)

    def test_entropy_sixteen_uniform_bytes(self, auditor):
        """H(X) with 16 equally probable bytes = log2(16) = 4.000000 bits/byte."""
        payload = bytes(range(16)) * 1000
        entropy = auditor._calculate_entropy(payload)
        assert math.isclose(entropy, 4.0, rel_tol=1e-6)

    def test_entropy_all_256_uniform_bytes_exact_maximum(self, auditor):
        """H(X) with all 256 byte values uniformly distributed = log2(256) = 8.000000 bits/byte."""
        payload = bytes(range(256)) * 500
        entropy = auditor._calculate_entropy(payload)
        assert math.isclose(entropy, 8.0, rel_tol=1e-9)

    def test_entropy_cryptographic_random_high_entropy(self, auditor):
        """H(X) for 100KB urandom must be in [7.99, 8.00] bits/byte."""
        payload = os.urandom(100000)
        entropy = auditor._calculate_entropy(payload)
        assert 7.99 <= entropy <= 8.0

    def test_entropy_invariant_non_negative_and_upper_bounded(self, auditor):
        """For all inputs, 0.0 <= H(X) <= 8.0."""
        test_inputs = [
            b"",
            b"a",
            b"ab",
            b"abc",
            b"The quick brown fox jumps over the lazy dog.",
            os.urandom(10),
            os.urandom(500),
            bytes(range(256)),
            b"\x00" * 50000,
        ]
        for data in test_inputs:
            h = auditor._calculate_entropy(data)
            assert 0.0 <= h <= 8.0, f"Entropy invariant violated: {h}"


# ==============================================================================
# Suite 3: RaptorQ Codec Tampering, Shard Poisoning & HMAC Rejection
# ==============================================================================

class TestRaptorQTamperingAndHMACRejection:
    """Stress test RaptorQ decoders against corrupted HMAC shards, truncation, and key mismatches."""

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_single_corrupted_shard_dropped_and_decode_succeeds(self, adapter_cls):
        """HIGH-01: A single corrupted shard must NOT abort decoding if valid repair shards >= K."""
        adapter = adapter_cls(shard_size=1024)
        secret = b"authentic_hmac_secret_key_32b00"
        data = b"TFP_HIGH_AVAILABILITY_ERASURE_STREAM_" * 100  # ~3.7KB -> 4 shards
        shards = adapter.encode(data, redundancy=0.5, hmac_key=secret)
        assert len(shards) >= 5

        # Inject corruption into 1 shard payload
        corrupted_shards = list(shards)
        tampered = bytearray(corrupted_shards[1])
        tampered[20] ^= 0xFF  # Flip byte in payload
        corrupted_shards[1] = bytes(tampered)

        # Decoding must succeed despite corrupted shard
        recovered = adapter.decode(corrupted_shards, hmac_key=secret)
        assert recovered == data

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_excessive_corrupted_shards_raises_integrity_error(self, adapter_cls):
        """When corrupted shards reduce valid count below K, decoder must raise IntegrityError."""
        adapter = adapter_cls(shard_size=1024)
        secret = b"authentic_hmac_secret_key_32b00"
        data = b"CRITICAL_DATA_BLOCK_" * 150
        shards = adapter.encode(data, redundancy=0.2, hmac_key=secret)

        # Corrupt all shards except 1
        corrupted_shards = list(shards)
        for i in range(1, len(corrupted_shards)):
            tampered = bytearray(corrupted_shards[i])
            tampered[-1] ^= 0x01  # Tamper HMAC tag
            corrupted_shards[i] = bytes(tampered)

        with pytest.raises((PureIntegrityError, FFIIntegrityError, ValueError)):
            adapter.decode(corrupted_shards, hmac_key=secret)

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_wrong_hmac_secret_rejects_all_shards(self, adapter_cls):
        """Decoding with wrong secret key must reject all shards."""
        adapter = adapter_cls(shard_size=1024)
        secret_correct = b"correct_hmac_secret_key_32b000"
        secret_wrong = b"wrong_hmac_secret_key_32b00000"
        data = b"TOP_SECRET_BROADCAST_PAYLOAD_" * 50
        shards = adapter.encode(data, redundancy=0.3, hmac_key=secret_correct)

        with pytest.raises((PureIntegrityError, FFIIntegrityError, ValueError)):
            adapter.decode(shards, hmac_key=secret_wrong)

    @pytest.mark.parametrize("adapter_cls", [PurePythonRaptorQ, FFIRaptorQ])
    def test_truncated_shard_lengths_handled_gracefully(self, adapter_cls):
        """Shards truncated to < 16 bytes or < 48 bytes must be skipped cleanly."""
        adapter = adapter_cls(shard_size=1024)
        secret = b"authentic_hmac_secret_key_32b00"
        data = b"RESILIENT_DATA_BLOCK_" * 100
        shards = adapter.encode(data, redundancy=0.5, hmac_key=secret)

        # Replace one shard with truncated garbage
        corrupted_shards = list(shards)
        corrupted_shards[0] = b"\x01\x02\x03\x04\x05"  # 5 bytes only

        recovered = adapter.decode(corrupted_shards, hmac_key=secret)
        assert recovered == data


# ==============================================================================
# Suite 4: Session Token Forgery, Replay & Access Gates
# ==============================================================================

class TestSessionTokenAndAccessGatesAdversarial:
    """Stress test CreditLedger receipt replay, PUF signature tampering, and ZKP proof forgery."""

    def test_credit_ledger_double_spend_replay_attack(self):
        """HIGH-02: Presenting the same receipt multiple times must fail on 2nd attempt."""
        ledger = CreditLedger()
        proof1 = hashlib.sha3_256(b"task_proof_1").digest()
        proof2 = hashlib.sha3_256(b"task_proof_2").digest()

        r1 = ledger.mint(10, proof1)
        r2 = ledger.mint(10, proof2)
        assert ledger.balance == 20

        # Spend 5 credits with r1 -> balance = 15
        ledger.spend(5, r1)
        assert ledger.balance == 15
        assert r1.chain_hash in ledger.spent_receipts

        # Replay spend with exact same r1 -> must raise ValueError
        with pytest.raises(ValueError, match="receipt has already been spent"):
            ledger.spend(5, r1)

        # Balance remains 15 after rejected replay
        assert ledger.balance == 15

        # Spend with unused r2 succeeds
        ledger.spend(5, r2)
        assert ledger.balance == 10

    def test_credit_ledger_forged_unminted_receipt_rejection(self):
        """Presenting an unminted / fabricated receipt hash must be rejected."""
        ledger = CreditLedger()
        ledger.mint(10, hashlib.sha3_256(b"task_1").digest())

        forged_receipt = Receipt(chain_hash=b"\xde\xad\xbe\xef" * 8, credits=10)
        with pytest.raises(ValueError, match="not in chain"):
            ledger.spend(5, forged_receipt)

    def test_demo_server_puf_signature_forgery_and_replay(self):
        """Verify demo server rejects unauthorized signatures, fake task IDs, and replayed requests."""
        import uuid
        with TestClient(app) as client:
            puf_entropy = os.urandom(32)
            device_id = f"device_test_sec_{uuid.uuid4().hex[:8]}"

            # Enroll device
            resp = client.post(
                "/api/enroll",
                json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
            )
            assert resp.status_code == 200

            # 1. Tampered Signature Header
            fake_sig = _make_sig(os.urandom(32), f"{device_id}:task-1")
            resp_tampered = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "task-1"},
                headers={"X-Device-Sig": fake_sig},
            )
            assert resp_tampered.status_code == 401
            assert "invalid or missing device signature" in resp_tampered.json()["detail"]

            # 2. Authentic Earn Request
            valid_sig = _make_sig(puf_entropy, f"{device_id}:task-1")
            resp_valid = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "task-1"},
                headers={"X-Device-Sig": valid_sig},
            )
            assert resp_valid.status_code == 200
            assert resp_valid.json()["credits_earned"] == 10

            # 3. Replay of same task_id must return 409 Conflict
            resp_replay = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "task-1"},
                headers={"X-Device-Sig": valid_sig},
            )
            assert resp_replay.status_code == 409
            assert "already processed" in resp_replay.json()["detail"]

    def test_zkp_access_token_boundaries_and_forgery_rejection(self):
        """Verify ZKP proof generation, length checking, and structural validation."""
        zkp = RealZKPAdapter()
        valid_proof = zkp.generate_proof("authorized_content_id", b"secret_witness_token")
        public_hash = hashlib.sha3_256(b"authorized_content_id").digest()

        # Valid proof verifies
        assert zkp.verify_proof(valid_proof, public_hash) is True

        # Truncated or malformed length proof fails
        assert zkp.verify_proof(valid_proof[:64], public_hash) is False
        assert zkp.verify_proof(valid_proof + b"\x00", public_hash) is False
        assert zkp.verify_proof(b"", public_hash) is False

        # Invalid curve point prefix (e.g. 0x00 instead of 0x02/0x03) fails
        corrupted_point_proof = b"\x00" + valid_proof[1:]
        assert zkp.verify_proof(corrupted_point_proof, public_hash) is False

        # Zero scalar s fails
        zero_s_proof = valid_proof[:33] + (0).to_bytes(32, "big")
        assert zkp.verify_proof(zero_s_proof, public_hash) is False
