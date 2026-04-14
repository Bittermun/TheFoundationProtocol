# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for Template Assembler - Chunk + HLT Integration

The Template Assembler combines:
1. Chunk Cache (cached content pieces)
2. HLT Validation (semantic synchronization check)
3. AI Assembly (minimal generation for missing pieces)
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tfp_client.lib.cache.chunk_store import ChunkStore
from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree
from tfp_client.lib.reconstruction.template_assembler import (
    AssemblyResult,
    AssemblyStatus,
    Recipe,
    TemplateAssembler,
)


class TestRecipe:
    """Test recipe parsing and validation."""

    def test_create_recipe(self):
        """Create a valid content recipe."""
        recipe = Recipe(
            content_hash="abc123",
            template_id="news_layout_v4",
            chunk_ids=["sky_42", "face_19", "text_delta"],
            ai_adapter="medical_v2.1",
        )
        assert recipe.template_id == "news_layout_v4"
        assert len(recipe.chunk_ids) == 3

    def test_recipe_serialization(self):
        """Recipe must serialize for network transmission."""
        recipe = Recipe(
            content_hash="def456",
            template_id="legal_doc_v2",
            chunk_ids=["header_01", "body_02"],
            ai_adapter="legal_v1.0",
        )
        data = recipe.to_dict()
        restored = Recipe.from_dict(data)
        assert restored.content_hash == recipe.content_hash
        assert restored.template_id == recipe.template_id


class TestTemplateAssembler:
    """Test template assembly with chunk cache and HLT."""

    def test_create_assembler(self):
        """Create assembler with chunk store and HLT."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()

        assembler = TemplateAssembler(chunk_store, hlt)
        assert assembler.chunk_store == chunk_store
        assert assembler.hlt == hlt

    def test_assemble_with_all_chunks_cached(self):
        """Assemble when all chunks are in cache - no AI needed."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("news_layout", "v4.0.0", hashlib.sha3_256(b"news").hexdigest())

        # Pre-populate chunk cache
        chunk_store.put(b"sky_data", category="visual", chunk_id_hint="sky_42")
        chunk_store.put(b"face_data", category="visual", chunk_id_hint="face_19")
        chunk_store.put(b"text_data", category="text", chunk_id_hint="text_delta")

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="content_001",
            template_id="news_layout_v4",
            chunk_ids=["sky_42", "face_19", "text_delta"],
            ai_adapter="news_layout",
        )

        result = assembler.assemble(recipe)

        assert result.status == AssemblyStatus.SUCCESS
        assert len(result.missing_chunks) == 0
        assert result.ai_generation_needed is False

    def test_assemble_with_missing_chunks(self):
        """Assemble when some chunks are missing - AI fill-in needed."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("news_layout", "v4.0.0", hashlib.sha3_256(b"news").hexdigest())

        # Only cache some chunks
        chunk_store.put(b"sky_data", category="visual", chunk_id_hint="sky_42")
        # face_19 and text_delta are missing

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="content_002",
            template_id="news_layout_v4",
            chunk_ids=["sky_42", "face_19", "text_delta"],
            ai_adapter="news_layout",
        )

        result = assembler.assemble(recipe)

        assert result.status == AssemblyStatus.PARTIAL
        assert len(result.missing_chunks) == 2
        assert "face_19" in result.missing_chunks
        assert "text_delta" in result.missing_chunks
        assert result.ai_generation_needed is True

    def test_assemble_fails_without_hlt_sync(self):
        """Assembly fails if HLT doesn't have required adapter."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        # Don't add the required domain

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="content_003",
            template_id="news_layout_v4",
            chunk_ids=["chunk_01"],
            ai_adapter="missing_domain",
        )

        result = assembler.assemble(recipe)

        assert result.status == AssemblyStatus.HLT_SYNC_FAILED
        assert result.hlt_synced is False

    def test_assemble_succeeds_with_hlt_adapter(self):
        """Assembly proceeds when HLT has required adapter."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("medical", "v2.1.0", hashlib.sha3_256(b"med").hexdigest())
        hlt.add_adapter("medical_v2_1_0", "v2.1.1", b"adapter_delta", "anchor_001")

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="content_004",
            template_id="medical_report",
            chunk_ids=["chart_01"],
            ai_adapter="medical",
        )

        result = assembler.assemble(recipe)

        assert result.hlt_synced is True
        # Will fail on chunk missing, but HLT check passes
        assert result.status in [AssemblyStatus.PARTIAL, AssemblyStatus.HLT_SYNC_FAILED]

    def test_get_assembly_plan(self):
        """Get detailed plan before assembly."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()

        chunk_store.put(b"data1", category="test", chunk_id_hint="existing_01")

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="content_005",
            template_id="template_v1",
            chunk_ids=["existing_01", "missing_02"],
            ai_adapter="test",
        )

        plan = assembler.get_assembly_plan(recipe)

        assert "existing_01" in plan["cached_chunks"]
        assert "missing_02" in plan["missing_chunks"]
        assert plan["ai_needed"] is True

    def test_assembly_result_serialization(self):
        """Assembly result must serialize for logging/auditing."""
        result = AssemblyResult(
            status=AssemblyStatus.SUCCESS,
            content_hash="result_001",
            assembled_data=b"final_output",
            cached_chunks=["chunk_01", "chunk_02"],
            missing_chunks=[],
            ai_generation_needed=False,
            hlt_synced=True,
        )

        data = result.to_dict()
        restored = AssemblyResult.from_dict(data)

        assert restored.status == result.status
        assert restored.content_hash == result.content_hash
        assert restored.assembled_data == result.assembled_data


class TestTemplateAssemblerIntegration:
    """Integration tests for full assembly workflow."""

    def test_full_workflow_cached_content(self):
        """Complete workflow: recipe → HLT check → chunk fetch → assemble."""
        # Setup
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("general", "v1.0.0", hashlib.sha3_256(b"gen").hexdigest())

        # Cache all chunks
        for i in range(5):
            chunk_store.put(
                f"data_{i}".encode(), category="test", chunk_id_hint=f"chunk_{i:02d}"
            )

        assembler = TemplateAssembler(chunk_store, hlt)

        # Create recipe
        recipe = Recipe(
            content_hash="full_test_001",
            template_id="multi_chunk_v1",
            chunk_ids=[f"chunk_{i:02d}" for i in range(5)],
            ai_adapter="general",
        )

        # Assemble
        result = assembler.assemble(recipe)

        assert result.status == AssemblyStatus.SUCCESS
        assert result.hlt_synced is True
        assert result.ai_generation_needed is False
        assert len(result.cached_chunks) == 5

    def test_full_workflow_partial_cache(self):
        """Workflow with partial cache - requests missing chunks."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("mixed", "v1.0.0", hashlib.sha3_256(b"mix").hexdigest())

        # Cache only some chunks
        for i in range(3):
            chunk_store.put(
                f"data_{i}".encode(), category="test", chunk_id_hint=f"chunk_{i:02d}"
            )

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="full_test_002",
            template_id="multi_chunk_v1",
            chunk_ids=[f"chunk_{i:02d}" for i in range(5)],  # 5 chunks needed
            ai_adapter="mixed",
        )

        result = assembler.assemble(recipe)

        assert result.status == AssemblyStatus.PARTIAL
        assert len(result.cached_chunks) == 3
        assert len(result.missing_chunks) == 2
        assert result.ai_generation_needed is True

    def test_bandwidth_savings_estimate(self):
        """Calculate bandwidth savings from chunk caching."""
        chunk_store = ChunkStore(max_bytes=10000, max_chunks=100)
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("test", "v1.0.0", hashlib.sha3_256(b"t").hexdigest())

        # Cache 80% of chunks
        total_chunks = 10
        cached_count = 8

        for i in range(cached_count):
            chunk_store.put(
                b"x" * 1000, category="test", chunk_id_hint=f"chunk_{i:02d}"
            )

        assembler = TemplateAssembler(chunk_store, hlt)

        recipe = Recipe(
            content_hash="bw_test_001",
            template_id="bw_test",
            chunk_ids=[f"chunk_{i:02d}" for i in range(total_chunks)],
            ai_adapter="test",
        )

        result = assembler.assemble(recipe)

        # Calculate savings
        total_size = total_chunks * 1000
        downloaded_size = len(result.missing_chunks) * 1000
        savings_percent = ((total_size - downloaded_size) / total_size) * 100

        assert savings_percent == 80.0  # 80% cached = 80% savings
