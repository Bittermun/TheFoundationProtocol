# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""Generic binary FastCDC delta patches, usable for opaque ZIM archives.
Payloads stream through temporary files. Hash indexes scale with chunk count;
this module does not parse ZIM clusters or establish publisher identity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tfp_core_v4.cdc import _GEAR_MATRIX_64, ContentDefinedChunker

ZIM_PATCH_MAGIC = b"TFPZIMP1"
DEFAULT_STREAM_BUFFER_SIZE = 1024 * 1024  # 1 MB



@dataclass(frozen=True)
class ZimPatchLimits:
    """Resource ceilings for patch admission; configurable by operator callers."""
    max_header_bytes: int = 1048576
    max_chunks: int = 4096
    max_chunk_bytes: int = 131072
    max_target_bytes: int = 67108864

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Patch limits must be positive integers")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def bounded_int(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Invalid integer or resource limit exceeded")
    return value


def valid_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid SHA3 digest")
    return value


def check_output(output: Path, *inputs: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if any(output.resolve() == source.resolve() for source in inputs):
        raise ValueError("Output aliases input")


@contextmanager
def new_output(output: Path):
    """Install a flushed sibling without overwriting existing content, including races."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tfp-stage-", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        # Hard link creation is exclusive. Do not replace a concurrently created output.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ZimPatchManifest:
    """Metadata describing a FastCDC differential ZIM patch."""

    base_sha3: str
    target_sha3: str
    target_size: int
    target_chunk_hashes: list[str]
    novel_chunk_count: int
    total_novel_bytes: int


class ZimDeltaEngine:
    """
    Differential sync engine for large compressed knowledge archives.
    Streams payloads; metadata memory scales with bounded chunk counts.
    """

    def __init__(
        self,
        min_chunk_size: int = 16384,
        target_chunk_size: int = 65536,
        max_chunk_size: int = 131072,
    ):
        self.chunker = ContentDefinedChunker(
            min_size=min_chunk_size,
            target_size=target_chunk_size,
            max_size=max_chunk_size,
        )

    def _stream_chunks(
        self,
        path: Path,
        buffer_size: int = DEFAULT_STREAM_BUFFER_SIZE,
    ) -> Iterator[tuple[int, bytes, str]]:
        """
        Stream FastCDC chunks from file without loading entire file into memory.
        Yields (offset_in_file, chunk_bytes, sha3_256_hash).
        """
        uint64_max = 0xFFFFFFFFFFFFFFFF
        min_sz = self.chunker.min_size
        max_sz = self.chunker.max_size
        tgt_sz = self.chunker.target_size
        mask_s = self.chunker.mask_s
        mask_l = self.chunker.mask_l

        with open(path, "rb") as f:
            buf = bytearray()
            file_offset = 0
            eof = False

            while not eof or buf:
                # Top up buffer if below double the maximum chunk size
                if not eof and len(buf) < max_sz * 2:
                    read_bytes = f.read(buffer_size)
                    if not read_bytes:
                        eof = True
                    else:
                        buf.extend(read_bytes)

                if not buf:
                    break

                n = len(buf)
                if n <= min_sz:
                    if not eof:
                        continue
                    if eof:
                        chunk = bytes(buf)
                        buf.clear()
                        h = hashlib.sha3_256(chunk).hexdigest()
                        yield file_offset, chunk, h
                        file_offset += len(chunk)
                    break

                max_scan = min(max_sz, n)
                if max_scan < max_sz and not eof:
                    continue

                scan_pos = min_sz
                mid_point = min(tgt_sz, max_scan)
                rolling_hash = 0

                # 1. Warm up rolling hash on minimum window
                for i in range(scan_pos):
                    rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[buf[i]]) & uint64_max

                # 2. Sub-target region: tight mask
                boundary_found = False
                while scan_pos < mid_point:
                    b = buf[scan_pos]
                    rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[b]) & uint64_max
                    if (rolling_hash & mask_s) == 0:
                        boundary_found = True
                        scan_pos += 1
                        break
                    scan_pos += 1

                # 3. Post-target region: looser mask
                if not boundary_found:
                    while scan_pos < max_scan:
                        b = buf[scan_pos]
                        rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[b]) & uint64_max
                        if (rolling_hash & mask_l) == 0:
                            boundary_found = True
                            scan_pos += 1
                            break
                        scan_pos += 1

                chunk = bytes(buf[:scan_pos])
                del buf[:scan_pos]
                h = hashlib.sha3_256(chunk).hexdigest()
                yield file_offset, chunk, h
                file_offset += scan_pos

    def _scan_base_file(self, path: Path, limits: ZimPatchLimits | None = None) -> tuple[dict[str, tuple[int, int]], str]:
        """
        Scan base archive and build an index of chunk hashes to (offset, size).
        Stores zero payload bytes in RAM. Returns (chunk_offsets, full_file_sha3).
        """
        offsets: dict[str, tuple[int, int]] = {}
        file_hasher = hashlib.sha3_256()

        with open(path, "rb") as f:
            while chunk := f.read(DEFAULT_STREAM_BUFFER_SIZE):
                file_hasher.update(chunk)

        for offset, chunk_bytes, h in self._stream_chunks(path):
            if limits and (len(chunk_bytes) > limits.max_chunk_bytes or (h not in offsets and len(offsets) >= limits.max_chunks)):
                raise ValueError("Base exceeds chunk limits")
            if h not in offsets:
                offsets[h] = (offset, len(chunk_bytes))

        return offsets, file_hasher.hexdigest()

    def create_patch(
        self, base_path: str | Path, target_path: str | Path,
        patch_out: str | Path, metadata: dict[str, Any] | None = None,
        *, limits: ZimPatchLimits | None = None,
    ) -> ZimPatchManifest:
        limits = limits or ZimPatchLimits()
        base, target, output = map(Path, (base_path, target_path, patch_out))
        check_output(output, base, target)
        for source in (base, target):
            if source.stat().st_size > limits.max_target_bytes:
                raise ValueError("Archive exceeds size limit")
        offsets, base_hash = self._scan_base_file(base, limits)
        if len(offsets) > limits.max_chunks:
            raise ValueError("Base exceeds chunk limit")
        hashes: list[str] = []
        novel: set[str] = set()
        total = 0
        hasher = hashlib.sha3_256()
        with tempfile.TemporaryFile() as spool:
            for _, chunk, digest in self._stream_chunks(target):
                if len(hashes) >= limits.max_chunks or len(chunk) > limits.max_chunk_bytes:
                    raise ValueError("Target exceeds chunk limits")
                hashes.append(digest)
                hasher.update(chunk)
                if digest not in offsets and digest not in novel:
                    novel.add(digest)
                    total += len(chunk)
                    spool.write(struct.pack("!BI", 64, len(chunk)))
                    spool.write(digest.encode("ascii"))
                    spool.write(chunk)
            manifest = ZimPatchManifest(base_hash, hasher.hexdigest(), target.stat().st_size,
                                        hashes, len(novel), total)
            header = dict(vars(manifest), metadata=metadata or {}, chunker_params=self.parameters)
            raw = json.dumps(header, allow_nan=False).encode("utf-8")
            if len(raw) > limits.max_header_bytes:
                raise ValueError("Patch header exceeds limit")
            with new_output(output) as stream:
                stream.write(ZIM_PATCH_MAGIC + struct.pack("!I", len(raw)) + raw)
                spool.seek(0)
                shutil.copyfileobj(spool, stream, DEFAULT_STREAM_BUFFER_SIZE)
        return manifest

    @property
    def parameters(self) -> list[int]:
        return [self.chunker.min_size, self.chunker.target_size, self.chunker.max_size]

    def apply_patch(
        self, base_path: str | Path, patch_path: str | Path, out_path: str | Path,
        *, limits: ZimPatchLimits | None = None,
    ) -> None:
        limits = limits or ZimPatchLimits()
        base, patch, output = map(Path, (base_path, patch_path, out_path))
        check_output(output, base, patch)
        if base.stat().st_size > limits.max_target_bytes:
            raise ValueError("Base archive exceeds limit")
        novel: dict[str, tuple[int, int]] = {}
        with patch.open("rb") as stream:
            if stream.read(8) != ZIM_PATCH_MAGIC:
                raise ValueError("Invalid patch magic")
            length_raw = stream.read(4)
            if len(length_raw) != 4:
                raise ValueError("Truncated patch header")
            length = struct.unpack("!I", length_raw)[0]
            if not 0 < length <= limits.max_header_bytes:
                raise ValueError("Patch header exceeds limit")
            raw = stream.read(length)
            if len(raw) != length:
                raise ValueError("Truncated patch header")
            header = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(header, dict):
                raise ValueError("Invalid patch header")
            size = bounded_int(header.get("target_size"), limits.max_target_bytes)
            count = bounded_int(header.get("novel_chunk_count"), limits.max_chunks)
            total = bounded_int(header.get("total_novel_bytes"), limits.max_target_bytes)
            hashes = header.get("target_chunk_hashes")
            if not isinstance(hashes, list) or len(hashes) > limits.max_chunks:
                raise ValueError("Invalid target chunk list")
            for digest in hashes:
                valid_hash(digest)
            valid_hash(header.get("base_sha3"))
            valid_hash(header.get("target_sha3"))
            # Legacy v1 lacked parameters: only the original default is unambiguous.
            params = header.get("chunker_params", [16384, 65536, 131072])
            if params != self.parameters or any(type(n) is not int for n in params):
                raise ValueError("Patch chunker parameters differ")
            payload_total = 0
            for _ in range(count):
                record = stream.read(5)
                if len(record) != 5:
                    raise ValueError("Truncated chunk metadata")
                hlen, clen = struct.unpack("!BI", record)
                if hlen != 64 or not 0 < clen <= limits.max_chunk_bytes:
                    raise ValueError("Invalid chunk length")
                digest = stream.read(hlen).decode("ascii")
                valid_hash(digest)
                if digest in novel:
                    raise ValueError("Duplicate novel chunk")
                offset = stream.tell()
                chunk = stream.read(clen)
                if len(chunk) != clen or not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), digest):
                    raise ValueError("Invalid novel chunk digest or truncated payload")
                novel[digest] = (offset, clen)
                payload_total += clen
            if stream.read(1) or payload_total != total or not set(novel).issubset(hashes):
                raise ValueError("Unexpected patch records or totals")
        offsets, base_hash = self._scan_base_file(base, limits)
        if not hmac.compare_digest(base_hash, header["base_sha3"]):
            raise ValueError("Patch base digest mismatch")
        if len(offsets) > limits.max_chunks:
            raise ValueError("Base exceeds chunk limit")
        actual = 0
        hasher = hashlib.sha3_256()
        with new_output(output) as out, base.open("rb") as original, patch.open("rb") as delta:
            for digest in hashes:
                source = delta if digest in novel else original
                entries = novel if digest in novel else offsets
                if digest not in entries:
                    raise ValueError("Missing required chunk")
                offset, length = entries[digest]
                if length > limits.max_chunk_bytes:
                    raise ValueError("Referenced chunk exceeds limit")
                source.seek(offset)
                chunk = source.read(length)
                if not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), digest):
                    raise ValueError("Chunk digest mismatch")
                actual += len(chunk)
                if actual > size:
                    raise ValueError("Reconstruction exceeds declared size")
                hasher.update(chunk)
                out.write(chunk)
            if actual != size or not hmac.compare_digest(hasher.hexdigest(), header["target_sha3"]):
                raise RuntimeError("Reconstructed archive integrity failure")
