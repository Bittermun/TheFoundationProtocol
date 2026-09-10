# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial Empirical Challenge Suite: Deterministic Fountain Codecs & Anti-Pollution Mechanisms.
Constructed by Challenger 1 to stress-test:
1. Byzantine Pollution Attacks & Mathematical Immunity:
   - Spoofed/unregistered seed injection
   - Corrupted linear combinations with valid seeds (degree & index tampering)
   - Systematic droplet spoofing & out-of-bounds index injection
   - Cross-manifest/cross-session replay injection
   - Wire format binary deserialization fuzzing and mutation
2. High Erasure Channel Stress (10% to 60% Loss Rates):
   - Graduated erasure channels (10%, 20%, 30%, 40%, 50%, 60%)
   - 100% systematic packet erasure (pure repair droplet payload recovery)
   - Burst erasure channels (consecutive block loss)
   - Mixed adversarial conditions: simultaneous 50% packet erasure + 50% Byzantine pollution
   - Variable symbol sizes (16B to 1024B)
3. Seed Schedule Collision & Rollover Stress:
   - Massive seed schedule derivation (10,000+ seeds) with zero intra-batch collisions
   - Multi-session cryptographic binding and orthogonality across 50 distinct sessions
   - Uint32 boundary rollover and large K bounds
   - Empirical Soliton degree distribution fidelity
   - Seed schedule generation throughput
"""

import collections
import hashlib
import hmac
import math
import os
import random
import struct
import time
from typing import Dict, List, Set, Tuple

import pytest

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    LubyTransformCodec,
    _sample_soliton_degree,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)
from tfp_transport.fountain import TransportFountainChannel


# ==============================================================================
# Suite 1: Byzantine Pollution Attacks & Mathematical Immunity
# ==============================================================================

class TestByzantinePollutionAttacks:
    """Stress tests simulating malicious adversarial actors attempting to poison fountain decoding."""

    def test_spoofed_unregistered_seeds_rejection(self):
        """
        Adversary injects droplets with arbitrary spoofed seeds and randomized equations.
        Verify that O(1) verify_droplet_seed_authenticity rejects non-matching equations.
        """
        k = 16
        spoofed_attempts = 200

        rejected_count = 0
        for i in range(spoofed_attempts):
            fake_seed = 100000 + i
            # Adversary guesses arbitrary degree and indices
            fake_degree = random.randint(1, k)
            fake_indices = sorted(random.sample(range(k), fake_degree))

            # What the authentic generator would have produced:
            rng = random.Random(fake_seed)
            expected_degree = _sample_soliton_degree(k, rng)
            expected_indices = sorted(rng.sample(range(k), expected_degree))

            is_valid = verify_droplet_seed_authenticity(
                droplet_seed=fake_seed,
                total_source_blocks=k,
                degree=fake_degree,
                indices=fake_indices,
            )

            # Unless adversary accidentally guessed exact deterministic equation, it must be rejected
            if fake_degree == expected_degree and fake_indices == expected_indices:
                assert is_valid is True
            else:
                assert is_valid is False
                rejected_count += 1

        # In 200 random guesses for K=16, rejection rate should be >= 95%
        assert rejected_count > 190

    def test_tampered_soliton_degree_with_valid_seed(self):
        """
        Adversary uses a legitimate seed derived from schedule, but modifies degree.
        Verify verify_droplet_seed_authenticity strictly detects degree tampering in O(1).
        """
        k = 12
        root_hash = hashlib.sha3_256(b"target_document_manifest").digest()
        seeds = derive_repair_seed_schedule(root_hash, b"nonce_deg_test", k, repair_count=50)

        for seed in seeds:
            rng = random.Random(seed)
            correct_degree = _sample_soliton_degree(k, rng)
            correct_indices = sorted(rng.sample(range(k), correct_degree))

            # 1. Valid droplet must pass
            assert verify_droplet_seed_authenticity(
                droplet_seed=seed,
                total_source_blocks=k,
                degree=correct_degree,
                indices=correct_indices,
            ) is True

            # 2. Tampered higher degree
            tampered_deg_high = min(k, correct_degree + 1)
            if tampered_deg_high != correct_degree:
                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    total_source_blocks=k,
                    degree=tampered_deg_high,
                    indices=correct_indices,
                ) is False

            # 3. Tampered lower degree
            tampered_deg_low = max(1, correct_degree - 1)
            if tampered_deg_low != correct_degree:
                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    total_source_blocks=k,
                    degree=tampered_deg_low,
                    indices=correct_indices,
                ) is False

            # 4. Out-of-bounds degree (0 or > k)
            assert verify_droplet_seed_authenticity(
                droplet_seed=seed,
                total_source_blocks=k,
                degree=0,
                indices=correct_indices,
            ) is False

            assert verify_droplet_seed_authenticity(
                droplet_seed=seed,
                total_source_blocks=k,
                degree=k + 5,
                indices=correct_indices,
            ) is False

    def test_tampered_symbol_indices_with_valid_seed(self):
        """
        Adversary uses legitimate seed and legitimate degree, but swaps one or more indices.
        Verify verify_droplet_seed_authenticity detects index substitution in O(1).
        """
        k = 20
        root_hash = hashlib.sha3_256(b"indices_tamper_test").digest()
        seeds = derive_repair_seed_schedule(root_hash, b"nonce_idx_test", k, repair_count=50)

        for seed in seeds:
            rng = random.Random(seed)
            correct_degree = _sample_soliton_degree(k, rng)
            correct_indices = sorted(rng.sample(range(k), correct_degree))

            # Permute / substitute indices
            all_indices = set(range(k))
            unused_indices = list(all_indices - set(correct_indices))

            if unused_indices:
                tampered_indices = list(correct_indices)
                tampered_indices[0] = unused_indices[0]
                tampered_indices.sort()

                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    total_source_blocks=k,
                    degree=correct_degree,
                    indices=tampered_indices,
                ) is False

    def test_systematic_droplet_spoofing_attack(self):
        """
        Adversary sends fake systematic droplets (seed < K) with forged degrees or incorrect indices.
        """
        k = 8
        # Systematic packets must strictly have degree=1 and indices=[seed]
        for s in range(k):
            # Genuine systematic
            assert verify_droplet_seed_authenticity(
                droplet_seed=s,
                total_source_blocks=k,
                degree=1,
                indices=[s],
            ) is True

            # Forged degree > 1
            assert verify_droplet_seed_authenticity(
                droplet_seed=s,
                total_source_blocks=k,
                degree=2,
                indices=[s, (s + 1) % k],
            ) is False

            # Forged index pointing to a different symbol
            wrong_idx = (s + 1) % k
            assert verify_droplet_seed_authenticity(
                droplet_seed=s,
                total_source_blocks=k,
                degree=1,
                indices=[wrong_idx],
            ) is False

            # Empty indices
            assert verify_droplet_seed_authenticity(
                droplet_seed=s,
                total_source_blocks=k,
                degree=1,
                indices=[],
            ) is False

        # Negative seed
        assert verify_droplet_seed_authenticity(
            droplet_seed=-1,
            total_source_blocks=k,
            degree=1,
            indices=[0],
        ) is False

    def test_transport_channel_byzantine_pollution_flood(self):
        """
        Adversary floods TransportFountainChannel with 1000 corrupted / poisoned droplets (forged equations & malformed sizes).
        Verify all 1000 are rejected, 0 corrupt the Gaussian decoding buffer, and valid payload recovers cleanly.
        """
        payload = b"GENUINE_TFP_V4_SECURE_PAYLOAD_CONTENT_ACROSS_MESH_NETWORK" * 10  # 570 bytes
        symbol_size = 64
        root_hash = hashlib.sha3_256(payload).digest()
        session_nonce = b"flood_nonce_99"

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=session_nonce)
        droplets, k, orig_len = encoder.encode(payload, redundancy=0.5)

        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=session_nonce,
        )

        # 1. Flood with 500 Byzantine droplets with intentionally corrupted degrees/equations
        for i in range(500):
            fake_seed = 50000 + i
            rng = random.Random(fake_seed)
            correct_deg = _sample_soliton_degree(k, rng)
            correct_idx = sorted(rng.sample(range(k), correct_deg))
            # Adversary alters degree to inject invalid linear combination
            tampered_deg = (correct_deg % k) + 1
            if tampered_deg == correct_deg:
                tampered_deg = ((tampered_deg + 1) % k) + 1

            fake_d = FountainDroplet(
                seed=fake_seed,
                degree=tampered_deg,
                indices=correct_idx,
                payload=os.urandom(symbol_size),
            )
            assert channel.admit_droplet(fake_d) is False

        # 2. Flood with 500 malformed payload sizes
        for i in range(500):
            bad_len = symbol_size + ((i % 10) + 1)
            bad_len_d = FountainDroplet(
                seed=i,
                degree=1,
                indices=[i % k],
                payload=os.urandom(bad_len),
            )
            assert channel.admit_droplet(bad_len_d) is False

        assert len(channel.received_droplets) == 0
        assert channel.rejected_count == 1000

        # 3. Now admit legitimate droplets
        for d in droplets:
            admitted = channel.admit_droplet(d)
            assert admitted is True

        assert channel.can_decode() is True
        assert len(channel.received_droplets) == len(droplets)
        assert channel.decode() == payload

    def test_wire_format_binary_fuzzing(self):
        """
        Fuzz binary serialization and deserialization of FountainDroplet wire format.
        """
        symbol_size = 64
        droplet = FountainDroplet(
            seed=42,
            degree=3,
            indices=[0, 2, 5],
            payload=b"A" * symbol_size,
        )
        serialized = droplet.serialize()
        assert len(serialized) == 10 + (3 * 2) + symbol_size  # 10 header + 6 indices + 64 payload = 80 bytes

        # Clean roundtrip
        deserialized = FountainDroplet.deserialize(serialized, symbol_size=symbol_size)
        assert deserialized.seed == 42
        assert deserialized.degree == 3
        assert deserialized.indices == [0, 2, 5]
        assert deserialized.payload == b"A" * symbol_size

        # Fuzzing truncated wire bytes: verify unpack handles or raises expected struct error
        for trunc_len in range(0, 10):
            with pytest.raises(Exception):
                FountainDroplet.deserialize(serialized[:trunc_len], symbol_size=symbol_size)

        # Truncated index bytes
        with pytest.raises(Exception):
            FountainDroplet.deserialize(serialized[:12], symbol_size=symbol_size)


# ==============================================================================
# Suite 2: High Erasure Channel Stress (10% to 60% Loss Rates)
# ==============================================================================

class TestHighErasureStressChannel:
    """Stress tests verifying rateless fountain codec payload recovery under extreme packet loss."""

    @pytest.mark.parametrize("loss_rate", [0.10, 0.20, 0.30, 0.40, 0.50, 0.60])
    @pytest.mark.parametrize("payload_size", [256, 1024, 4096])
    def test_graduated_packet_erasure_recovery(self, loss_rate: float, payload_size: int):
        """
        Test graduated erasure channel from 10% to 60% packet drop.
        Transmitter emits a rateless fountain stream with deterministic repair droplets.
        Receiver collects arriving packets through the lossy channel and achieves 100% payload recovery.
        """
        symbol_size = 64
        raw_data = os.urandom(payload_size)
        root_hash = hashlib.sha3_256(raw_data).digest()
        nonce = f"erasure_test_{loss_rate}_{payload_size}".encode()

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=nonce)
        decoder = FountainDecoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=nonce)

        k = math.ceil(payload_size / symbol_size)
        # Redundancy scaled for channel erasure rate
        redundancy = max(4.0, (3.0 / (1.0 - loss_rate)))
        droplets, k_out, orig_len = encoder.encode(raw_data, redundancy=redundancy)
        assert k_out == k

        # Simulate independent random packet loss channel
        rng = random.Random(int(loss_rate * 1000) + payload_size)
        received: List[FountainDroplet] = []
        decoded = False

        for d in droplets:
            if rng.random() >= loss_rate:  # packet survived
                received.append(d)
                if len(received) >= k:
                    try:
                        recovered = decoder.decode(received, k=k, orig_len=orig_len)
                        assert recovered == raw_data
                        decoded = True
                        break
                    except ValueError:
                        # Need more repair droplets to reach full rank K
                        continue

        assert decoded is True, f"Failed to decode at loss_rate={loss_rate}, K={k}, received={len(received)}"

    def test_100_percent_systematic_loss_pure_repair_recovery(self):
        """
        Worst-case erasure scenario: 100% of systematic droplets (0..K-1) are dropped by the channel.
        Receiver receives ONLY deterministic repair droplets (seed >= K).
        Verify Gaussian elimination solves the linear system and recovers original payload.
        """
        symbol_size = 128
        raw_data = b"FOUNDATION_PROTOCOL_ZERO_SYSTEMATIC_SURVIVAL_STRESS_TEST_" * 16  # 912 bytes
        root_hash = hashlib.sha3_256(raw_data).digest()
        session_nonce = b"pure_repair_nonce_001"

        codec = FountainCodec(symbol_size=symbol_size, root_hash=root_hash, session_nonce=session_nonce)
        # Redundancy 4.0 -> K systematic + 4*K repair droplets = 5*K droplets
        droplets, k, orig_len = codec.encode(raw_data, redundancy=4.0)

        # Drop ALL systematic packets (0..k-1)
        pure_repair_droplets = droplets[k:]
        assert len(pure_repair_droplets) >= k
        assert all(d.seed >= k for d in pure_repair_droplets)

        # Accumulate repair droplets until rank K is achieved
        received = []
        decoded = False
        for d in pure_repair_droplets:
            received.append(d)
            if len(received) >= k:
                try:
                    recovered = codec.decode(received, k=k, orig_len=orig_len)
                    assert recovered == raw_data
                    decoded = True
                    break
                except ValueError:
                    continue

        assert decoded is True

    def test_burst_erasure_consecutive_block_loss(self):
        """
        Simulate burst erasure where consecutive blocks of packets are wiped out (e.g. RF fade).
        """
        symbol_size = 64
        raw_data = os.urandom(2048)  # 32 blocks
        root_hash = hashlib.sha3_256(raw_data).digest()

        codec = FountainCodec(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = codec.encode(raw_data, redundancy=2.0)
        assert k == 32
        assert len(droplets) == 96

        # Wipe out bursts: drop packets 5..20 (16 packets) and packets 40..55 (16 packets) = 32 dropped
        surviving = [d for idx, d in enumerate(droplets) if not (5 <= idx <= 20 or 40 <= idx <= 55)]
        assert len(surviving) == 96 - 32  # 64 packets

        recovered = codec.decode(surviving, k=k, orig_len=orig_len)
        assert recovered == raw_data

    def test_simultaneous_50_percent_loss_and_50_percent_byzantine_pollution(self):
        """
        Combined high-stress attack: 50% packet erasure + 50% Byzantine injected poison packets.
        TransportFountainChannel must filter out 100% of poison and reconstruct clean payload.
        """
        symbol_size = 64
        payload = b"CRITICAL_TFP_COMMAND_CONTROL_MISSION_DATA_UNDER_FIRE" * 12  # 636 bytes
        root_hash = hashlib.sha3_256(payload).digest()
        nonce = b"combat_channel_nonce"

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=nonce)
        droplets, k, orig_len = encoder.encode(payload, redundancy=4.0)

        # Channel setup
        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=nonce,
        )

        # 1. 50% packet loss on genuine droplets
        rng = random.Random(42)
        received_genuine = [d for d in droplets if rng.random() > 0.50]
        assert len(received_genuine) >= k

        # 2. Generate 50% Byzantine poisoned packets
        poison_packets = []
        for i in range(len(received_genuine)):
            # Poison type A: fake seed with random indices
            poison_packets.append(
                FountainDroplet(
                    seed=888888 + i,
                    degree=random.randint(1, k),
                    indices=[random.randint(0, k - 1)],
                    payload=os.urandom(symbol_size),
                )
            )

        # Interleave genuine and poison packets
        mixed_stream = []
        for g, p in zip(received_genuine, poison_packets):
            mixed_stream.append(p)
            mixed_stream.append(g)

        # Feed mixed stream to channel
        for d in mixed_stream:
            channel.admit_droplet(d)

        assert channel.rejected_count == len(poison_packets)
        assert channel.can_decode() is True
        assert channel.decode() == payload

    @pytest.mark.parametrize("sym_size", [16, 32, 128, 256, 512, 1024])
    def test_variable_symbol_sizes_under_40_percent_loss(self, sym_size: int):
        # Deterministic byte sequence matching test's deterministic specification
        raw_data = bytes((i * 31 + sym_size) % 256 for i in range(sym_size * 8 + 7))  # 9 blocks
        root = hashlib.sha3_256(raw_data).digest()

        codec = FountainCodec(symbol_size=sym_size, root_hash=root)
        droplets, k, orig_len = codec.encode(raw_data, redundancy=4.0)
        assert k == 9

        # Drop 40%
        rng = random.Random(sym_size)
        surviving = [d for d in droplets if rng.random() > 0.40]

        # Accumulate until decode
        received = []
        decoded = False
        for d in surviving:
            received.append(d)
            if len(received) >= k:
                try:
                    recovered = codec.decode(received, k=k, orig_len=orig_len)
                    assert recovered == raw_data
                    decoded = True
                    break
                except ValueError:
                    continue

        assert decoded is True


# ==============================================================================
# Suite 3: Seed Schedule Collision & Rollover Stress Tests
# ==============================================================================

class TestSeedScheduleCollisionAndRollover:
    """Stress tests for deterministic repair seed generation, collision resistance, and rollover."""

    def test_massive_seed_schedule_uniqueness_10k_seeds(self):
        """
        Derive 10,000 deterministic repair seeds for a large content transfer.
        Verify 0 intra-batch collisions, strict seed >= K invariant, and 32-bit integer compliance.
        """
        root_hash = hashlib.sha3_256(b"massive_10k_transfer_stream").digest()
        session_nonce = b"session_large_10k"
        k = 64
        repair_count = 10_000

        t0 = time.perf_counter()
        schedule = derive_repair_seed_schedule(root_hash, session_nonce, k, repair_count)
        t_elapsed = time.perf_counter() - t0

        assert len(schedule) == repair_count
        # All seeds >= k
        assert all(s >= k for s in schedule)
        # All seeds in uint32 bounds
        assert all(0 <= s <= 0xFFFFFFFF for s in schedule)

        # Verify uniqueness (zero collisions)
        unique_seeds = set(schedule)
        collision_count = repair_count - len(unique_seeds)
        assert collision_count == 0, f"Encountered {collision_count} seed collisions in 10k schedule"

        # Check generation throughput (should be fast)
        rate = repair_count / max(0.001, t_elapsed)
        assert rate > 10_000, f"Seed derivation throughput {rate:.0f} seeds/sec is too slow"

    def test_multi_session_orthogonality_and_cryptographic_independence(self):
        """
        Derive 50 distinct sessions with different RootHashes and Nonces (1,000 seeds each).
        Verify cross-session orthogonality and cryptographic separation.
        """
        k = 16
        num_sessions = 50
        seeds_per_session = 1000

        session_schedules: List[List[int]] = []
        for i in range(num_sessions):
            root = hashlib.sha3_256(f"session_root_{i}".encode()).digest()
            nonce = f"nonce_{i}".encode()
            sched = derive_repair_seed_schedule(root, nonce, k, seeds_per_session)
            session_schedules.append(sched)

        # Check that no two sessions produce identical schedules
        for i in range(num_sessions):
            for j in range(i + 1, num_sessions):
                assert session_schedules[i] != session_schedules[j], f"Session {i} and {j} produced identical seeds"

    def test_seed_rollover_near_large_k_bounds(self):
        """
        Test seed derivation when K is large (e.g. K = 100,000 source blocks).
        Verify arithmetic does not overflow or produce invalid seeds < K.
        """
        root_hash = hashlib.sha3_256(b"gigabyte_file_transfer").digest()
        large_k = 100_000
        count = 1000

        schedule = derive_repair_seed_schedule(root_hash, b"nonce_large_k", large_k, count)
        assert len(schedule) == count
        for seed in schedule:
            assert seed >= large_k
            assert seed <= 0xFFFFFFFF

    def test_empirical_soliton_degree_distribution_fidelity(self):
        """
        Empirically sample 10,000 soliton degrees for K=50.
        Verify that degree 1 and degree 2 are sampled with highest frequencies per Soliton distribution theory.
        """
        k = 50
        sample_count = 10_000
        root = hashlib.sha3_256(b"soliton_dist_manifest").digest()
        seeds = derive_repair_seed_schedule(root, b"dist_nonce", k, sample_count)

        degree_counts: Dict[int, int] = collections.defaultdict(int)
        for s in seeds:
            rng = random.Random(s)
            deg = _sample_soliton_degree(k, rng)
            assert 1 <= deg <= k
            degree_counts[deg] += 1

        # In Soliton distribution, degree 2 has highest weight (1 / (2*1) = 0.5)
        # Degree 1 has weight 1 / K = 0.02
        assert degree_counts[2] > degree_counts[1]
        assert degree_counts[2] > degree_counts[3]
        assert degree_counts[2] > degree_counts[10]

        # Degree 1, 2, 3 should account for the majority of repair droplets
        low_degree_total = degree_counts[1] + degree_counts[2] + degree_counts[3]
        fraction_low_degree = low_degree_total / sample_count
        assert fraction_low_degree > 0.50, f"Low degree fraction {fraction_low_degree} lower than expected"
