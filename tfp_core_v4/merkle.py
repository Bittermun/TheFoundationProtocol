# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
SHA3-256 Merkle Tree & Constant-Time Proof Verifier for TFP v4.0

Guarantees data integrity and prevents Byzantine poisoning attacks.
"""

import hashlib
import hmac
from typing import List, Tuple


def sha3_256(data: bytes) -> bytes:
    """Compute raw SHA3-256 digest."""
    return hashlib.sha3_256(data).digest()


class MerkleTree:
    """Complete binary Merkle tree with SHA3-256 hashing."""

    def __init__(self, leaves: List[bytes]):
        if not leaves:
            raise ValueError("Cannot build Merkle tree from empty leaf list")
        self.leaf_data = list(leaves)
        self.leaf_hashes = [sha3_256(leaf) for leaf in leaves]
        self.levels = [self.leaf_hashes]
        self._build()

    def _build(self):
        current = self.leaf_hashes
        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else left
                parent = sha3_256(left + right)
                next_level.append(parent)
            self.levels.append(next_level)
            current = next_level

    @property
    def root(self) -> bytes:
        """Root hash of the Merkle tree."""
        return self.levels[-1][0]

    @property
    def root_hex(self) -> str:
        """Hex-encoded root hash."""
        return self.root.hex()

    def get_proof(self, leaf_index: int) -> List[Tuple[bytes, str]]:
        """Generate audit proof path for a specific leaf index."""
        if not (0 <= leaf_index < len(self.leaf_hashes)):
            raise IndexError(f"Leaf index out of range: {leaf_index}")

        proof = []
        idx = leaf_index
        for level in self.levels[:-1]:
            is_right = (idx % 2 == 1)
            sibling_idx = idx - 1 if is_right else (idx + 1 if idx + 1 < len(level) else idx)
            direction = "left" if is_right else "right"
            proof.append((level[sibling_idx], direction))
            idx = idx // 2
        return proof


def verify_merkle_proof(
    leaf_data: bytes,
    proof: List[Tuple[bytes, str]],
    expected_root: bytes,
) -> bool:
    """
    Verify a Merkle proof in constant-time to eliminate timing side-channels.
    """
    current = sha3_256(leaf_data)
    for sibling_hash, direction in proof:
        if direction == "left":
            current = sha3_256(sibling_hash + current)
        else:
            current = sha3_256(current + sibling_hash)
    return hmac.compare_digest(current, expected_root)
