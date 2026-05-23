# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Content-Defined Chunking (CDC) Codec

Implements rolling hash-based file chunking (Gear/prime-modulo rolling hash)
to split files into chunks dynamically based on content boundaries. This
enables extremely efficient, duplicate-resistant chunk storage and transfers
over low-bandwidth networks (e.g. for audio streaming/radio pilots).
"""

import hashlib
from typing import List, Dict, Any

# Gear rolling hash configuration
# Pre-computed prime table for fast rolling hashing
_GEAR_MATRIX = [
    (16777619 * i) & 0xFFFFFFFF for i in range(256)
]


class ContentDefinedChunker:
    """
    Splits binary data into variable-sized chunks using a Gear-hash rolling window.
    This guarantees that modifications to one part of a file do not shift chunk
    boundaries for unchanged regions, enabling optimal deduplication.
    """

    def __init__(
        self,
        min_size: int = 16384,     # 16 KB min size
        max_size: int = 262144,    # 256 KB max size
        target_size: int = 65536,  # 64 KB target size
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.target_size = target_size
        
        # Calculate mask based on target size (target must be power of 2 for optimal modulo)
        # mod target_size - 1 maps to leading bits mask
        self.mask = self.target_size - 1

    def chunk_data(self, data: bytes) -> List[Dict[str, Any]]:
        """
        Scan through data and partition into variable-size chunks based on rolling hash triggers.
        
        Returns:
            List of dictionaries:
            [
                {
                    "offset": int,
                    "size": int,
                    "hash": str,  # SHA3-256 hash of the chunk
                    "data": bytes
                },
                ...
            ]
        """
        if not data:
            return []

        chunks = []
        n = len(data)
        
        # Fast path if file size is less than minimum chunk size
        if n <= self.min_size:
            h = hashlib.sha3_256(data).hexdigest()
            return [{
                "offset": 0,
                "size": n,
                "hash": h,
                "data": data
            }]

        offset = 0
        while offset < n:
            # If remaining bytes are less than min_size, consume the rest as a single chunk
            if n - offset <= self.min_size:
                chunk_data = data[offset:]
                h = hashlib.sha3_256(chunk_data).hexdigest()
                chunks.append({
                    "offset": offset,
                    "size": len(chunk_data),
                    "hash": h,
                    "data": chunk_data
                })
                break

            # Scan starting from minimum size window
            chunk_start = offset
            scan_pos = chunk_start + self.min_size
            max_scan = min(chunk_start + self.max_size, n)

            # Initialize rolling hash over the minimum window
            rolling_hash = 0
            for i in range(chunk_start, scan_pos):
                byte_val = data[i]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX[byte_val]) & 0xFFFFFFFF

            # Slide window to find boundary trigger
            boundary_found = False
            while scan_pos < max_scan:
                byte_val = data[scan_pos]
                # Update Gear Hash: H = (H << 1) + Gear[byte]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX[byte_val]) & 0xFFFFFFFF
                
                # Check for boundary trigger (e.g. hash match modulo pattern)
                # modulo pattern: rolling_hash & mask == 0
                if (rolling_hash & self.mask) == 0:
                    boundary_found = True
                    scan_pos += 1  # include triggering byte
                    break
                
                scan_pos += 1

            # Extract chunk
            chunk_data = data[chunk_start:scan_pos]
            h = hashlib.sha3_256(chunk_data).hexdigest()
            chunks.append({
                "offset": chunk_start,
                "size": len(chunk_data),
                "hash": h,
                "data": chunk_data
            })
            
            offset = scan_pos

        return chunks
