# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
FastCDC ZIM Cluster-Aware Delta Synchronization Engine for TFP v4.0.

Computes deduplicated differential patch recipes between massive offline knowledge
archives (such as Kiwix OpenZIM Wikipedia collections) using 64-bit normalized
rolling gear hashes, and applies delta patches with bit-exact cryptographic verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tfp_core_v4.cdc import ContentDefinedChunker

ZIM_PATCH_MAGIC = b"TFPZIMP1"


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
    Extracts cluster-level deltas and reconstructs target archives in-place or streamed.
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

    def _chunk_file(self, path: Path) -> tuple[dict[str, bytes], list[str], str]:
        """
        Partition a file into FastCDC chunks and compute hashes.
        Returns: (chunk_store, ordered_hashes, file_sha3_256)
        """
        data = path.read_bytes()
        file_sha3 = hashlib.sha3_256(data).hexdigest()
        chunks = self.chunker.chunk(data)
        chunk_store: dict[str, bytes] = {}
        ordered_hashes: list[str] = []

        for c in chunks:
            h = hashlib.sha3_256(c).hexdigest()
            ordered_hashes.append(h)
            if h not in chunk_store:
                chunk_store[h] = c

        return chunk_store, ordered_hashes, file_sha3

    def create_patch(
        self,
        base_path: str | Path,
        target_path: str | Path,
        patch_out: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> ZimPatchManifest:
        """
        Compute the differential delta between base_path and target_path,
        writing minimal novel chunk payloads and reconstruction map to patch_out.
        """
        b_path = Path(base_path)
        t_path = Path(target_path)
        p_out = Path(patch_out)

        # Chunk both archives
        base_store, _, base_sha3 = self._chunk_file(b_path)
        target_store, target_hashes, target_sha3 = self._chunk_file(t_path)

        # Identify novel chunks not in base
        base_hash_set = set(base_store.keys())
        novel_hashes = [h for h in target_store if h not in base_hash_set]
        total_novel_bytes = sum(len(target_store[h]) for h in novel_hashes)

        target_size = t_path.stat().st_size
        manifest = ZimPatchManifest(
            base_sha3=base_sha3,
            target_sha3=target_sha3,
            target_size=target_size,
            target_chunk_hashes=target_hashes,
            novel_chunk_count=len(novel_hashes),
            total_novel_bytes=total_novel_bytes,
        )

        manifest_dict = {
            "base_sha3": manifest.base_sha3,
            "target_sha3": manifest.target_sha3,
            "target_size": manifest.target_size,
            "target_chunk_hashes": manifest.target_chunk_hashes,
            "novel_chunk_count": manifest.novel_chunk_count,
            "total_novel_bytes": manifest.total_novel_bytes,
            "metadata": metadata or {},
        }
        manifest_raw = json.dumps(manifest_dict).encode("utf-8")

        p_out.parent.mkdir(parents=True, exist_ok=True)
        with open(p_out, "wb") as f:
            f.write(ZIM_PATCH_MAGIC)
            f.write(struct.pack("!I", len(manifest_raw)))
            f.write(manifest_raw)

            # Write novel chunk payloads: [hash_len: 1B, hash: ascii, payload_len: 4B, payload]
            for h in novel_hashes:
                chunk_bytes = target_store[h]
                h_bytes = h.encode("ascii")
                f.write(struct.pack("!BI", len(h_bytes), len(chunk_bytes)))
                f.write(h_bytes)
                f.write(chunk_bytes)

        return manifest

    def apply_patch(
        self,
        base_path: str | Path,
        patch_path: str | Path,
        out_path: str | Path,
    ) -> None:
        """
        Apply a differential FastCDC patch against base_path, verifying bit-exact SHA3-256 integrity.
        """
        b_path = Path(base_path)
        p_path = Path(patch_path)
        o_path = Path(out_path)

        if not b_path.exists():
            raise FileNotFoundError(f"Base archive not found: {b_path}")
        if not p_path.exists():
            raise FileNotFoundError(f"Patch file not found: {p_path}")

        # 1. Read patch header and manifest
        with open(p_path, "rb") as f:
            magic = f.read(len(ZIM_PATCH_MAGIC))
            if magic != ZIM_PATCH_MAGIC:
                raise ValueError("Invalid patch format: magic header mismatch")

            header_len_bytes = f.read(4)
            if len(header_len_bytes) < 4:
                raise ValueError("Truncated patch header")
            header_len = struct.unpack("!I", header_len_bytes)[0]
            manifest_dict = json.loads(f.read(header_len).decode("utf-8"))

            target_sha3 = manifest_dict["target_sha3"]
            target_chunk_hashes = manifest_dict["target_chunk_hashes"]
            novel_count = manifest_dict["novel_chunk_count"]

            # Load novel chunks from patch body
            available_chunks: dict[str, bytes] = {}
            for _ in range(novel_count):
                meta = f.read(5)  # 1B hash_len + 4B payload_len
                if len(meta) < 5:
                    raise ValueError("Truncated novel chunk metadata in patch")
                h_len, payload_len = struct.unpack("!BI", meta)
                h = f.read(h_len).decode("ascii")
                payload = f.read(payload_len)
                if len(payload) != payload_len:
                    raise ValueError(f"Truncated novel chunk payload for {h}")
                # Verify novel chunk integrity
                actual_h = hashlib.sha3_256(payload).hexdigest()
                if not hmac.compare_digest(actual_h, h):
                    raise ValueError(f"Corrupt novel chunk hash: expected {h}, got {actual_h}")
                available_chunks[h] = payload

        # 2. Extract base chunks
        base_store, _, base_sha3 = self._chunk_file(b_path)
        if not hmac.compare_digest(base_sha3, manifest_dict["base_sha3"]):
            # Base archive mismatch warning, but proceed if required chunks exist
            pass
        for h, c in base_store.items():
            if h not in available_chunks:
                available_chunks[h] = c

        # 3. Assemble target archive in stream
        o_path.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha3_256()
        with open(o_path, "wb") as out_f:
            for h in target_chunk_hashes:
                if h not in available_chunks:
                    raise RuntimeError(f"Missing required chunk hash {h} during reconstruction")
                chunk = available_chunks[h]
                out_f.write(chunk)
                hasher.update(chunk)

        # 4. Verify reconstructed hash against manifest
        reconstructed_sha3 = hasher.hexdigest()
        if not hmac.compare_digest(reconstructed_sha3, target_sha3):
            o_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Reconstructed archive integrity failure: expected {target_sha3}, got {reconstructed_sha3}"
            )
