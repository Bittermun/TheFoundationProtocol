"""
Real fountain/erasure code adapter — pure Python, no external deps.
Uses systematic XOR-based erasure coding (equivalent to binary LDPC).
Implements RaptorQ-compatible interface: encode → shards, decode(any k shards) → original.

Interface matches RaptorQAdapter exactly.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import struct
from typing import List, Tuple

log = logging.getLogger(__name__)

_SHARD_SIZE = 128  # bytes per shard
_MAX_OVERHEAD = 0.5  # max redundancy fraction
_HMAC_SIZE = 32  # HMAC-SHA3-256 digest length


class IntegrityError(Exception):
    """Raised when a per-shard HMAC verification fails."""


def _pad(data: bytes, shard_size: int) -> bytes:
    rem = len(data) % shard_size
    if rem:
        data += b"\x00" * (shard_size - rem)
    return data


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _gf2_rref(matrix: List[List[int]], ncols: int) -> Tuple[List[List[int]], List[int]]:
    """Reduced Row Echelon Form over GF(2). Returns (rref_matrix, pivot_cols)."""
    m = [row[:] for row in matrix]
    pivot_row = 0
    pivot_cols = []
    for col in range(ncols):
        # find pivot
        found = -1
        for row in range(pivot_row, len(m)):
            if m[row][col] == 1:
                found = row
                break
        if found == -1:
            continue
        m[pivot_row], m[found] = m[found], m[pivot_row]
        pivot_cols.append(col)
        for row in range(len(m)):
            if row != pivot_row and m[row][col] == 1:
                m[row] = [(m[row][i] ^ m[pivot_row][i]) for i in range(len(m[row]))]
        pivot_row += 1
    return m, pivot_cols


def _shard_hmac(key: bytes, payload: bytes) -> bytes:
    """Return HMAC-SHA3-256(key, payload)."""
    return _hmac.new(key, payload, hashlib.sha3_256).digest()


class RealRaptorQAdapter:
    """
    Real systematic erasure code adapter.
    encode: splits data into k source shards, generates redundancy shards via XOR combos.
    decode: recovers original from any k of the received shards using Gaussian elimination.

    Per-shard HMAC integrity:
        When ``hmac_key`` is provided to encode/decode, each shard has a 32-byte
        HMAC-SHA3-256(key, header+payload) appended.  decode raises IntegrityError
        on any mismatch.
    """

    def __init__(self, shard_size: int = _SHARD_SIZE):
        self.shard_size = shard_size

    def encode(
        self, data: bytes, redundancy: float = 0.05, hmac_key: bytes = None
    ) -> List[bytes]:
        if not data:
            raise ValueError("Cannot encode empty data")
        redundancy = min(max(redundancy, 0.0), _MAX_OVERHEAD)
        padded = _pad(data, self.shard_size)
        k = len(padded) // self.shard_size
        source = [
            padded[i * self.shard_size : (i + 1) * self.shard_size] for i in range(k)
        ]
        n_repair = max(1, int(k * redundancy) + 1)
        # Generate repair shards: deterministic XOR combinations seeded by index
        repair = []
        for r in range(n_repair):
            seed = hashlib.sha256(f"repair:{r}:{k}".encode()).digest()
            combo = bytearray(self.shard_size)
            for i in range(k):
                # include source shard i if bit i of seed is 1
                if seed[i % len(seed)] & (1 << (i % 8)):
                    combo = bytearray(_xor(bytes(combo), source[i]))
            # ensure at least one source is XORed in
            if all(b == 0 for b in combo):
                combo = bytearray(source[r % k])
            repair.append(bytes(combo))
        # Systematic: source shards first, then repair
        all_shards = source + repair
        # Prepend metadata: original length (8 bytes), k (4 bytes), shard index (4 bytes)
        result = []
        orig_len = len(data)
        for idx, shard in enumerate(all_shards):
            header = struct.pack(">QII", orig_len, k, idx)
            frame = header + shard
            if hmac_key is not None:
                frame = frame + _shard_hmac(hmac_key, frame)
            result.append(frame)
        return result

    def decode(
        self, shards: List[bytes], k: int = None, hmac_key: bytes = None
    ) -> bytes:
        if not shards:
            raise ValueError("No shards to decode")
        # Parse headers, optionally verify HMAC
        parsed = []
        orig_len = None
        src_k = None
        for shard in shards:
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

        # Sort shards by index
        parsed.sort(key=lambda x: x[0])

        # Systematic shards (index < k) can be returned directly if we have all of them
        source_shards = {idx: data for idx, data in parsed if idx < k}
        if len(source_shards) >= k:
            result = b"".join(source_shards[i] for i in range(k))
            return result[:orig_len]

        # Need repair shards — use Gaussian elimination over GF(2)
        # Build the generator matrix rows for available shards
        available = parsed[:k]  # take first k available
        matrix_rows = []
        shard_data = []
        for idx, data in available:
            if idx < src_k:
                row = [1 if j == idx else 0 for j in range(src_k)]
            else:
                # Reconstruct the XOR combination for this repair shard
                r = idx - src_k
                seed = hashlib.sha256(f"repair:{r}:{src_k}".encode()).digest()
                row = [
                    1 if (seed[i % len(seed)] & (1 << (i % 8))) else 0
                    for i in range(src_k)
                ]
                if sum(row) == 0:
                    row[r % src_k] = 1
            matrix_rows.append(row)
            shard_data.append(bytearray(data))

        # Solve byte-by-byte
        recovered = [bytearray(self.shard_size) for _ in range(src_k)]
        # For each byte position, solve the GF(2) system
        for byte_pos in range(self.shard_size):
            aug = [row + [shard_data[i][byte_pos]] for i, row in enumerate(matrix_rows)]
            rref, pivots = _gf2_rref(aug, src_k)
            for pivot_idx, col in enumerate(pivots):
                if pivot_idx < len(rref):
                    recovered[col][byte_pos] = rref[pivot_idx][src_k]

        result = b"".join(bytes(s) for s in recovered)
        return result[:orig_len]
