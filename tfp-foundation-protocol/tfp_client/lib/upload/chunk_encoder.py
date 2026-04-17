# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
ChunkEncoder - RaptorQ erasure coding for parallel chunk uploads.

Integrates the RealRaptorQAdapter with the ChunkUploader to provide
fault-tolerant parallel uploads with erasure coding redundancy.

Usage:
    encoder = ChunkEncoder()
    encoded_chunks = encoder.encode_for_upload(data, redundancy=0.1)
    # Upload encoded chunks using ChunkUploader
    decoded_data = encoder.decode_from_chunks(received_chunks)
"""

import logging
from typing import List, Optional

from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter

logger = logging.getLogger(__name__)


class ChunkEncoder:
    """
    Encodes data into erasure-coded chunks for fault-tolerant parallel uploads.

    Uses RaptorQ-compatible systematic erasure coding to generate redundant
    shards that can recover the original data from any subset of chunks.

    Args:
        chunk_size: Size of each chunk in bytes (default: 256KB)
        redundancy: Fraction of redundant chunks to generate (default: 0.1 = 10%)
    """

    def __init__(
        self,
        chunk_size: int = 262144,  # 256KB default
        redundancy: float = 0.1,
    ):
        self._chunk_size = chunk_size
        self._redundancy = redundancy
        self._adapter = RealRaptorQAdapter(shard_size=chunk_size)

    def encode_for_upload(
        self, data: bytes, redundancy: Optional[float] = None
    ) -> List[bytes]:
        """
        Encode data into erasure-coded chunks for upload.

        Args:
            data: Raw bytes to encode
            redundancy: Override default redundancy fraction

        Returns:
            List of encoded chunk bytes (includes redundancy)
        """
        if not data:
            raise ValueError("Cannot encode empty data")

        actual_redundancy = redundancy if redundancy is not None else self._redundancy
        encoded_shards = self._adapter.encode(data, redundancy=actual_redundancy)

        logger.info(
            "Encoded %d bytes into %d shards (redundancy=%.2f)",
            len(data),
            len(encoded_shards),
            actual_redundancy,
        )

        return encoded_shards

    def decode_from_chunks(self, chunks: List[bytes], k: Optional[int] = None) -> bytes:
        """
        Decode data from received erasure-coded chunks.

        Args:
            chunks: List of received chunk bytes
            k: Expected number of source chunks (auto-detected if not provided)

        Returns:
            Decoded original data bytes
        """
        if not chunks:
            raise ValueError("No chunks to decode")

        decoded_data = self._adapter.decode(chunks, k=k)

        logger.info(
            "Decoded %d bytes from %d chunks",
            len(decoded_data),
            len(chunks),
        )

        return decoded_data

    def estimate_chunk_count(
        self, data_size: int, redundancy: Optional[float] = None
    ) -> int:
        """
        Estimate the number of chunks that will be generated for a given data size.

        Args:
            data_size: Size of data in bytes
            redundancy: Override default redundancy fraction

        Returns:
            Estimated number of chunks (including redundancy)
        """
        actual_redundancy = redundancy if redundancy is not None else self._redundancy
        k = (data_size + self._chunk_size - 1) // self._chunk_size  # Ceiling division
        n_repair = max(1, int(k * actual_redundancy) + 1)
        return k + n_repair

    def get_min_chunks_to_recover(
        self, chunk_count: int, redundancy: Optional[float] = None
    ) -> int:
        """
        Calculate minimum number of chunks needed to recover the original data.

        Args:
            chunk_count: Total number of chunks generated
            redundancy: Redundancy fraction used

        Returns:
            Minimum number of chunks needed for recovery
        """
        actual_redundancy = redundancy if redundancy is not None else self._redundancy
        # If we have total chunks = k + repair, then we need k chunks to recover
        # k = total / (1 + redundancy)
        k = int(chunk_count / (1 + actual_redundancy))
        return max(k, 1)
