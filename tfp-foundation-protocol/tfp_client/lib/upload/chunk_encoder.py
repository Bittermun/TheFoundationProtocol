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

try:
    from tfp_transport.cdc import CDCChunker, create_fastcdc_chunker
    CDC_AVAILABLE = True
except ImportError:
    CDC_AVAILABLE = False

logger = logging.getLogger(__name__)


class ChunkEncoder:
    """
    Encodes data into erasure-coded chunks for fault-tolerant parallel uploads.

    Uses RaptorQ-compatible systematic erasure coding to generate redundant
    shards that can recover the original data from any subset of chunks.

    Args:
        chunk_size: Size of each chunk in bytes (default: 256KB)
        redundancy: Fraction of redundant chunks to generate (default: 0.1 = 10%)
        use_cdc: Whether to use Content-Defined Chunking before RaptorQ (default: False)
        cdc_min_chunk: Minimum CDC chunk size in KB (default: 4KB)
        cdc_max_chunk: Maximum CDC chunk size in KB (default: 64KB)
        cdc_avg_chunk: Target average CDC chunk size in KB (default: 16KB)
    """

    def __init__(
        self,
        chunk_size: int = 262144,  # 256KB default
        redundancy: float = 0.1,
        use_cdc: bool = False,
        cdc_min_chunk: int = 4,
        cdc_max_chunk: int = 64,
        cdc_avg_chunk: int = 16,
    ):
        self._chunk_size = chunk_size
        self._redundancy = redundancy
        self._adapter = RealRaptorQAdapter(shard_size=chunk_size)
        self._use_cdc = use_cdc and CDC_AVAILABLE

        if self._use_cdc:
            self._cdc_chunker = create_fastcdc_chunker(
                min_chunk_kb=cdc_min_chunk,
                max_chunk_kb=cdc_max_chunk,
                avg_chunk_kb=cdc_avg_chunk,
            )
        else:
            self._cdc_chunker = None

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

        # Apply CDC preprocessing if enabled
        if self._use_cdc and self._cdc_chunker:
            logger.info("Applying Content-Defined Chunking before RaptorQ encoding")
            # CDC chunks are reassembled before RaptorQ for now
            # Future: could encode each CDC chunk separately for better deduplication
            cdc_chunks = list(self._cdc_chunker.chunk_data(data))
            logger.info(
                "CDC split %d bytes into %d chunks (avg size: %.1f KB)",
                len(data),
                len(cdc_chunks),
                sum(len(c) for c in cdc_chunks) / len(cdc_chunks) / 1024 if cdc_chunks else 0,
            )
            # Reassemble for RaptorQ (CDC is primarily for deduplication metadata)
            data = b"".join(cdc_chunks)

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

    def get_cdc_chunk_hashes(self, data: bytes) -> Optional[List[str]]:
        """
        Get CDC chunk hashes for deduplication metadata.

        Args:
            data: Raw bytes to analyze

        Returns:
            List of SHA-256 hashes for each CDC chunk, or None if CDC is disabled
        """
        if not self._use_cdc or not self._cdc_chunker:
            return None

        return self._cdc_chunker.get_chunk_hashes(data)

    def is_cdc_enabled(self) -> bool:
        """
        Check if CDC is enabled for this encoder.

        Returns:
            True if CDC is enabled and available
        """
        return self._use_cdc
