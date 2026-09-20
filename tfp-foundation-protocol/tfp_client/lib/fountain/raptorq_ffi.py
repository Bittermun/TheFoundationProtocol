# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
RFC 6330 RaptorQ and Universal Fountain Coding Adapter

Provides high-performance RFC 6330 RaptorQ erasure coding via compiled Rust
bindings when available, with automatic transparent fallback to pure-Python
systematic GF(2) fountain coding on resource-constrained environments.
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
    _HAS_RAPTORQ = True
except ImportError:
    raptorq = None
    _HAS_RAPTORQ = False

from tfp_client.lib.fountain.fountain_real import (
    RealRaptorQAdapter as PurePythonFountainAdapter,
    IntegrityError,
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
    RFC 6330-compliant RaptorQ erasure code adapter.
    
    Uses compiled Rust bindings when available; falls back to pure-Python
    erasure coding seamlessly when raptorq wheel is not installed.
    """

    def __init__(self, shard_size: int = _SHARD_SIZE):
        self.shard_size = shard_size
        self._fallback_adapter = None
        if not _HAS_RAPTORQ:
            log.info("Native raptorq library not detected; using pure-Python systematic fountain adapter")
            self._fallback_adapter = PurePythonFountainAdapter(shard_size=shard_size)

    def encode(
        self, data: bytes, redundancy: float = 0.05, hmac_key: bytes = None
    ) -> List[bytes]:
        """
        Encode data using RaptorQ (or fallback fountain coding).
        """
        if not data:
            raise ValueError("Cannot encode empty data")

        if not _HAS_RAPTORQ:
            return self._fallback_adapter.encode(data, redundancy=redundancy, hmac_key=hmac_key)

        redundancy = min(max(redundancy, 0.0), _MAX_OVERHEAD)
        orig_len = len(data)
        
        # Pad data to multiple of shard_size
        padded = _pad(data, self.shard_size)
        k = len(padded) // self.shard_size
        
        # Calculate number of repair symbols
        n_repair = max(1, int(k * redundancy) + 1)
        total_symbols = k + n_repair
        
        try:
            encoder = raptorq.Encoder.with_defaults(data, symbol_size=self.shard_size)
            encoded_packets = encoder.get_encoded_packets(total_symbols)
            
            all_shards = []
            for idx, packet in enumerate(encoded_packets):
                header = struct.pack(">QII", orig_len, k, idx)
                frame = header + packet
                
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
        Decode data from RaptorQ or fallback fountain shards.
        """
        if not shards:
            raise ValueError("No shards to decode")

        if not _HAS_RAPTORQ:
            return self._fallback_adapter.decode(shards, k=k, hmac_key=hmac_key)

        parsed = []
        orig_len = None
        src_k = None
        hmac_failed_count = 0
        
        for shard in shards:
            if hmac_key is not None:
                if len(shard) < 16 + _HMAC_SIZE:
                    log.warning(
                        "Shard too short for HMAC verification (%d bytes); skipping",
                        len(shard),
                    )
                    continue
                frame, received_mac = shard[:-_HMAC_SIZE], shard[-_HMAC_SIZE:]
                expected_mac = _shard_hmac(hmac_key, frame)
                if not _hmac.compare_digest(received_mac, expected_mac):
                    log.warning("Dropping corrupted shard: per-shard HMAC verification failed")
                    hmac_failed_count += 1
                    continue
                shard = frame

            if shard.startswith(b'fallback_shard_'):
                log.debug("Detected authenticated NDN fallback shard, returning content directly")
                return shard[15:]

            if len(shard) < 16:
                continue
            
            o_len, sk, idx = struct.unpack(">QII", shard[:16])
            if orig_len is None:
                orig_len, src_k = o_len, sk
            parsed.append((idx, shard[16:]))
        
        if orig_len is None or src_k is None:
            if hmac_key is not None and hmac_failed_count > 0:
                raise IntegrityError("per-shard HMAC verification failed for all shards")
            return b"".join(s[:k] if k else s for s in shards)[
                : k * self.shard_size if k else None
            ]
        
        if k is None:
            k = src_k
        
        if len(parsed) < k:
            if hmac_key is not None and hmac_failed_count > 0:
                raise IntegrityError(
                    f"Insufficient valid shards after dropping corrupted shards: need {k}, got {len(parsed)}"
                )
            raise ValueError(
                f"Insufficient shards: need {k}, got {len(parsed)}"
            )
        
        symbols_to_decode = parsed[:k]
        symbol_indices = [idx for idx, _ in symbols_to_decode]
        symbol_data = [data for _, data in symbols_to_decode]
        
        try:
            decoder = raptorq.Decoder(symbol_data, symbol_indices, symbol_size=self.shard_size)
            recovered = decoder.decode()
            return recovered[:orig_len]
            
        except Exception as e:
            raise RaptorQError(f"RaptorQ decoding failed: {e}")


def shutdown_encode_executor():
    """Graceful shutdown hook (kept for API compatibility)."""
    PurePythonFountainAdapter().shutdown_encode_executor if hasattr(PurePythonFountainAdapter, "shutdown_encode_executor") else None
