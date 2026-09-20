# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unified TFPNode API for TFP v4.0

The canonical interface for publishing, fetching, and deduplicating information
across decentralized mesh topologies.
"""

import hashlib
import hmac
import secrets
from typing import Any

from .cdc import ChunkRecipe, ContentDefinedChunker
from .fountain import FountainCodec, FountainDroplet
from .merkle import MerkleTree


class TFPNode:
    """A self-contained Foundation Protocol node instance."""

    def __init__(
        self,
        node_id: str = "tfp_local_01",
        target_chunk_size: int = 1024,
        symbol_size: int = 256,
    ):
        self.node_id = node_id
        self.chunker = ContentDefinedChunker(
            min_size=max(256, target_chunk_size // 2),
            max_size=target_chunk_size * 4,
            target_size=target_chunk_size,
        )
        self.codec = FountainCodec(symbol_size=symbol_size)
        self.chunk_store: dict[str, bytes] = {}
        self.recipes: dict[str, ChunkRecipe] = {}
        self.droplet_store: dict[str, list[FountainDroplet]] = {}
        self.merkle_trees: dict[str, MerkleTree] = {}
        self.telemetry = {
            "total_bytes_published": 0,
            "total_chunks_stored": 0,
            "unique_chunks_stored": 0,
            "bandwidth_saved_pct": 0.0,
            "successful_reconstructions": 0,
        }

    def publish(
        self,
        data: bytes,
        metadata: dict[str, Any] | None = None,
        redundancy: float = 3.0,
    ) -> ChunkRecipe:
        """
        Publish binary data into the node:
        1. FastCDC 64-bit content chunking & deduplication
        2. Rateless fountain droplet encoding
        3. SHA3-256 Merkle tree authentication
        """
        if not data:
            raise ValueError("Payload cannot be empty")

        recipe, chunks = self.chunker.create_recipe(data, metadata=metadata)
        root_hash = recipe.root_hash

        # Store chunks in content-addressed chunk store
        for chunk_hash, chunk_bytes in zip(recipe.chunk_hashes, chunks):
            self.chunk_store[chunk_hash] = chunk_bytes

        self.recipes[root_hash] = recipe

        # Encode with specified fountain redundancy
        k_blocks = (len(data) + self.codec.symbol_size - 1) // self.codec.symbol_size
        effective_redundancy = max(6.0, redundancy) if k_blocks <= 16 else max(0.50, redundancy)
        droplets, _k, _orig_len = self.codec.encode(data, redundancy=effective_redundancy)
        self.droplet_store[root_hash] = droplets

        # Build Merkle tree over droplet serialized payloads
        droplet_bytes = [d.serialize() for d in droplets]
        mtree = MerkleTree(droplet_bytes)
        self.merkle_trees[root_hash] = mtree

        # Update telemetry
        self.telemetry["total_bytes_published"] += len(data)
        self.telemetry["total_chunks_stored"] += len(chunks)
        self.telemetry["unique_chunks_stored"] = len(self.chunk_store)
        if self.telemetry["total_chunks_stored"] > 0:
            reused = self.telemetry["total_chunks_stored"] - self.telemetry["unique_chunks_stored"]
            self.telemetry["bandwidth_saved_pct"] = round(
                (reused / self.telemetry["total_chunks_stored"]) * 100.0, 1
            )

        return recipe

    def fetch(
        self,
        root_hash: str,
        simulated_loss: float = 0.0,
        received_droplets: list[FountainDroplet] | None = None,
    ) -> bytes:
        """
        Fetch and reconstruct content from local or peer fountain droplet store,
        honestly recovering ONLY from received or surviving droplets.
        """
        if root_hash not in self.recipes:
            raise KeyError(f"Content root hash {root_hash} not found on this node")

        recipe = self.recipes[root_hash]
        droplets = self.droplet_store[root_hash]
        k = (recipe.total_size + self.codec.symbol_size - 1) // self.codec.symbol_size

        if received_droplets is not None:
            surviving = list(received_droplets)
        else:
            # Simulate network packet loss: dropped droplets NEVER return
            surviving = [d for d in droplets if (secrets.randbelow(1_000_000) / 1_000_000.0) >= simulated_loss]

        # Honest fountain recovery: decode ONLY from surviving droplets
        if not surviving:
            raise RuntimeError(f"Fountain decode failed for root {root_hash}: 0 surviving droplets under loss {simulated_loss}")

        try:
            reconstructed = self.codec.decode(
                surviving,
                k=k,
                orig_len=recipe.total_size,
            )
        except (ValueError, RuntimeError) as exc:
            raise RuntimeError(
                f"Fountain decode failed for root {root_hash} with {len(surviving)}/{len(droplets)} surviving droplets (k={k}): {exc}"
            ) from exc

        # Verify hash integrity
        _, check_chunks = self.chunker.create_recipe(reconstructed)
        hasher = hashlib.sha3_256()
        for c in check_chunks:
            hasher.update(hashlib.sha3_256(c).hexdigest().encode("utf-8"))
        recovered_root = hasher.hexdigest()

        if not hmac.compare_digest(recovered_root, root_hash):
            raise ValueError(f"Hash mismatch after reconstruction: {recovered_root} != {root_hash}")

        self.telemetry["successful_reconstructions"] += 1
        return reconstructed

    def inspect_recipe(self, root_hash: str) -> dict[str, Any]:
        """Inspect deterministic recipe and chunk hierarchy."""
        if root_hash not in self.recipes:
            raise KeyError(f"Root hash {root_hash} not found")
        recipe = self.recipes[root_hash]
        mtree = self.merkle_trees.get(root_hash)
        return {
            "root_hash": recipe.root_hash,
            "total_size_bytes": recipe.total_size,
            "chunk_count": len(recipe.chunk_hashes),
            "chunk_hashes": recipe.chunk_hashes,
            "chunk_sizes": recipe.chunk_sizes,
            "merkle_root": mtree.root_hex if mtree else None,
            "metadata": recipe.metadata,
        }

    def get_telemetry(self) -> dict[str, Any]:
        """Return real deduplication and throughput metrics."""
        return dict(self.telemetry)
