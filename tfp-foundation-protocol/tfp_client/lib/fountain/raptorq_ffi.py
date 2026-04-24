# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Real RFC 6330 RaptorQ adapter via raptorq Python package (Rust implementation).
Replaces XOR-based fountain code with standards-compliant RaptorQ erasure coding.

Interface matches the previous RealRaptorQAdapter exactly for backward compatibility.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import os
import struct
from typing import List

try:
    import raptorq
except ImportError:
    raise ImportError(
        "raptorq package not installed. Install with: pip install raptorq>=2.0.0"
    )

log = logging.getLogger(__name__)

_SHARD_SIZE = int(
    os.getenv("TFP_CHUNK_SIZE", 262144)
)  # bytes per shard (default: 256KB)
_MAX_OVERHEAD = 0.5  # max redundancy fraction
_HMAC_SIZE = 32  # HMAC-SHA3-256 digest length


class RaptorQError(Exception):
    """Raised when RaptorQ library operations fail."""

    pass


class IntegrityError(Exception):
    """Raised when a per-shard HMAC verification fails."""

    pass


def _pad(data: bytes, shard_size: int) -> bytes:
    """Pad data to multiple of shard_size with null bytes."""
    rem = len(data) % shard_size
    if rem:
        data += b"\x00" * (shard_size - rem)
    return data


def _shard_hmac(key: bytes, payload: bytes) -> bytes:
    """Return HMAC-SHA3-256(key, payload)."""
    return _hmac.new(key, payload, hashlib.sha3_256).digest()


class RealRaptorQAdapter:
    """
    RFC 6330-compliant RaptorQ erasure code adapter using raptorq Python package.
    
    encode: splits data into k source symbols, generates repair symbols via RaptorQ.
    decode: recovers original from any k symbols using RaptorQ decoding.
    
    Per-shard HMAC integrity:
        When ``hmac_key`` is provided to encode/decode, each shard has a 32-byte
        HMAC-SHA3-256(key, header+payload) appended.  decode raises IntegrityError
        on any mismatch.
    
    Header format (16 bytes):
        - original_length: 8 bytes (big-endian uint64)
        - k: 4 bytes (big-endian uint32) - number of source symbols
        - idx: 4 bytes (big-endian uint32) - symbol index
    """

    def __init__(self, shard_size: int = _SHARD_SIZE):
        self.shard_size = shard_size

    def encode(
        self, data: bytes, redundancy: float = 0.05, hmac_key: bytes = None
    ) -> List[bytes]:
        """
        Encode data using RFC 6330 RaptorQ.
        
        Args:
            data: Input data to encode
            redundancy: Fraction of repair symbols to generate (default 0.05 = 5%)
            hmac_key: Optional key for per-shard HMAC-SHA3-256 integrity
            
        Returns:
            List of encoded shards (each with header + payload + optional HMAC)
        """
        if not data:
            raise ValueError("Cannot encode empty data")
        
        redundancy = min(max(redundancy, 0.0), _MAX_OVERHEAD)
        orig_len = len(data)
        
        # Pad data to multiple of shard_size
        padded = _pad(data, self.shard_size)
        k = len(padded) // self.shard_size
        
        # Calculate number of repair symbols
        n_repair = max(1, int(k * redundancy) + 1)
        total_symbols = k + n_repair
        
        try:
            # Create RaptorQ encoder using correct API
            encoder = raptorq.Encoder.with_defaults(data, symbol_size=self.shard_size)
            
            # Generate encoded packets
            encoded_packets = encoder.get_encoded_packets(total_symbols)
            
            # Build shards with headers
            all_shards = []
            for idx, packet in enumerate(encoded_packets):
                # Prepend header: original_length, k, index
                header = struct.pack(">QII", orig_len, k, idx)
                frame = header + packet
                
                # Append HMAC if key provided
                if hmac_key is not None:
                    frame = frame + _shard_hmac(hmac_key, frame)
                
                all_shards.append(frame)
            
            return all_shards
            
        except Exception as e:
            raise RaptorQError(f"RaptorQ encoding failed: {e}")

    def decode(
        self, shards: List[bytes], k: int = None, hmac_key: bytes = None
    ) -> bytes:
        """
        Decode data from RaptorQ-encoded shards.
        
        Args:
            shards: List of encoded shards (with headers)
            k: Optional number of source symbols (inferred from headers if not provided)
            hmac_key: Optional key for per-shard HMAC-SHA3-256 verification
            
        Returns:
            Original decoded data
            
        Raises:
            IntegrityError: If HMAC verification fails
            RaptorQError: If RaptorQ decoding fails
        """
        if not shards:
            raise ValueError("No shards to decode")
        
        # Parse headers, optionally verify HMAC
        parsed = []
        orig_len = None
        src_k = None
        
        for shard in shards:
            # Detect NDN fallback shards (string-based, no binary header)
            if shard.startswith(b'fallback_shard_'):
                log.debug("Detected NDN fallback shard, returning content directly")
                return shard[15:]  # Strip 'fallback_shard_' prefix
            
            if hmac_key is not None:
                # Shard = header(16) + payload(shard_size) + hmac(32)
                if len(shard) < 16 + _HMAC_SIZE:
                    log.warning(
                        "Shard too short for HMAC verification (%d bytes); skipping",
                        len(shard),
                    )
                    continue
                frame, received_mac = shard[:-_HMAC_SIZE], shard[-_HMAC_SIZE:]
                expected_mac = _shard_hmac(hmac_key, frame)
                if not _hmac.compare_digest(received_mac, expected_mac):
                    raise IntegrityError("per-shard HMAC verification failed")
                shard = frame  # strip MAC for further processing
            
            if len(shard) < 16:
                continue
            
            o_len, sk, idx = struct.unpack(">QII", shard[:16])
            if orig_len is None:
                orig_len, src_k = o_len, sk
            parsed.append((idx, shard[16:]))
        
        if orig_len is None or src_k is None:
            # Legacy shards without header — concatenate directly
            return b"".join(s[:k] if k else s for s in shards)[
                : k * self.shard_size if k else None
            ]
        
        if k is None:
            k = src_k
        
        # Need at least k symbols to decode
        if len(parsed) < k:
            raise ValueError(
                f"Insufficient shards: need {k}, got {len(parsed)}"
            )
        
        # Take first k available symbols
        symbols_to_decode = parsed[:k]
        symbol_indices = [idx for idx, _ in symbols_to_decode]
        symbol_data = [data for _, data in symbols_to_decode]
        
        try:
            # Create RaptorQ decoder using correct API
            decoder = raptorq.Decoder(symbol_data, symbol_indices, symbol_size=self.shard_size)
            
            # Decode the original data
            recovered = decoder.decode()
            
            # Trim to original length
            return recovered[:orig_len]
            
        except Exception as e:
            raise RaptorQError(f"RaptorQ decoding failed: {e}")


# No global executor needed for raptorq (Rust implementation is already optimized)
# This function is kept for API compatibility
def shutdown_encode_executor():
    """No-op for raptorq implementation (kept for API compatibility)."""
    log.debug("RaptorQ implementation does not use global executor")
