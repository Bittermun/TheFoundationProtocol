# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive Multi-Tier Test Suite: Deterministic Repair Seed Schedules & Anti-Pollution Pre-Validation

Covers:
- Tier 1 (Feature):
    * Deterministic repair droplet seed generation (seed >= K) via HMAC-SHA3-256
    * Seed sequence predictability and synchronization across independent sender/receiver endpoints
    * Strict mathematical invariants: seed >= K, uint32 bounds, zero intra-batch collisions
    * RootHash and SessionNonce cryptographic binding
    * Systematic vs. repair droplet structure & Soliton degree distribution
    * End-to-end Fountain encoding and Gaussian elimination decoding using deterministic repair droplets
    * TransportFountainChannel admission and payload reconstruction
- Tier 2 (Boundary/Edge & Adversarial Anti-Pollution):
    * O(1) verify_droplet_seed_authenticity pre-validation filter
    * Byzantine degree tampering detection and rejection
    * Byzantine indices manipulation / linear combination forgery rejection
    * Fabricated seed and corrupted symbol payload rejection in TransportFountainChannel
    * Prevention of Gaussian elimination matrix corruption and memory exhaustion
    * Boundary conditions: empty payload, single-byte payload, K=1, large repair schedules (5000+ seeds)
    * Insufficient rank and deficient droplet count error handling
"""

import hashlib
import os
import random
import pytest
from typing import List

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    LubyTransformCodec,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)
from tfp_transport.fountain import TransportFountainChannel


# ============================================================================
# Tier 1: Feature Tests (Happy Path & Protocol Invariants)
# ============================================================================

class TestDeterministicSeedScheduleTier1Features:
    """Tier 1 Feature tests verifying deterministic repair seed schedule logic."""

    def test_derive_repair_seed_schedule_reproducibility(self):
        """Verify that identical inputs produce identical repair seed sequences."""
        root_hash = hashlib.sha3_256(b"content_manifest_payload_v4").digest()
        session_nonce = b"tfp_session_nonce_xyz123"
        k = 10
        repair_count = 20

        schedule1 = derive_repair_seed_schedule(root_hash, session_nonce, k, repair_count)
        schedule2 = derive_repair_seed_schedule(root_hash, session_nonce, k, repair_count)

        assert len(schedule1) == repair_count
        assert len(schedule2) == repair_count
        assert schedule1 == schedule2

    def test_seed_invariants_and_bounds(self):
        """Verify seeds satisfy seed >= K and fit in 32-bit unsigned integer bounds."""
        root_hash = "0123456789abcdef" * 4
        session_nonce = "node_alpha_beta"
        k = 16
        repair_count = 100

        schedule = derive_repair_seed_schedule(root_hash, session_nonce, k, repair_count)

        assert len(schedule) == repair_count
        for seed in schedule:
            assert isinstance(seed, int)
            assert seed >= k, f"Repair seed {seed} must be >= K ({k})"
            assert 0 <= seed <= 0xFFFFFFFF, f"Seed {seed} must fit in uint32"

        # Unique seeds in the derived window
        assert len(set(schedule)) == repair_count

    def test_root_hash_and_nonce_cryptographic_binding(self):
        """Verify changing root hash or session nonce derives distinct seed sequences."""
        root_a = hashlib.sha3_256(b"file_alpha").digest()
        root_b = hashlib.sha3_256(b"file_beta").digest()
        nonce_a = b"nonce_1"
        nonce_b = b"nonce_2"
        k = 8
        count = 15

        sched_a = derive_repair_seed_schedule(root_a, nonce_a, k, count)
        sched_b = derive_repair_seed_schedule(root_b, nonce_a, k, count)
        sched_c = derive_repair_seed_schedule(root_a, nonce_b, k, count)

        assert sched_a != sched_b
        assert sched_a != sched_c
        assert sched_b != sched_c

    def test_sender_receiver_schedule_synchronization(self):
        """Verify sender and receiver independently construct synchronized repair schedules."""
        shared_root = hashlib.sha256(b"manifest_root_block").digest()
        shared_nonce = b"session_secret_nonce"
        k_blocks = 12
        rep_blocks = 10

        sender_seeds = derive_repair_seed_schedule(shared_root, shared_nonce, k_blocks, rep_blocks)
        receiver_seeds = derive_repair_seed_schedule(shared_root, shared_nonce, k_blocks, rep_blocks)

        assert sender_seeds == receiver_seeds
        assert all(s >= k_blocks for s in receiver_seeds)

    def test_systematic_and_repair_droplet_properties(self):
        """Verify systematic droplets have seed < K and degree=1, while repair droplets have seed >= K."""
        symbol_size = 64
        data = b"TFP_PROTOCOL_RUST_PYTHON_NEXTGEN_TEST_PAYLOAD_" * 8  # 368 bytes -> 6 blocks
        root_hash = hashlib.sha3_256(data).digest()

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = encoder.encode(data, redundancy=0.5)

        assert k == 6
        assert orig_len == len(data)
        assert len(droplets) >= k

        # Check systematic droplets (0..k-1)
        for i in range(k):
            d = droplets[i]
            assert d.seed == i
            assert d.degree == 1
            assert d.indices == [i]
            assert len(d.payload) == symbol_size

        # Check repair droplets (seed >= k)
        for d in droplets[k:]:
            assert d.seed >= k
            assert 1 <= d.degree <= k
            assert len(d.indices) == d.degree
            assert all(0 <= idx < k for idx in d.indices)
            assert len(d.payload) == symbol_size

    def test_fountain_codec_deterministic_encode_decode_roundtrip(self):
        """Verify data encode, loss of systematic packets, and recovery via deterministic repair droplets."""
        symbol_size = 128
        raw_data = os.urandom(1024)  # 8 blocks
        root_hash = hashlib.sha3_256(raw_data).digest()
        session_nonce = b"test_session_nonce_42"

        codec = FountainCodec(
            symbol_size=symbol_size,
            root_hash=root_hash,
            session_nonce=session_nonce,
        )

        droplets, k, orig_len = codec.encode(raw_data, redundancy=1.5)
        assert k == 8
        assert len(droplets) == 20  # 8 systematic + 12 repair

        # Simulate 50% packet drop on systematic packets: keep only 4 systematic + remaining repair droplets
        received = droplets[:4] + droplets[8:]
        assert len(received) >= k

        # Decode
        recovered = codec.decode(received, k=k, orig_len=orig_len)
        assert recovered == raw_data

    def test_transport_fountain_channel_admission_and_decode(self):
        """Verify TransportFountainChannel admits valid droplets and successfully reconstructs payload."""
        symbol_size = 64
        test_payload = b"Mesh Network Packet Stream Data for Foundation Protocol V4" * 4
        root_hash = hashlib.sha3_256(test_payload).digest()
        session_nonce = b"hop_transport_nonce"

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=session_nonce)
        droplets, k, orig_len = encoder.encode(test_payload, redundancy=0.6)

        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=session_nonce,
        )

        for d in droplets:
            admitted = channel.admit_droplet(d)
            assert admitted is True

        assert channel.can_decode() is True
        assert channel.rejected_count == 0
        decoded_payload = channel.decode()
        assert decoded_payload == test_payload


# ============================================================================
# Tier 2: Boundary & Edge Cases (Adversarial Anti-Pollution & Robustness)
# ============================================================================

class TestDeterministicSeedScheduleTier2EdgeCases:
    """Tier 2 Edge and Boundary tests for anti-pollution pre-validation and fault injection."""

    def test_o1_prevalidation_filter_valid_droplets(self):
        """Verify verify_droplet_seed_authenticity approves legitimate systematic and repair droplets."""
        k = 5
        # Valid systematic droplet
        assert verify_droplet_seed_authenticity(
            droplet_seed=2,
            total_source_blocks=k,
            degree=1,
            indices=[2],
        ) is True

        # Valid repair droplet with correctly derived degree/indices
        seed = 100
        rng = random.Random(seed)
        from tfp_core_v4.fountain import _sample_soliton_degree
        deg = _sample_soliton_degree(k, rng)
        indices = sorted(rng.sample(range(k), deg))

        assert verify_droplet_seed_authenticity(
            droplet_seed=seed,
            total_source_blocks=k,
            degree=deg,
            indices=indices,
        ) is True

    def test_byzantine_degree_tampering_rejected(self):
        """Verify adversarial manipulation of droplet degree is rejected in O(1)."""
        k = 8
        # Systematic droplet with forged degree > 1
        assert verify_droplet_seed_authenticity(
            droplet_seed=3,
            total_source_blocks=k,
            degree=3,  # Invalid: systematic must be degree 1
            indices=[3],
        ) is False

        # Repair droplet with tampered degree
        seed = 42
        rng = random.Random(seed)
        from tfp_core_v4.fountain import _sample_soliton_degree
        correct_deg = _sample_soliton_degree(k, rng)
        wrong_deg = (correct_deg % k) + 1
        if wrong_deg == correct_deg:
            wrong_deg = (wrong_deg % k) + 1

        assert verify_droplet_seed_authenticity(
            droplet_seed=seed,
            total_source_blocks=k,
            degree=wrong_deg,
            indices=sorted(rng.sample(range(k), correct_deg)),
        ) is False

    def test_byzantine_indices_tampering_rejected(self):
        """Verify adversarial manipulation of symbol indices is rejected in O(1)."""
        k = 6
        # Systematic droplet claiming index of a different block
        assert verify_droplet_seed_authenticity(
            droplet_seed=2,
            total_source_blocks=k,
            degree=1,
            indices=[4],  # Invalid: index must match seed for systematic
        ) is False

        # Repair droplet with altered indices
        seed = 55
        rng = random.Random(seed)
        from tfp_core_v4.fountain import _sample_soliton_degree
        deg = _sample_soliton_degree(k, rng)
        correct_indices = sorted(rng.sample(range(k), deg))
        tampered_indices = [(idx + 1) % k for idx in correct_indices]

        if tampered_indices != correct_indices:
            assert verify_droplet_seed_authenticity(
                droplet_seed=seed,
                total_source_blocks=k,
                degree=deg,
                indices=tampered_indices,
            ) is False

    def test_byzantine_pollution_attack_rejected_by_transport_channel(self):
        """Verify TransportFountainChannel drops Byzantine poisoned droplets before Gaussian buffer."""
        symbol_size = 64
        payload = b"Legitimate Payload Data" * 8
        root_hash = hashlib.sha3_256(payload).digest()

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = encoder.encode(payload, redundancy=0.5)

        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
        )

        # 1. Admit legitimate droplets
        for d in droplets:
            channel.admit_droplet(d)

        initial_admitted = len(channel.received_droplets)

        # 2. Inject Byzantine poisoned droplet: invalid payload size
        poison1 = FountainDroplet(seed=999, degree=1, indices=[0], payload=b"too_short")
        assert channel.admit_droplet(poison1) is False
        assert channel.rejected_count == 1

        # 3. Inject Byzantine poisoned droplet: forged degree / indices
        poison2 = FountainDroplet(seed=1000, degree=5, indices=[0, 1], payload=b"\x00" * symbol_size)
        assert channel.admit_droplet(poison2) is False
        assert channel.rejected_count == 2

        # 4. Inject Byzantine systematic droplet with wrong index
        poison3 = FountainDroplet(seed=0, degree=1, indices=[3], payload=b"\xff" * symbol_size)
        assert channel.admit_droplet(poison3) is False
        assert channel.rejected_count == 3

        # Confirm matrix buffer was not polluted
        assert len(channel.received_droplets) == initial_admitted
        # Confirm channel decodes legitimate payload without corruption
        assert channel.decode() == payload

    def test_boundary_empty_payload(self):
        """Verify encoder returns empty structures for 0-byte input."""
        encoder = FountainEncoder(symbol_size=64)
        droplets, k, orig_len = encoder.encode(b"")
        assert droplets == []
        assert k == 0
        assert orig_len == 0

    def test_boundary_single_block_payload(self):
        """Verify encoding and decoding a single block (K=1)."""
        symbol_size = 128
        single_block_data = b"Tiny payload < 128 bytes"
        codec = FountainCodec(symbol_size=symbol_size)

        droplets, k, orig_len = codec.encode(single_block_data, redundancy=0.5)
        assert k == 1
        assert orig_len == len(single_block_data)
        assert len(droplets) >= 1

        decoded = codec.decode(droplets, k=k, orig_len=orig_len)
        assert decoded == single_block_data

    def test_insufficient_droplets_raises_value_error(self):
        """Verify decoder raises ValueError when presented with fewer than K droplets."""
        codec = FountainCodec(symbol_size=64)
        data = os.urandom(256)  # 4 blocks
        droplets, k, orig_len = codec.encode(data, redundancy=0.0)

        assert k == 4
        # Pass only 3 droplets
        with pytest.raises(ValueError, match="Need at least 4 valid droplets"):
            codec.decode(droplets[:3], k=k, orig_len=orig_len)

    def test_linearly_dependent_droplets_raise_insufficient_rank(self):
        """Verify decoder raises ValueError if droplets are linearly dependent (rank < K)."""
        codec = FountainCodec(symbol_size=64)
        data = os.urandom(256)  # 4 blocks
        droplets, k, orig_len = codec.encode(data, redundancy=0.5)
        assert k == 4

        # Pass 4 copies of the SAME systematic droplet
        duplicate_droplets = [droplets[0]] * 4
        with pytest.raises(ValueError, match="Insufficient linearly independent droplets"):
            codec.decode(duplicate_droplets, k=k, orig_len=orig_len, pre_validate=False)

    def test_large_repair_schedule_rollover(self):
        """Verify large repair counts (5,000 seeds) execute reliably without seed pool failure."""
        root = hashlib.sha3_256(b"large_mesh_transfer").digest()
        k = 32
        large_count = 5000

        schedule = derive_repair_seed_schedule(root, b"session_big", k, large_count)
        assert len(schedule) == large_count
        assert all(s >= k for s in schedule)
        assert all(s <= 0xFFFFFFFF for s in schedule)
