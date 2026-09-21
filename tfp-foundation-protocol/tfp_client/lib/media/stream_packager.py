# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Media Stream Packaging Engine for TFP v4.0.

Provides FastCDC boundary segmentation, Merkle tree construction, and
verifiable media manifest generation for streaming audio/video.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure tfp_core_v4 is importable
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.cdc import ChunkRecipe, ContentDefinedChunker
from tfp_core_v4.merkle import MerkleTree, sha3_256, verify_merkle_proof


@dataclass
class MediaManifest:
    """Verifiable manifest describing a partitioned media stream."""

    manifest_id: str
    media_type: str
    total_size: int
    chunk_count: int
    merkle_root: str
    chunk_hashes: List[str]
    chunk_sizes: List[int]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MediaManifest:
        chunk_hashes = list(d["chunk_hashes"])
        chunk_sizes = [int(s) for s in d["chunk_sizes"]]
        chunk_count = int(d["chunk_count"])
        total_size = int(d["total_size"])
        if chunk_count != len(chunk_hashes) or chunk_count != len(chunk_sizes):
            raise ValueError(
                f"Manifest chunk_count ({chunk_count}) does not match chunk_hashes length ({len(chunk_hashes)}) "
                f"or chunk_sizes length ({len(chunk_sizes)})"
            )
        if sum(chunk_sizes) != total_size:
            raise ValueError(
                f"Manifest total_size ({total_size}) does not match sum of chunk_sizes ({sum(chunk_sizes)})"
            )
        return cls(
            manifest_id=d["manifest_id"],
            media_type=d.get("media_type", "application/octet-stream"),
            total_size=total_size,
            chunk_count=chunk_count,
            merkle_root=d["merkle_root"],
            chunk_hashes=chunk_hashes,
            chunk_sizes=chunk_sizes,
            metadata=dict(d.get("metadata", {})),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> MediaManifest:
        return cls.from_dict(json.loads(json_str))

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> MediaManifest:
        return cls.from_json(raw.decode("utf-8"))


class MediaStreamPackager:
    """
    Packages continuous or segmented media payloads into content-defined chunks
    authenticated by a Merkle tree.
    """

    def __init__(
        self,
        min_chunk_size: int = 4096,      # 4 KB minimum
        target_chunk_size: int = 16384,   # 16 KB target for low-latency streaming
        max_chunk_size: int = 65536,     # 64 KB maximum
    ):
        self.chunker = ContentDefinedChunker(
            min_size=min_chunk_size,
            max_size=max_chunk_size,
            target_size=target_chunk_size,
        )

    def package(
        self,
        media_data: bytes,
        media_type: str = "video/mp4",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[MediaManifest, List[bytes], MerkleTree]:
        """
        Partition arbitrary media bytes into FastCDC chunks and build Merkle tree.

        Returns:
            (manifest, chunks, merkle_tree)
        """
        if not media_data:
            raise ValueError("Cannot package empty media stream")

        metadata = metadata or {}
        recipe, chunks = self.chunker.create_recipe(media_data, metadata=metadata)

        # Build Merkle tree over the raw chunks
        merkle = MerkleTree(chunks)
        merkle_root = merkle.root_hex

        # Compute deterministic manifest ID
        manifest_id_hash = hashlib.sha3_256(
            f"{media_type}:{merkle_root}:{len(media_data)}".encode("utf-8")
        ).hexdigest()

        manifest = MediaManifest(
            manifest_id=manifest_id_hash,
            media_type=media_type,
            total_size=len(media_data),
            chunk_count=len(chunks),
            merkle_root=merkle_root,
            chunk_hashes=recipe.chunk_hashes,
            chunk_sizes=recipe.chunk_sizes,
            metadata=metadata,
        )

        return manifest, chunks, merkle

    def verify_chunk(
        self,
        chunk: bytes,
        chunk_index: int,
        manifest: MediaManifest,
        merkle_tree: Optional[MerkleTree] = None,
    ) -> bool:
        """Verify chunk content matches manifest hash and optional Merkle audit proof."""
        if not (0 <= chunk_index < manifest.chunk_count):
            return False

        expected_hash = manifest.chunk_hashes[chunk_index]
        actual_hash = hashlib.sha3_256(chunk).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            return False

        if merkle_tree is not None:
            proof = merkle_tree.get_proof(chunk_index)
            expected_root_bytes = bytes.fromhex(manifest.merkle_root)
            return verify_merkle_proof(chunk, proof, expected_root_bytes)

        return True

    def assemble(self, manifest: MediaManifest, chunk_map: Dict[int, bytes]) -> bytes:
        """Reassemble full media payload from reconstructed chunks."""
        if len(chunk_map) < manifest.chunk_count:
            missing = set(range(manifest.chunk_count)) - set(chunk_map.keys())
            raise ValueError(f"Incomplete chunk map; missing indices: {sorted(missing)}")

        assembled = bytearray()
        for idx in range(manifest.chunk_count):
            chunk = chunk_map[idx]
            expected_hash = manifest.chunk_hashes[idx]
            if not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), expected_hash):
                raise ValueError(f"Chunk {idx} corrupted during assembly")
            assembled.extend(chunk)

        return bytes(assembled)
