"""
Bloom Filter Implementation for TFP Metadata Compression

Provides space-efficient probabilistic set membership testing
for tag-based content discovery.

Parameters tuned for:
- 10,000 entries capacity
- <1% false positive rate
- 7 hash functions (optimal)
"""

import hashlib
import math
from typing import List, Union


class BloomFilter:
    """
    A space-efficient probabilistic data structure for set membership testing.

    Attributes:
        size_bits: Total number of bits in the filter
        hash_count: Number of hash functions to use
        bit_array: Internal bit storage as bytearray
        count: Number of items added (approximate)
    """

    def __init__(self, size_bits: int = 10000, hash_count: int = 7, seed: int = 42):
        """
        Initialize a Bloom filter.

        Args:
            size_bits: Number of bits in the filter (default 10K for ~1% FPR at 10K items)
            hash_count: Number of hash functions (default 7, optimal for 10K/10K)
            seed: Seed for hash function variation
        """
        if size_bits <= 0:
            raise ValueError("size_bits must be positive")
        if hash_count <= 0:
            raise ValueError("hash_count must be positive")

        self.size_bits = size_bits
        self.hash_count = hash_count
        self.seed = seed
        # Calculate byte array size (round up to nearest byte)
        self.byte_size = (size_bits + 7) // 8
        self.bit_array = bytearray(self.byte_size)
        self.count = 0

    def _hashes(self, item: bytes) -> List[int]:
        """
        Generate multiple hash values for an item using double hashing technique.

        Uses h(i) = (h1 + i * h2) mod m where:
        - h1 = SHA3(item + seed)
        - h2 = SHA3(item + seed + 1)

        Args:
            item: Bytes to hash

        Returns:
            List of bit positions (indices)
        """
        # Two base hashes for double hashing
        h1 = int.from_bytes(
            hashlib.sha3_256(item + self.seed.to_bytes(4, "big")).digest()[:8], "big"
        )
        h2 = int.from_bytes(
            hashlib.sha3_256(item + (self.seed + 1).to_bytes(4, "big")).digest()[:8],
            "big",
        )

        # Generate hash_count positions using linear combination
        positions = []
        for i in range(self.hash_count):
            pos = (h1 + i * h2) % self.size_bits
            positions.append(pos)

        return positions

    def add(self, item: Union[bytes, str]) -> None:
        """
        Add an item to the Bloom filter.

        Args:
            item: Item to add (will be encoded to bytes if string)
        """
        if isinstance(item, str):
            item = item.encode("utf-8")

        positions = self._hashes(item)
        for pos in positions:
            byte_idx = pos // 8
            bit_idx = pos % 8
            self.bit_array[byte_idx] |= 1 << bit_idx

        self.count += 1

    def contains(self, item: Union[bytes, str]) -> bool:
        """
        Test if an item might be in the set.

        Note: May return false positives but never false negatives.

        Args:
            item: Item to test (will be encoded to bytes if string)

        Returns:
            True if item might be in set, False if definitely not
        """
        if isinstance(item, str):
            item = item.encode("utf-8")

        positions = self._hashes(item)
        for pos in positions:
            byte_idx = pos // 8
            bit_idx = pos % 8
            if not (self.bit_array[byte_idx] & (1 << bit_idx)):
                return False

        return True

    def serialize(self) -> bytes:
        """
        Serialize the Bloom filter to bytes for transmission.

        Format: [size_bits (4 bytes)] [hash_count (1 byte)] [seed (4 bytes)]
                [count (4 bytes)] [bit_array (variable)]

        Returns:
            Serialized bytes
        """
        header = (
            self.size_bits.to_bytes(4, "big")
            + self.hash_count.to_bytes(1, "big")
            + self.seed.to_bytes(4, "big")
            + self.count.to_bytes(4, "big")
        )
        return header + bytes(self.bit_array)

    @classmethod
    def deserialize(cls, data: bytes) -> "BloomFilter":
        """
        Deserialize a Bloom filter from bytes.

        Args:
            data: Serialized bytes

        Returns:
            Deserialized BloomFilter instance
        """
        if len(data) < 13:
            raise ValueError("Data too short for Bloom filter header")

        size_bits = int.from_bytes(data[0:4], "big")
        hash_count = data[4]
        seed = int.from_bytes(data[5:9], "big")
        count = int.from_bytes(data[9:13], "big")

        bf = cls(size_bits=size_bits, hash_count=hash_count, seed=seed)
        bf.bit_array = bytearray(data[13:])
        bf.count = count

        # Validate byte array size
        expected_byte_size = (size_bits + 7) // 8
        if len(bf.bit_array) != expected_byte_size:
            raise ValueError(
                f"Byte array size mismatch: expected {expected_byte_size}, got {len(bf.bit_array)}"
            )

        return bf

    def estimated_false_positive_rate(self) -> float:
        """
        Estimate the current false positive rate.

        Formula: (1 - e^(-kn/m))^k where:
        - k = hash_count
        - n = count (items added)
        - m = size_bits

        Returns:
            Estimated false positive probability (0.0 to 1.0)
        """
        if self.count == 0:
            return 0.0

        k = self.hash_count
        n = self.count
        m = self.size_bits

        # Avoid division by zero
        if m == 0:
            return 1.0

        exponent = -k * n / m
        return (1 - math.exp(exponent)) ** k

    def clear(self) -> None:
        """Clear all bits and reset count."""
        self.bit_array = bytearray(self.byte_size)
        self.count = 0

    def union(self, other: "BloomFilter") -> "BloomFilter":
        """
        Create a new Bloom filter that is the union of this and another.

        Both filters must have the same parameters.

        Args:
            other: Another BloomFilter with same size_bits, hash_count, seed

        Returns:
            New BloomFilter representing union

        Raises:
            ValueError: If parameters don't match
        """
        if (
            self.size_bits != other.size_bits
            or self.hash_count != other.hash_count
            or self.seed != other.seed
        ):
            raise ValueError("Bloom filter parameters must match for union")

        result = BloomFilter(
            size_bits=self.size_bits, hash_count=self.hash_count, seed=self.seed
        )
        result.bit_array = bytearray(
            a | b for a, b in zip(self.bit_array, other.bit_array)
        )
        result.count = max(self.count, other.count)  # Approximate

        return result

    def __repr__(self) -> str:
        return (
            f"BloomFilter(size_bits={self.size_bits}, hash_count={self.hash_count}, "
            f"count={self.count}, fpr={self.estimated_false_positive_rate():.4f})"
        )

    def __len__(self) -> int:
        return self.count

    @staticmethod
    def optimal_size(n: int, p: float) -> int:
        """
        Calculate optimal Bloom filter size for given capacity and false positive rate.

        Formula: m = -(n * ln(p)) / (ln(2)^2)

        Args:
            n: Expected number of items
            p: Desired false positive rate (e.g., 0.01 for 1%)

        Returns:
            Optimal number of bits
        """
        if n <= 0:
            raise ValueError("n must be positive")
        if not (0 < p < 1):
            raise ValueError("p must be between 0 and 1")

        return int(-(n * math.log(p)) / (math.log(2) ** 2))

    @staticmethod
    def optimal_hash_count(m: int, n: int) -> int:
        """
        Calculate optimal number of hash functions.

        Formula: k = (m/n) * ln(2)

        Args:
            m: Number of bits
            n: Expected number of items

        Returns:
            Optimal number of hash functions (minimum 1)
        """
        if n <= 0:
            return 1
        return max(1, int((m / n) * math.log(2)))
