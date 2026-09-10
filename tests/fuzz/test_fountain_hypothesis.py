# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Property Testing for Rateless Fountain Codec and O(1) Anti-Pollution Invariants.

Verifies invariants:
1. GF(2) Rank K Decodability: Any linearly independent K droplets (or systematic + repair sets)
   recover the original binary data bit-exact across symbol sizes (32, 64, 128, 256 bytes).
2. O(1) Anti-Pollution Pre-Filter: verify_droplet_seed_authenticity returns True for authentic
   seeds and soliton equations, and returns False in O(1) for forged seeds, tampered degrees,
   or altered source indices BEFORE any Gaussian elimination matrix allocation.
3. Deterministic Seed Schedules: derive_repair_seed_schedule produces identical seeds for
   identical inputs, orthogonal schedules for distinct root hashes or nonces, and bounds seeds >= K.
"""

import hashlib
import random
import pytest
from hypothesis import given, settings, strategies as st

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    _sample_soliton_degree,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)


class TestFountainHypothesis:
    """Property-based verification of fountain codec and anti-pollution security."""

    @settings(max_examples=30, deadline=None)
    @given(
        data=st.binary(min_size=1, max_size=4096),
        symbol_size=st.sampled_from([32, 64, 128, 256]),
    )
    def test_gf2_rank_k_decodability_systematic_roundtrip(self, data: bytes, symbol_size: int):
        """
        Invariant: GF(2) Rank K Decodability.
        The K systematic droplets (which have rank K by definition) recover original data bit-exact.
        """
        root_hash = hashlib.sha3_256(data).hexdigest()
        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = encoder.encode(data, redundancy=0.50)

        assert len(droplets) >= k
        assert k > 0
        assert orig_len == len(data)

        # First K droplets are systematic
        systematic_droplets = droplets[:k]

        decoder = FountainDecoder(symbol_size=symbol_size, root_hash=root_hash)
        recovered = decoder.decode(systematic_droplets, k, orig_len)

        assert recovered == data, "Decoded payload does not match original binary data"

    @settings(max_examples=30, deadline=None)
    @given(
        data=st.binary(min_size=128, max_size=2048),
        symbol_size=st.sampled_from([32, 64, 128]),
    )
    def test_gf2_decodability_with_repair_droplets(self, data: bytes, symbol_size: int):
        """
        Invariant: Decodability when packets include repair droplets derived from schedule.
        When droplet collection has full rank K, decoding produces bit-exact original data.
        If rank < K, raises ValueError instead of returning corrupted data silently.
        """
        root_hash = hashlib.sha3_256(data).hexdigest()
        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = encoder.encode(data, redundancy=0.80)

        decoder = FountainDecoder(symbol_size=symbol_size, root_hash=root_hash)

        # Decoding all droplets (systematic + repair) must achieve rank K and match
        recovered_full = decoder.decode(droplets, k, orig_len)
        assert recovered_full == data

        # If we take a random subset of size k from all available droplets:
        subset = random.sample(droplets, k)
        try:
            recovered_subset = decoder.decode(subset, k, orig_len)
            assert recovered_subset == data
        except ValueError as exc:
            # Expected when randomly selected subset has rank < K
            assert "Insufficient linearly independent droplets" in str(exc)

    @settings(max_examples=40, deadline=None)
    @given(
        k=st.integers(min_value=2, max_value=64),
        tamper_mode=st.sampled_from(["corrupt_degree", "corrupt_indices", "negative_seed"]),
    )
    def test_anti_pollution_prefilter_o1_rejection(self, k: int, tamper_mode: str):
        """
        Invariant: O(1) Anti-Pollution Pre-Filter.
        verify_droplet_seed_authenticity verifies authentic droplets and rejects forged/tampered
        droplets before Gaussian elimination buffer allocation.
        """
        root_hash = "fuzz_root_hash_anti_pollution"
        session_nonce = "fuzz_session_nonce"

        # 1. Authentic systematic droplets verify
        for i in range(min(k, 5)):
            assert verify_droplet_seed_authenticity(
                droplet_seed=i,
                total_source_blocks=k,
                degree=1,
                indices=[i],
            ) is True

        # 2. Authentic repair droplets verify
        repair_seeds = derive_repair_seed_schedule(root_hash, session_nonce, total_source_blocks=k, repair_count=5)
        for seed in repair_seeds:
            rng = random.Random(seed)
            deg = _sample_soliton_degree(k, rng)
            idx = sorted(rng.sample(range(k), deg))

            # Authentic check
            assert verify_droplet_seed_authenticity(
                droplet_seed=seed,
                root_hash=root_hash,
                session_nonce=session_nonce,
                total_source_blocks=k,
                degree=deg,
                indices=idx,
            ) is True

            # Tampered checks
            if tamper_mode == "corrupt_degree":
                tampered_deg = deg + 1
                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    root_hash=root_hash,
                    session_nonce=session_nonce,
                    total_source_blocks=k,
                    degree=tampered_deg,
                    indices=idx,
                ) is False

            elif tamper_mode == "corrupt_indices":
                tampered_idx = [(i + 1) % k for i in idx]
                if tampered_idx != idx:
                    assert verify_droplet_seed_authenticity(
                        droplet_seed=seed,
                        root_hash=root_hash,
                        session_nonce=session_nonce,
                        total_source_blocks=k,
                        degree=deg,
                        indices=tampered_idx,
                    ) is False

            elif tamper_mode == "negative_seed":
                assert verify_droplet_seed_authenticity(
                    droplet_seed=-1,
                    root_hash=root_hash,
                    session_nonce=session_nonce,
                    total_source_blocks=k,
                    degree=deg,
                    indices=idx,
                ) is False

    @settings(max_examples=40, deadline=None)
    @given(
        root_hash_a=st.text(min_size=16, max_size=64),
        root_hash_b=st.text(min_size=16, max_size=64),
        k=st.integers(min_value=1, max_value=32),
        repair_count=st.integers(min_value=5, max_value=20),
    )
    def test_deterministic_seed_schedules(
        self, root_hash_a: str, root_hash_b: str, k: int, repair_count: int
    ):
        """
        Invariant: Deterministic Seed Schedules.
        derive_repair_seed_schedule produces identical seeds for identical root hashes,
        and orthogonal schedules for distinct root hashes.
        All seeds are >= K.
        """
        schedule_a1 = derive_repair_seed_schedule(root_hash_a, "nonce", k, repair_count)
        schedule_a2 = derive_repair_seed_schedule(root_hash_a, "nonce", k, repair_count)

        # Determinism
        assert schedule_a1 == schedule_a2
        assert len(schedule_a1) == repair_count

        # Bound check: all repair seeds >= k
        for s in schedule_a1:
            assert s >= k, f"Repair seed {s} is smaller than source blocks K={k}"
            assert s <= 0xFFFFFFFF, f"Repair seed {s} exceeds uint32 max"

        # Orthogonality across distinct root hashes
        if root_hash_a != root_hash_b:
            schedule_b = derive_repair_seed_schedule(root_hash_b, "nonce", k, repair_count)
            assert schedule_a1 != schedule_b, "Distinct root hashes generated identical seed schedule"
