# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Property-Based Testing for FastCDC (Content-Defined Chunking).

Verifies invariants:
1. Concatenation Identity: b"".join(chunker.chunk(data)) == data across arbitrary binary inputs.
2. Bound Invariant: min_size <= len(c) <= max_size for non-terminal chunks, and 0 < len(c) <= max_size for final chunk.
3. Deterministic Assembly: chunker.assemble(recipe, chunk_map) == data.
4. Tamper Detection: Corrupting any chunk hash, length, or payload in chunk_map raises ValueError or KeyError, never returns corrupt data silently.
5. Boundary-Shift Resistance: Localized insertion modifies at most O(1) chunks; downstream chunks resynchronize identically.
"""

import hashlib
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe


class TestFastCDCHypothesis:
    """Property-based verification of Content-Defined Chunking."""

    @settings(max_examples=50, deadline=None)
    @given(
        data=st.binary(min_size=0, max_size=100_000),
        min_size=st.integers(min_value=64, max_value=512),
        multiplier=st.integers(min_value=2, max_value=4),
    )
    def test_concatenation_identity_and_bounds(self, data: bytes, min_size: int, multiplier: int):
        """Invariant: Concatenation Identity and Min/Max Bound Invariant."""
        target_size = min_size * multiplier
        max_size = target_size * 2
        chunker = ContentDefinedChunker(min_size=min_size, max_size=max_size, target_size=target_size)

        chunks = chunker.chunk(data)

        # a) Concatenation identity
        assert b"".join(chunks) == data

        # b) Bound invariant
        if not data:
            assert chunks == []
            return

        if len(chunks) == 1:
            # Single chunk might be smaller than min_size if total data <= min_size
            if len(data) <= min_size:
                assert len(chunks[0]) == len(data)
            else:
                assert min_size <= len(chunks[0]) <= max_size
        else:
            # Non-terminal chunks must strictly respect [min_size, max_size]
            for c in chunks[:-1]:
                assert min_size <= len(c) <= max_size, f"Non-terminal chunk size {len(c)} outside [{min_size}, {max_size}]"

            # Final chunk must satisfy 0 < len(c) <= max_size
            final_len = len(chunks[-1])
            assert 0 < final_len <= max_size, f"Terminal chunk size {final_len} outside (0, {max_size}]"

    @settings(max_examples=50, deadline=None)
    @given(
        data=st.binary(min_size=1, max_size=50_000),
        min_size=st.integers(min_value=128, max_value=256),
    )
    def test_deterministic_recipe_and_assembly(self, data: bytes, min_size: int):
        """Invariant: Deterministic Recipe Generation and Bit-Exact Assembly."""
        chunker = ContentDefinedChunker(min_size=min_size, max_size=min_size * 4, target_size=min_size * 2)

        recipe1, chunks1 = chunker.create_recipe(data)
        recipe2, chunks2 = chunker.create_recipe(data)

        # Determinism invariant
        assert recipe1.root_hash == recipe2.root_hash
        assert recipe1.chunk_hashes == recipe2.chunk_hashes
        assert recipe1.chunk_sizes == recipe2.chunk_sizes
        assert chunks1 == chunks2

        # Build valid chunk map
        chunk_map = {h: c for h, c in zip(recipe1.chunk_hashes, chunks1)}

        # Bit-exact assembly
        assembled = chunker.assemble(recipe1, chunk_map)
        assert assembled == data

    @settings(max_examples=40, deadline=None)
    @given(
        data=st.binary(min_size=512, max_size=30_000),
        corrupt_mode=st.sampled_from(["payload_bitflip", "size_mismatch", "missing_key", "tampered_hash_key"]),
    )
    def test_tamper_detection(self, data: bytes, corrupt_mode: str):
        """Invariant: Tamper Detection raises ValueError or KeyError on any corruption."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        recipe, chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, chunks)}

        # Pick the first chunk to corrupt
        target_hash = recipe.chunk_hashes[0]
        orig_chunk = chunk_map[target_hash]

        if corrupt_mode == "payload_bitflip":
            # Flip the first byte of payload
            corrupted = bytes([orig_chunk[0] ^ 0xFF]) + orig_chunk[1:]
            chunk_map[target_hash] = corrupted
            with pytest.raises(ValueError, match="hash mismatch"):
                chunker.assemble(recipe, chunk_map)

        elif corrupt_mode == "size_mismatch":
            # Truncate or append one byte
            corrupted = orig_chunk[:-1] if len(orig_chunk) > 1 else orig_chunk + b"\x00"
            chunk_map[target_hash] = corrupted
            with pytest.raises(ValueError, match="size mismatch"):
                chunker.assemble(recipe, chunk_map)

        elif corrupt_mode == "missing_key":
            del chunk_map[target_hash]
            with pytest.raises(KeyError, match="Missing required chunk"):
                chunker.assemble(recipe, chunk_map)

        elif corrupt_mode == "tampered_hash_key":
            del chunk_map[target_hash]
            fake_hash = hashlib.sha3_256(b"fake").hexdigest()
            chunk_map[fake_hash] = orig_chunk
            with pytest.raises(KeyError, match="Missing required chunk"):
                chunker.assemble(recipe, chunk_map)

    @settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @given(
        prefix=st.binary(min_size=256, max_size=1024),
        suffix=st.binary(min_size=1024, max_size=3072),
        insertion=st.binary(min_size=1, max_size=64),
    )
    def test_boundary_shift_resistance(self, prefix: bytes, suffix: bytes, insertion: bytes):
        """
        Invariant: Localized insertion modifies at most O(1) chunks.
        Subsequent downstream chunks resynchronize and maintain identical hashes.
        """
        chunker = ContentDefinedChunker(min_size=64, max_size=256, target_size=128)

        data_orig = prefix + suffix
        data_mod = prefix + insertion + suffix

        chunks_orig = chunker.chunk(data_orig)
        chunks_mod = chunker.chunk(data_mod)

        # Set of chunk hashes
        hashes_orig = [hashlib.sha3_256(c).hexdigest() for c in chunks_orig]
        hashes_mod = [hashlib.sha3_256(c).hexdigest() for c in chunks_mod]

        # Calculate symmetric difference: non-shared chunks
        set_orig = set(hashes_orig)
        set_mod = set(hashes_mod)

        diff_orig = [h for h in hashes_orig if h not in set_mod]
        diff_mod = [h for h in hashes_mod if h not in set_orig]

        # In FastCDC, a local mutation causes boundary shift in at most O(1) chunks before resync
        assert len(diff_orig) <= 8, f"Too many modified chunks in orig: {len(diff_orig)}"
        assert len(diff_mod) <= 8, f"Too many modified chunks in mod: {len(diff_mod)}"

        # At least one shared downstream chunk must exist in the large suffix
        shared = set_orig.intersection(set_mod)
        assert len(shared) >= 1, "Downstream chunks failed to resynchronize"
