# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Content-Defined Chunking (CDC) using FastCDC (Gear hash).

Implements efficient content-defined chunking for deduplication and
delta encoding. Chunks are determined by content patterns rather than
fixed sizes, enabling better deduplication across similar files.

FastCDC uses Gear rolling hash with normalized masking for better
performance and chunk distribution compared to Rabin-Karp.

Usage:
    chunker = CDCChunker(min_chunk=4KB, max_chunk=64KB, avg_chunk=16KB)
    chunks = list(chunker.chunk_data(data))
    # Reconstruct
    reconstructed = b''.join(chunks)
"""

import hashlib
import random
from typing import Iterator, List, Optional


class FastCDC:
    """
    FastCDC implementation using Gear rolling hash.

    FastCDC uses Gear hash with normalized masking for efficient
    content-defined chunking. ~10x faster than Rabin-Karp with
    near-identical deduplication ratio.

    Reference: Xia et al., "FastCDC: A Fast and Efficient Content-Defined
    Chunking Approach for Data Deduplication", USENIX ATC 2016.
    """

    # Default parameters from FastCDC paper
    DEFAULT_WINDOW_SIZE = 64
    DEFAULT_MASK_BITS = 21
    DEFAULT_ZERO_PADDING = 5  # Enlarge sliding window for better distribution

    def __init__(
        self,
        min_chunk: int = 4096,
        max_chunk: int = 65536,
        expected_chunk: int = 16384,
        mask_bits: int = DEFAULT_MASK_BITS,
        zero_padding: int = DEFAULT_ZERO_PADDING,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ):
        """
        Initialize FastCDC chunker.

        Args:
            min_chunk: Minimum chunk size in bytes
            max_chunk: Maximum chunk size in bytes
            expected_chunk: Target average chunk size in bytes
            mask_bits: Number of bits for cut mask (higher = fewer cuts)
            zero_padding: Zero padding for normalized masking
            window_size: Rolling hash window size
        """
        self.min_chunk = min_chunk
        self.max_chunk = max_chunk
        self.expected_chunk = expected_chunk
        self.window_size = window_size
        self.zero_padding = zero_padding

        # Compute effective mask with zero padding
        self.base_mask = ((1 << mask_bits) - 1) << zero_padding

        # Generate deterministic Gear hash table
        self.gear_table = self._generate_gear_table(seed=0x9e3779b9)

    def _generate_gear_table(self, seed: int) -> tuple:
        """Generate deterministic Gear hash lookup table."""
        rng = random.Random(seed)
        return tuple(rng.getrandbits(64) for _ in range(256))

    def _gear_roll(self, fp: int, old_byte: int, new_byte: int) -> int:
        """
        O(1) Gear hash update.

        Gear hash: fp = (fp << 1) ^ G(new_byte) ^ G(old_byte) << n
        """
        return ((fp << 1) ^ self.gear_table[new_byte] ^ 
                (self.gear_table[old_byte] << self.window_size)) & ((1 << 64) - 1)

    def _normalized_mask(self, chunk_size: int) -> int:
        """
        Dynamic mask adjustment for normalized chunk distribution.

        Reduces mask bits for small chunks (more boundaries),
        increases for large chunks (fewer boundaries).
        """
        if chunk_size < self.expected_chunk // 2:
            return self.base_mask >> 2
        elif chunk_size > self.expected_chunk * 2:
            return self.base_mask << 1
        return self.base_mask

    def chunk(self, data: bytes) -> Iterator[bytes]:
        """
        Yield content-defined chunks using FastCDC.

        Args:
            data: Input data to chunk

        Yields:
            Chunks of data
        """
        if not data:
            return

        if len(data) <= self.min_chunk:
            yield data
            return

        offset = 0
        data_len = len(data)

        # Initialize fingerprint with first window
        fp = 0
        for i in range(min(self.window_size, data_len)):
            fp = (fp << 1) ^ self.gear_table[data[i]]
        fp &= ((1 << 64) - 1)

        for i, byte in enumerate(data):
            # Update rolling window after first window is processed
            if i >= self.window_size:
                old_byte = data[i - self.window_size]
                fp = self._gear_roll(fp, old_byte, byte)

            # Skip min_chunk enforcement (FastCDC optimization)
            if i - offset < self.min_chunk:
                continue

            # Boundary detection with normalized mask
            current_mask = self._normalized_mask(i - offset)
            if (fp & current_mask) == 0 or (i - offset) >= self.max_chunk:
                chunk_end = min(i, offset + self.max_chunk)
                chunk_data = data[offset:chunk_end]
                yield chunk_data
                offset = chunk_end
                # Reset fingerprint for next chunk
                fp = 0
                for j in range(min(self.window_size, data_len - offset)):
                    fp = (fp << 1) ^ self.gear_table[data[offset + j]]
                fp &= ((1 << 64) - 1)

        # Final chunk
        if offset < data_len:
            yield data[offset:]


class CDCChunker:
    """
    Content-Defined Chunker using FastCDC (Gear hash).

    Splits data into chunks based on content patterns using FastCDC
    algorithm for better performance and chunk distribution.

    Args:
        min_chunk: Minimum chunk size in bytes
        max_chunk: Maximum chunk size in bytes
        avg_chunk: Target average chunk size in bytes
    """

    # Default FastCDC parameters
    DEFAULT_AVG_CHUNK = 16384  # 16KB
    DEFAULT_MIN_CHUNK = 4096   # 4KB
    DEFAULT_MAX_CHUNK = 65536  # 64KB

    def __init__(
        self,
        min_chunk: int = DEFAULT_MIN_CHUNK,
        max_chunk: int = DEFAULT_MAX_CHUNK,
        avg_chunk: int = DEFAULT_AVG_CHUNK,
    ):
        """
        Initialize CDC chunker with FastCDC.

        Args:
            min_chunk: Minimum chunk size in bytes
            max_chunk: Maximum chunk size in bytes
            avg_chunk: Target average chunk size in bytes
        """
        if min_chunk >= max_chunk:
            raise ValueError("min_chunk must be less than max_chunk")
        if avg_chunk < min_chunk or avg_chunk > max_chunk:
            raise ValueError("avg_chunk must be between min_chunk and max_chunk")

        self.min_chunk = min_chunk
        self.max_chunk = max_chunk
        self.avg_chunk = avg_chunk

        # Initialize FastCDC with these parameters
        self.fastcdc = FastCDC(
            min_chunk=min_chunk,
            max_chunk=max_chunk,
            expected_chunk=avg_chunk,
        )

    def chunk_data(self, data: bytes) -> Iterator[bytes]:
        """
        Split data into content-defined chunks using FastCDC.

        Args:
            data: Input data to chunk

        Yields:
            Chunks of data
        """
        yield from self.fastcdc.chunk(data)

    def chunk_file(self, file_path: str, buffer_size: int = 65536) -> Iterator[bytes]:
        """
        Chunk a file without loading it entirely into memory.

        Args:
            file_path: Path to file to chunk
            buffer_size: Read buffer size

        Yields:
            Chunks of file data
        """
        with open(file_path, "rb") as f:
            buffer = b""
            while True:
                chunk = f.read(buffer_size)
                if not chunk:
                    break

                buffer += chunk

                # Process buffer for chunks
                while len(buffer) >= self.max_chunk:
                    # Find cut point in buffer
                    for chunk_data in self.chunk_data(buffer):
                        if len(chunk_data) <= len(buffer):
                            yield chunk_data
                            buffer = buffer[len(chunk_data) :]
                            break
                    else:
                        # No complete chunk found, need more data
                        break

            # Yield remaining data
            if buffer:
                yield from self.chunk_data(buffer)

    def get_chunk_hashes(self, data: bytes) -> List[str]:
        """
        Compute SHA-256 hashes for each chunk.

        Args:
            data: Input data to chunk

        Returns:
            List of chunk hashes
        """
        hashes = []
        for chunk in self.chunk_data(data):
            chunk_hash = hashlib.sha256(chunk).hexdigest()
            hashes.append(chunk_hash)
        return hashes

    def estimate_chunk_count(self, data_size: int) -> int:
        """
        Estimate number of chunks for given data size.

        Args:
            data_size: Size of data in bytes

        Returns:
            Estimated number of chunks
        """
        if data_size == 0:
            return 0
        return max(1, (data_size + self.avg_chunk - 1) // self.avg_chunk)


def create_fastcdc_chunker(
    min_chunk_kb: int = 4,
    max_chunk_kb: int = 64,
    avg_chunk_kb: int = 16,
) -> CDCChunker:
    """
    Create a FastCDC-style chunker with KB parameters.

    Convenience function matching FastCDC parameter naming.

    Args:
        min_chunk_kb: Minimum chunk size in KB
        max_chunk_kb: Maximum chunk size in KB
        avg_chunk_kb: Target average chunk size in KB

    Returns:
        Configured CDCChunker instance
    """
    return CDCChunker(
        min_chunk=min_chunk_kb * 1024,
        max_chunk=max_chunk_kb * 1024,
        avg_chunk=avg_chunk_kb * 1024,
    )


if __name__ == "__main__":
    # Demo usage
    print("=== FastCDC Chunking Demo ===\n")

    # Create chunker with FastCDC defaults
    chunker = create_fastcdc_chunker(min_chunk_kb=4, max_chunk_kb=64, avg_chunk_kb=16)

    # Test data with some repeated patterns
    test_data = b"The quick brown fox jumps over the lazy dog. " * 1000
    print(f"Test data size: {len(test_data)} bytes")

    # Chunk the data
    chunks = list(chunker.chunk_data(test_data))
    print(f"Number of chunks: {len(chunks)}")

    # Show chunk size distribution
    chunk_sizes = [len(c) for c in chunks]
    print(f"Min chunk size: {min(chunk_sizes)} bytes")
    print(f"Max chunk size: {max(chunk_sizes)} bytes")
    print(f"Avg chunk size: {sum(chunk_sizes) / len(chunk_sizes):.1f} bytes")

    # Verify reconstruction
    reconstructed = b"".join(chunks)
    assert reconstructed == test_data, "Reconstruction failed!"
    print("Reconstruction: OK")

    # Show chunk hashes
    print(f"\nFirst 5 chunk hashes:")
    hashes = chunker.get_chunk_hashes(test_data)
    for i, h in enumerate(hashes[:5]):
        print(f"  Chunk {i}: {h[:16]}...")

    # Estimate chunk count
    estimated = chunker.estimate_chunk_count(len(test_data))
    print(f"\nEstimated chunks: {estimated}")
    print(f"Actual chunks: {len(chunks)}")
