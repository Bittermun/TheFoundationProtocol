# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Template Assembler - Combines Chunks + HLT for Efficient Reconstruction

The Template Assembler is the final piece that brings together:
1. Chunk Cache - Reusable content pieces (textures, layouts, audio patterns)
2. HLT Validation - Ensures semantic synchronization before assembly
3. AI Assembly - Minimal generation only for missing pieces

Workflow:
  Recipe → [HLT Sync Check] → [Chunk Cache Lookup] → [AI Fill-in] → Final Content
"""

import dataclasses
import json
from enum import Enum
from typing import Any, Dict, List, Optional

from tfp_client.lib.cache.chunk_store import ChunkStore
from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree


class AssemblyStatus(Enum):
    """Status of template assembly operation."""

    SUCCESS = "success"  # All chunks cached, assembled
    PARTIAL = "partial"  # Some chunks missing, AI fill-in needed
    HLT_SYNC_FAILED = "hlt_sync_failed"  # HLT doesn't have required adapter
    CHUNK_FETCH_FAILED = "chunk_fetch_failed"  # Failed to fetch required chunks
    ERROR = "error"  # General error


@dataclasses.dataclass
class Recipe:
    """
    Content recipe describing how to assemble final output.

    Sent by broadcaster, contains references to chunks and required AI adapter.
    """

    content_hash: str
    template_id: str
    chunk_ids: List[str]
    ai_adapter: str
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Serialize recipe to dictionary."""
        return {
            "content_hash": self.content_hash,
            "template_id": self.template_id,
            "chunk_ids": self.chunk_ids,
            "ai_adapter": self.ai_adapter,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Recipe":
        """Deserialize recipe from dictionary."""
        return cls(
            content_hash=data["content_hash"],
            template_id=data["template_id"],
            chunk_ids=data["chunk_ids"],
            ai_adapter=data["ai_adapter"],
            metadata=data.get("metadata", {}),
        )

    def to_bytes(self) -> bytes:
        """Serialize to bytes for network transmission."""
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Recipe":
        """Deserialize from bytes."""
        return cls.from_dict(json.loads(data.decode("utf-8")))


@dataclasses.dataclass
class AssemblyResult:
    """Result of template assembly operation."""

    status: AssemblyStatus
    content_hash: str
    assembled_data: Optional[bytes] = None
    cached_chunks: List[str] = dataclasses.field(default_factory=list)
    missing_chunks: List[str] = dataclasses.field(default_factory=list)
    ai_generation_needed: bool = False
    hlt_synced: bool = False
    error_message: Optional[str] = None
    bandwidth_saved_bytes: int = 0
    compute_saved_percent: float = 0.0

    def to_dict(self) -> Dict:
        """Serialize result to dictionary."""
        return {
            "status": self.status.value,
            "content_hash": self.content_hash,
            "assembled_data": self.assembled_data.hex()
            if self.assembled_data
            else None,
            "cached_chunks": self.cached_chunks,
            "missing_chunks": self.missing_chunks,
            "ai_generation_needed": self.ai_generation_needed,
            "hlt_synced": self.hlt_synced,
            "error_message": self.error_message,
            "bandwidth_saved_bytes": self.bandwidth_saved_bytes,
            "compute_saved_percent": self.compute_saved_percent,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AssemblyResult":
        """Deserialize result from dictionary."""
        return cls(
            status=AssemblyStatus(data["status"]),
            content_hash=data["content_hash"],
            assembled_data=bytes.fromhex(data["assembled_data"])
            if data.get("assembled_data")
            else None,
            cached_chunks=data.get("cached_chunks", []),
            missing_chunks=data.get("missing_chunks", []),
            ai_generation_needed=data.get("ai_generation_needed", False),
            hlt_synced=data.get("hlt_synced", False),
            error_message=data.get("error_message"),
            bandwidth_saved_bytes=data.get("bandwidth_saved_bytes", 0),
            compute_saved_percent=data.get("compute_saved_percent", 0.0),
        )


class TemplateAssembler:
    """
    Assembles content from cached chunks with HLT validation.

    Minimizes bandwidth and compute by:
    1. Checking HLT for semantic sync (prevents drift)
    2. Using cached chunks when available (saves bandwidth)
    3. Only generating missing pieces with AI (saves compute)
    """

    def __init__(self, chunk_store: ChunkStore, hlt: HierarchicalLexiconTree):
        self.chunk_store = chunk_store
        self.hlt = hlt

    def assemble(self, recipe: Recipe) -> AssemblyResult:
        """
        Assemble content from recipe.

        Args:
            recipe: Content recipe with chunk IDs and AI adapter

        Returns:
            AssemblyResult with status, data, and metrics
        """
        # Step 1: Validate HLT synchronization
        hlt_synced = self._check_hlt_sync(recipe.ai_adapter)

        if not hlt_synced:
            return AssemblyResult(
                status=AssemblyStatus.HLT_SYNC_FAILED,
                content_hash=recipe.content_hash,
                hlt_synced=False,
                error_message=f"HLT not synchronized for adapter: {recipe.ai_adapter}",
            )

        # Step 2: Check chunk cache for each required chunk
        cached_chunks = []
        missing_chunks = []
        total_size = 0
        cached_size = 0

        for chunk_id in recipe.chunk_ids:
            if chunk_id in self.chunk_store:
                cached_chunks.append(chunk_id)
                entry = self.chunk_store.get_chunk(chunk_id)
                cached_size += len(entry.data)
            else:
                missing_chunks.append(chunk_id)

            # Estimate total size (would come from chunk registry in production)
            total_size += 1000  # Placeholder estimate

        # Step 3: Calculate savings metrics
        bandwidth_saved = cached_size
        compute_saved = (
            (len(cached_chunks) / len(recipe.chunk_ids)) * 100
            if recipe.chunk_ids
            else 0
        )

        # Step 4: Assemble available chunks
        assembled_data = self._assemble_cached_chunks(cached_chunks)

        # Step 5: Determine if AI generation is needed
        ai_needed = len(missing_chunks) > 0

        # Step 6: Determine final status
        if not missing_chunks:
            status = AssemblyStatus.SUCCESS
        elif ai_needed:
            status = AssemblyStatus.PARTIAL
        else:
            status = AssemblyStatus.ERROR

        return AssemblyResult(
            status=status,
            content_hash=recipe.content_hash,
            assembled_data=assembled_data,
            cached_chunks=cached_chunks,
            missing_chunks=missing_chunks,
            ai_generation_needed=ai_needed,
            hlt_synced=hlt_synced,
            bandwidth_saved_bytes=bandwidth_saved,
            compute_saved_percent=compute_saved,
        )

    def get_assembly_plan(self, recipe: Recipe) -> Dict[str, Any]:
        """
        Get detailed assembly plan without executing.

        Useful for determining what needs to be fetched before assembly.

        Returns:
            Dict with cached_chunks, missing_chunks, ai_needed, and estimates
        """
        cached = []
        missing = []

        for chunk_id in recipe.chunk_ids:
            if chunk_id in self.chunk_store:
                cached.append(chunk_id)
            else:
                missing.append(chunk_id)

        hlt_synced = self._check_hlt_sync(recipe.ai_adapter)

        return {
            "cached_chunks": cached,
            "missing_chunks": missing,
            "ai_needed": len(missing) > 0,
            "hlt_synced": hlt_synced,
            "cache_hit_rate": len(cached) / len(recipe.chunk_ids)
            if recipe.chunk_ids
            else 0,
            "estimated_bandwidth_needed": len(missing) * 1000,  # Placeholder
            "ready_to_assemble": hlt_synced and len(missing) == 0,
        }

    def _check_hlt_sync(self, ai_adapter: str) -> bool:
        """
        Check if HLT has the required AI adapter.

        Args:
            ai_adapter: Name of required adapter domain

        Returns:
            True if adapter is available and synchronized
        """
        if not self.hlt.has_domain(ai_adapter):
            return False

        # In production, would also check version compatibility
        latest = self.hlt.get_latest_version(ai_adapter)
        return latest["version"] is not None

    def _assemble_cached_chunks(self, chunk_ids: List[str]) -> bytes:
        """
        Assemble data from cached chunks.

        In production, this would:
        1. Fetch each chunk from cache
        2. Apply template layout rules
        3. Concatenate/merge according to recipe

        For now, simple concatenation.
        """
        data_parts = []

        for chunk_id in chunk_ids:
            try:
                entry = self.chunk_store.get_chunk(chunk_id)
                data_parts.append(entry.data)
            except KeyError:
                # Should not happen if called correctly
                pass

        return b"".join(data_parts)
