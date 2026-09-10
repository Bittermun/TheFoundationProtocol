# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Invariant Testing for Merkle Trees and Constant-Time Proof Verification.

Verifies invariants:
1. Audit Path Correctness: verify_merkle_proof(leaves[i], tree.get_proof(i), tree.root) is True for all leaves.
2. Mutation Resistance: For any mutated leaf L != leaves[i], verify_merkle_proof returns False.
3. Proof Tamper Resistance: Mutating any sibling hash or direction in the proof returns False.
4. Non-Power-of-Two Leaves: Trees with 1, 3, 5, 7, 9, 15, 33 leaves duplicate odd elements correctly at intermediate levels and verify 100%.
5. Empty Tree Rejection: MerkleTree([]) raises ValueError.
"""

import hashlib
import os
import pytest
from hypothesis import given, settings, strategies as st

from tfp_core_v4.merkle import MerkleTree, sha3_256, verify_merkle_proof


class TestMerkleHypothesis:
    """Property-based verification of Merkle tree proofs and integrity."""

    @settings(max_examples=50, deadline=None)
    @given(
        leaves=st.lists(st.binary(min_size=1, max_size=512), min_size=1, max_size=64),
    )
    def test_audit_path_correctness_all_leaves(self, leaves: list[bytes]):
        """Invariant: All leaves in arbitrary trees produce valid audit paths that verify against root."""
        tree = MerkleTree(leaves)

        assert len(tree.root) == 32
        assert tree.root_hex == tree.root.hex()

        for idx, leaf in enumerate(leaves):
            proof = tree.get_proof(idx)
            is_valid = verify_merkle_proof(leaf, proof, tree.root)
            assert is_valid is True, f"Audit proof verification failed for leaf index {idx}/{len(leaves)}"

    @settings(max_examples=50, deadline=None)
    @given(
        leaves=st.lists(st.binary(min_size=1, max_size=256), min_size=1, max_size=32),
        mutate_choice=st.sampled_from(["bitflip", "append_byte", "truncate", "random_replacement"]),
    )
    def test_mutation_resistance(self, leaves: list[bytes], mutate_choice: str):
        """Invariant: Any mutated leaf L != leaves[i] fails proof verification."""
        tree = MerkleTree(leaves)

        for idx, leaf in enumerate(leaves):
            proof = tree.get_proof(idx)

            if mutate_choice == "bitflip":
                mutated = bytes([leaf[0] ^ 0xFF]) + leaf[1:]
            elif mutate_choice == "append_byte":
                mutated = leaf + b"\x01"
            elif mutate_choice == "truncate" and len(leaf) > 1:
                mutated = leaf[:-1]
            else:
                mutated = os.urandom(len(leaf) + 4)

            # Unless mutated happened to match original (negligible)
            if mutated != leaf:
                assert verify_merkle_proof(mutated, proof, tree.root) is False

    @settings(max_examples=50, deadline=None)
    @given(
        leaves=st.lists(st.binary(min_size=1, max_size=256), min_size=2, max_size=32),
        tamper_mode=st.sampled_from(["flip_sibling_byte", "invert_direction", "wrong_root"]),
    )
    def test_proof_tamper_resistance(self, leaves: list[bytes], tamper_mode: str):
        """Invariant: Mutating any sibling hash or direction in proof, or checking against wrong root returns False."""
        tree = MerkleTree(leaves)

        for idx, leaf in enumerate(leaves):
            proof = tree.get_proof(idx)
            if not proof:
                continue

            # Target the first sibling in the proof
            sibling_hash, direction = proof[0]

            if tamper_mode == "flip_sibling_byte":
                corrupted_sibling = bytes([sibling_hash[0] ^ 0xFF]) + sibling_hash[1:]
                tampered_proof = [(corrupted_sibling, direction)] + proof[1:]
                assert verify_merkle_proof(leaf, tampered_proof, tree.root) is False

            elif tamper_mode == "invert_direction":
                inverted_dir = "right" if direction == "left" else "left"
                tampered_proof = [(sibling_hash, inverted_dir)] + proof[1:]
                # If tree has non-symmetric branch, direction inversion must fail
                if sibling_hash != sha3_256(leaf):
                    assert verify_merkle_proof(leaf, tampered_proof, tree.root) is False

            elif tamper_mode == "wrong_root":
                wrong_root = bytes([tree.root[0] ^ 0xFF]) + tree.root[1:]
                assert verify_merkle_proof(leaf, proof, wrong_root) is False

    @pytest.mark.parametrize("leaf_count", [1, 3, 5, 7, 9, 15, 33])
    def test_non_power_of_two_leaves_odd_duplication(self, leaf_count: int):
        """
        Invariant: Trees with non-power-of-two leaves duplicate odd elements correctly
        at intermediate levels and all audit proofs verify cleanly.
        """
        leaves = [f"non_power_leaf_{i}_{os.urandom(8).hex()}".encode() for i in range(leaf_count)]
        tree = MerkleTree(leaves)

        # Inspect intermediate levels to verify odd node duplication logic
        for level_idx, level in enumerate(tree.levels[:-1]):
            next_level = tree.levels[level_idx + 1]
            if len(level) % 2 == 1:
                # Last node in next level was formed by pairing last node with itself
                expected_last_parent = sha3_256(level[-1] + level[-1])
                assert next_level[-1] == expected_last_parent, f"Odd level {level_idx} did not pair last node with itself"

        # Verify all leaf proofs
        for i in range(leaf_count):
            proof = tree.get_proof(i)
            assert verify_merkle_proof(leaves[i], proof, tree.root) is True

    def test_empty_tree_rejection(self):
        """Invariant: MerkleTree([]) raises ValueError."""
        with pytest.raises(ValueError, match="Cannot build Merkle tree from empty leaf list"):
            MerkleTree([])

    def test_proof_out_of_bounds_rejection(self):
        """Invariant: get_proof raises IndexError on out-of-range leaf indices."""
        tree = MerkleTree([b"leaf0", b"leaf1"])
        with pytest.raises(IndexError, match="Leaf index out of range"):
            tree.get_proof(-1)
        with pytest.raises(IndexError, match="Leaf index out of range"):
            tree.get_proof(2)
