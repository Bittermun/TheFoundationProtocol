# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Vectorized Rateless Fountain Codec for TFP v4.0

Implements whole-payload vector Gaussian elimination over GF(2) and rateless
droplet generation, providing loss-tolerant recovery from any M >= K received droplets.
"""

from dataclasses import dataclass
import math
import random
import struct
from typing import Dict, List, Tuple


@dataclass
class FountainDroplet:
    """A single rateless fountain packet carrying encoded symbol data."""

    seed: int
    degree: int
    indices: List[int]
    payload: bytes

    def serialize(self) -> bytes:
        """Serialize droplet to compact binary wire format."""
        idx_bytes = struct.pack(f"<{len(self.indices)}H", *self.indices)
        header = struct.pack("<IIH", self.seed, self.degree, len(self.indices))
        return header + idx_bytes + self.payload

    @classmethod
    def deserialize(cls, data: bytes, symbol_size: int) -> "FountainDroplet":
        """Deserialize droplet from binary wire format."""
        seed, degree, num_idx = struct.unpack_from("<IIH", data, 0)
        offset = 10
        indices = list(struct.unpack_from(f"<{num_idx}H", data, offset))
        offset += num_idx * 2
        payload = data[offset:]
        return cls(seed=seed, degree=degree, indices=indices, payload=payload)


class FountainCodec:
    """Vectorized rateless fountain encoder and decoder."""

    def __init__(self, symbol_size: int = 256):
        if symbol_size < 16:
            raise ValueError(f"Symbol size must be at least 16 bytes: {symbol_size}")
        self.symbol_size = symbol_size

    def encode(self, data: bytes, redundancy: float = 0.50) -> Tuple[List[FountainDroplet], int, int]:
        """
        Encode data into rateless fountain droplets.
        Returns: (droplets, K_source_symbols, original_length)
        """
        if not data:
            return [], 0, 0

        orig_len = len(data)
        k = math.ceil(orig_len / self.symbol_size)

        # Pad data to multiple of symbol_size
        padded = data.ljust(k * self.symbol_size, b"\x00")
        source_symbols = [
            padded[i * self.symbol_size : (i + 1) * self.symbol_size]
            for i in range(k)
        ]

        total_droplets = max(k, math.ceil(k * (1.0 + redundancy)))
        droplets = []

        # Generate systematic droplets first (indices 0..k-1)
        for i in range(k):
            droplets.append(
                FountainDroplet(
                    seed=i,
                    degree=1,
                    indices=[i],
                    payload=source_symbols[i],
                )
            )

        # Generate repair droplets using robust soliton-like random distribution
        for seed in range(k, total_droplets):
            rng = random.Random(seed)  # nosec B311: Deterministic fountain PRNG
            degree = self._sample_degree(k, rng)
            indices = sorted(rng.sample(range(k), degree))

            # Vectorized XOR combination
            combined = bytearray(self.symbol_size)
            for idx in indices:
                sym = source_symbols[idx]
                for b in range(self.symbol_size):
                    combined[b] ^= sym[b]

            droplets.append(
                FountainDroplet(
                    seed=seed,
                    degree=degree,
                    indices=indices,
                    payload=bytes(combined),
                )
            )

        return droplets, k, orig_len

    @staticmethod
    def _sample_degree(k: int, rng: random.Random) -> int:
        """Sample degree distribution."""
        if k <= 2:
            return min(k, 1)
        # Robust Soliton degree sample
        weights = [1.0 / (d * (d - 1)) if d > 1 else 1.0 / k for d in range(1, k + 1)]
        total = sum(weights)
        probs = [w / total for w in weights]
        r = rng.random()
        cumulative = 0.0
        for d, p in enumerate(probs, start=1):
            cumulative += p
            if r <= cumulative:
                return min(k, max(1, d))
        return min(k, max(1, 2))

    def decode(
        self,
        droplets: List[FountainDroplet],
        k: int,
        orig_len: int,
    ) -> bytes:
        """
        Decode original payload using vectorized Gaussian elimination over GF(2).
        Requires at least K linearly independent droplets.
        """
        if len(droplets) < k:
            raise ValueError(f"Need at least {k} droplets to decode, got {len(droplets)}")

        # Build generator matrix and payload table
        matrix: List[bytearray] = []
        payloads: List[bytearray] = []

        for d in droplets:
            row = bytearray(k)
            for idx in d.indices:
                if idx < k:
                    row[idx] = 1
            matrix.append(row)
            payloads.append(bytearray(d.payload))

        num_rows = len(matrix)
        pivots: Dict[int, int] = {}  # col -> row

        # Forward elimination to reduced row echelon form over GF(2)
        current_row = 0
        for col in range(k):
            # Find pivot in this column
            pivot_row = None
            for r in range(current_row, num_rows):
                if matrix[r][col] == 1:
                    pivot_row = r
                    break

            if pivot_row is None:
                continue

            # Swap pivot row into current_row position
            matrix[current_row], matrix[pivot_row] = matrix[pivot_row], matrix[current_row]
            payloads[current_row], payloads[pivot_row] = payloads[pivot_row], payloads[current_row]

            # Eliminate all other rows with a 1 in this column
            for r in range(num_rows):
                if r != current_row and matrix[r][col] == 1:
                    # XOR row vectors in GF(2)
                    for c in range(k):
                        matrix[r][c] ^= matrix[current_row][c]
                    # Vectorized XOR on payload bytes
                    for b in range(self.symbol_size):
                        payloads[r][b] ^= payloads[current_row][b]

            pivots[col] = current_row
            current_row += 1
            if len(pivots) == k:
                break

        if len(pivots) < k:
            raise ValueError(
                f"Insufficient linearly independent droplets: rank {len(pivots)} < required {k}"
            )

        # Assemble original source symbols in order 0..k-1
        recovered = bytearray()
        for col in range(k):
            row_idx = pivots[col]
            recovered.extend(payloads[row_idx])

        return bytes(recovered[:orig_len])
