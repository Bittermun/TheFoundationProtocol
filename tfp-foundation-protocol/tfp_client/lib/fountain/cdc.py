# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Content-Defined Chunking (CDC) Codec

Implements FastCDC (USENIX ATC '16) with standard 64-bit Gear hash lookup table
and normalized dual-mask boundary detection. Splits arbitrary binary data into
variable-sized chunks deterministically based on content boundaries.

This enables maximum deduplication and delta-compression for constrained
networks and distributed information synchronization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple

# Canonical FastCDC 64-bit Gear lookup table imported from tfp_core_v4.cdc
from tfp_core_v4.cdc import _GEAR_MATRIX_64

_UINT64_MAX = 0xFFFFFFFFFFFFFFFF


@dataclass
class ChunkRecipe:
    """
    Metadata representation of an assembled piece of content.
    Allows exact bit-for-bit reconstruction using stored or gossiped chunks.
    """
    total_size: int
    root_hash: str
    chunk_hashes: List[str]
    chunk_sizes: List[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChunkRecipe:
        return cls(
            total_size=data["total_size"],
            root_hash=data["root_hash"],
            chunk_hashes=data["chunk_hashes"],
            chunk_sizes=data["chunk_sizes"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> ChunkRecipe:
        return cls.from_dict(json.loads(json_str))


class ContentDefinedChunker:
    """
    Splits binary data into variable-sized chunks using the FastCDC algorithm.
    Guarantees boundary shift resistance and uniform chunk size distribution.
    """

    def __init__(
        self,
        min_size: int = 16384,     # 16 KB minimum size
        max_size: int = 262144,    # 256 KB maximum size
        target_size: int = 65536,  # 64 KB target average size
        normalization_level: int = 1,
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.target_size = target_size
        self.normalization_level = normalization_level

        # Calculate bitmasks for normalized chunking (USENIX FastCDC)
        # Target bits: log2(target_size)
        target_bits = max(1, (self.target_size - 1).bit_length())
        
        # Dual masks: smaller mask for region [min_size, target_size),
        # larger mask for region [target_size, max_size)
        bits_s = target_bits + self.normalization_level
        bits_l = max(1, target_bits - self.normalization_level)
        
        self.mask_s = (1 << bits_s) - 1
        self.mask_l = (1 << bits_l) - 1
        self.mask = (1 << target_bits) - 1

    def chunk_data(self, data: bytes) -> List[Dict[str, Any]]:
        """
        Partition data into variable-sized chunks.

        Returns:
            List of dictionaries with keys:
            - 'offset': int
            - 'size': int
            - 'hash': str (SHA3-256 hex digest)
            - 'data': bytes
        """
        if not data:
            return []

        chunks: List[Dict[str, Any]] = []
        n = len(data)

        # Fast path if total size <= min_size
        if n <= self.min_size:
            h = hashlib.sha3_256(data).hexdigest()
            return [{
                "offset": 0,
                "size": n,
                "hash": h,
                "data": data,
            }]

        offset = 0
        while offset < n:
            # Trailing tail check
            remaining = n - offset
            if remaining <= self.min_size:
                chunk_data = data[offset:]
                h = hashlib.sha3_256(chunk_data).hexdigest()
                chunks.append({
                    "offset": offset,
                    "size": len(chunk_data),
                    "hash": h,
                    "data": chunk_data,
                })
                break

            chunk_start = offset
            scan_pos = chunk_start + self.min_size
            max_scan = min(chunk_start + self.max_size, n)
            mid_point = min(chunk_start + self.target_size, max_scan)

            rolling_hash = 0

            # 1. Warm up rolling hash on the minimum window
            for i in range(chunk_start, scan_pos):
                byte_val = data[i]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[byte_val]) & _UINT64_MAX

            # 2. Sub-target region: use tighter mask (mask_s)
            boundary_found = False
            while scan_pos < mid_point:
                byte_val = data[scan_pos]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[byte_val]) & _UINT64_MAX
                if (rolling_hash & self.mask_s) == 0:
                    boundary_found = True
                    scan_pos += 1
                    break
                scan_pos += 1

            # 3. Post-target region: use looser mask (mask_l) if boundary not yet found
            if not boundary_found:
                while scan_pos < max_scan:
                    byte_val = data[scan_pos]
                    rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[byte_val]) & _UINT64_MAX
                    if (rolling_hash & self.mask_l) == 0:
                        boundary_found = True
                        scan_pos += 1
                        break
                    scan_pos += 1

            chunk_bytes = data[chunk_start:scan_pos]
            h = hashlib.sha3_256(chunk_bytes).hexdigest()
            chunks.append({
                "offset": chunk_start,
                "size": len(chunk_bytes),
                "hash": h,
                "data": chunk_bytes,
            })

            offset = scan_pos

        return chunks

    def create_recipe(self, data: bytes) -> Tuple[ChunkRecipe, List[bytes]]:
        """
        Chunk data and produce both a serializable ChunkRecipe and the raw chunk bytes list.
        """
        chunks = self.chunk_data(data)
        root_hash = hashlib.sha3_256(data).hexdigest()
        recipe = ChunkRecipe(
            total_size=len(data),
            root_hash=root_hash,
            chunk_hashes=[c["hash"] for c in chunks],
            chunk_sizes=[c["size"] for c in chunks],
        )
        chunk_bytes = [c["data"] for c in chunks]
        return recipe, chunk_bytes

    @staticmethod
    def assemble_from_chunks(recipe: ChunkRecipe, chunk_store: Dict[str, bytes]) -> bytes:
        """
        Reconstruct the original data from a recipe and a chunk dictionary.
        Raises KeyError if any chunk hash is missing.
        Raises ValueError if reconstructed hash doesn't match recipe root_hash.
        """
        assembled_parts = []
        for chash in recipe.chunk_hashes:
            if chash not in chunk_store:
                raise KeyError(f"Missing required chunk hash: {chash}")
            assembled_parts.append(chunk_store[chash])

        reconstructed = b"".join(assembled_parts)
        actual_hash = hashlib.sha3_256(reconstructed).hexdigest()
        if not hmac.compare_digest(actual_hash, recipe.root_hash):
            raise ValueError(
                f"Integrity check failed on assembly: expected {recipe.root_hash}, got {actual_hash}"
            )
        return reconstructed
