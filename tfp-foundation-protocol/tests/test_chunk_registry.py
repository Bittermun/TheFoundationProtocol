# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for Chunk Registry - Maps chunk_id → content_hash → category

TDD: Tests written before implementation.
"""

import hashlib

import pytest
from tfp_common.assets.chunk_index.categories import (
    CHUNK_CATEGORIES,
    get_category_by_name,
    validate_category,
)
from tfp_common.assets.chunk_index.registry import (
    ChunkEntry,
    ChunkRegistry,
)


class TestChunkCategory:
    """Test chunk category definitions."""

    def test_predefined_categories_exist(self):
        """Verify standard categories are defined."""
        assert "texture" in CHUNK_CATEGORIES
        assert "layout" in CHUNK_CATEGORIES
        assert "audio_pattern" in CHUNK_CATEGORIES
        assert "code_block" in CHUNK_CATEGORIES
        assert "text_delta" in CHUNK_CATEGORIES

    def test_category_has_required_fields(self):
        """Each category must have name and description."""
        for cat_name, category in CHUNK_CATEGORIES.items():
            assert hasattr(category, "name")
            assert hasattr(category, "description")
            assert category.name == cat_name

    def test_get_category_by_name_valid(self):
        """Retrieve category by name."""
        category = get_category_by_name("texture")
        assert category is not None
        assert category.name == "texture"

    def test_get_category_by_name_invalid(self):
        """Invalid category name returns None."""
        category = get_category_by_name("nonexistent_category")
        assert category is None

    def test_validate_category_valid(self):
        """Valid category passes validation."""
        assert validate_category("texture") is True
        assert validate_category("layout") is True

    def test_validate_category_invalid(self):
        """Invalid category fails validation."""
        assert validate_category("invalid_cat") is False
        assert validate_category("") is False


class TestChunkEntry:
    """Test individual chunk entry structure."""

    def test_create_chunk_entry(self):
        """Create a valid chunk entry."""
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        entry = ChunkEntry(
            chunk_id="sky_42",
            content_hash=content_hash,
            category="texture",
            size_bytes=len(chunk_data),
            version=1,
        )

        assert entry.chunk_id == "sky_42"
        assert entry.content_hash == content_hash
        assert entry.category == "texture"
        assert entry.size_bytes == len(chunk_data)
        assert entry.version == 1

    def test_chunk_id_validation(self):
        """Chunk ID must be alphanumeric with underscores."""
        # Valid IDs
        assert ChunkEntry.is_valid_chunk_id("sky_42")
        assert ChunkEntry.is_valid_chunk_id("face_19")
        assert ChunkEntry.is_valid_chunk_id("text_delta_v2")

        # Invalid IDs
        assert not ChunkEntry.is_valid_chunk_id("sky-42")  # hyphen
        assert not ChunkEntry.is_valid_chunk_id("sky 42")  # space
        assert not ChunkEntry.is_valid_chunk_id("")  # empty

    def test_content_hash_validation(self):
        """Content hash must be valid SHA3-256 hex string."""
        valid_hash = "a" * 64  # 64 hex chars = 256 bits

        assert ChunkEntry.is_valid_content_hash(valid_hash)
        assert not ChunkEntry.is_valid_content_hash("short")
        assert not ChunkEntry.is_valid_content_hash("g" * 64)  # invalid hex char

    def test_chunk_entry_serialization(self):
        """Serialize and deserialize chunk entry."""
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        entry = ChunkEntry(
            chunk_id="test_chunk",
            content_hash=content_hash,
            category="texture",
            size_bytes=100,
            version=1,
        )

        # Serialize
        serialized = entry.to_dict()
        assert isinstance(serialized, dict)
        assert serialized["chunk_id"] == "test_chunk"

        # Deserialize
        restored = ChunkEntry.from_dict(serialized)
        assert restored.chunk_id == entry.chunk_id
        assert restored.content_hash == entry.content_hash
        assert restored.category == entry.category


class TestChunkRegistry:
    """Test the main chunk registry functionality."""

    def test_create_empty_registry(self):
        """Create an empty chunk registry."""
        registry = ChunkRegistry()
        assert registry.count == 0
        assert registry.get_all_chunks() == []

    def test_register_chunk(self):
        """Register a new chunk in the registry."""
        registry = ChunkRegistry()
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        chunk_id = registry.register(
            chunk_data=chunk_data,
            category="texture",
            chunk_id_hint="test_chunk",
        )

        assert chunk_id is not None
        assert registry.count == 1

    def test_register_chunk_auto_id(self):
        """Register chunk without hint generates auto ID."""
        registry = ChunkRegistry()
        chunk_data = b"test chunk data"

        chunk_id = registry.register(
            chunk_data=chunk_data,
            category="texture",
        )

        assert chunk_id.startswith("chunk_")
        assert registry.count == 1

    def test_register_chunk_invalid_category(self):
        """Registering with invalid category raises error."""
        registry = ChunkRegistry()
        chunk_data = b"test chunk data"

        with pytest.raises(ValueError, match="Invalid category"):
            registry.register(
                chunk_data=chunk_data,
                category="invalid_category",
            )

    def test_get_chunk_by_id(self):
        """Retrieve chunk entry by ID."""
        registry = ChunkRegistry()
        chunk_data = b"test chunk data"

        chunk_id = registry.register(
            chunk_data=chunk_data,
            category="texture",
            chunk_id_hint="my_chunk",
        )

        entry = registry.get_by_id(chunk_id)
        assert entry is not None
        assert entry.chunk_id == chunk_id

    def test_get_chunk_by_hash(self):
        """Retrieve chunk entry by content hash."""
        registry = ChunkRegistry()
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        registry.register(
            chunk_data=chunk_data,
            category="texture",
            chunk_id_hint="my_chunk",
        )

        entry = registry.get_by_hash(content_hash)
        assert entry is not None
        assert entry.content_hash == content_hash

    def test_get_chunks_by_category(self):
        """Retrieve all chunks in a category."""
        registry = ChunkRegistry()

        registry.register(
            chunk_data=b"texture1", category="texture", chunk_id_hint="t1"
        )
        registry.register(
            chunk_data=b"texture2", category="texture", chunk_id_hint="t2"
        )
        registry.register(chunk_data=b"layout1", category="layout", chunk_id_hint="l1")

        texture_chunks = registry.get_by_category("texture")
        assert len(texture_chunks) == 2

        layout_chunks = registry.get_by_category("layout")
        assert len(layout_chunks) == 1

    def test_duplicate_hash_returns_existing_id(self):
        """Registering same data returns existing chunk ID."""
        registry = ChunkRegistry()
        chunk_data = b"identical chunk data"

        id1 = registry.register(chunk_data=chunk_data, category="texture")
        id2 = registry.register(chunk_data=chunk_data, category="texture")

        assert id1 == id2
        assert registry.count == 1  # No duplicate

    def test_version_increment_on_update(self):
        """Updating chunk with same ID increments version."""
        registry = ChunkRegistry()

        id1 = registry.register(
            chunk_data=b"version 1",
            category="texture",
            chunk_id_hint="updateable_chunk",
        )

        entry1 = registry.get_by_id(id1)
        assert entry1.version == 1

        # Register new data with same hint (simulating update)
        id2 = registry.register(
            chunk_data=b"version 2",
            category="texture",
            chunk_id_hint="updateable_chunk",
            allow_update=True,
        )

        # Same ID, but version incremented
        assert id2 == id1
        entry2 = registry.get_by_id(id1)
        assert entry2.version == 2

    def test_merkle_root_computation(self):
        """Compute Merkle root of all chunks."""
        registry = ChunkRegistry()

        registry.register(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        registry.register(chunk_data=b"chunk2", category="texture", chunk_id_hint="c2")
        registry.register(chunk_data=b"chunk3", category="layout", chunk_id_hint="c3")

        root = registry.compute_merkle_root()
        assert len(root) == 64  # SHA3-256 hex = 64 chars

        # Deterministic
        root2 = registry.compute_merkle_root()
        assert root == root2

    def test_merkle_root_empty_registry(self):
        """Merkle root of empty registry is well-defined."""
        registry = ChunkRegistry()
        root = registry.compute_merkle_root()
        assert len(root) == 64

    def test_export_to_dict(self):
        """Export entire registry to dictionary."""
        registry = ChunkRegistry()
        registry.register(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        registry.register(chunk_data=b"chunk2", category="layout", chunk_id_hint="c2")

        exported = registry.to_dict()

        assert "chunks" in exported
        assert "merkle_root" in exported
        assert "count" in exported
        assert exported["count"] == 2

    def test_import_from_dict(self):
        """Import registry from dictionary."""
        original = ChunkRegistry()
        original.register(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        original.register(chunk_data=b"chunk2", category="layout", chunk_id_hint="c2")

        exported = original.to_dict()

        restored = ChunkRegistry.from_dict(exported)
        assert restored.count == original.count
        assert restored.compute_merkle_root() == original.compute_merkle_root()

    def test_serialization_roundtrip(self):
        """Full serialization roundtrip preserves data."""
        original = ChunkRegistry()
        original.register(chunk_data=b"data1", category="texture", chunk_id_hint="d1")
        original.register(
            chunk_data=b"data2", category="audio_pattern", chunk_id_hint="d2"
        )
        original.register(
            chunk_data=b"data3", category="code_block", chunk_id_hint="d3"
        )

        restored = ChunkRegistry.from_dict(original.to_dict())

        assert restored.count == original.count
        assert restored.compute_merkle_root() == original.compute_merkle_root()

        # Verify individual chunks
        for chunk_id in original.get_all_chunk_ids():
            orig_entry = original.get_by_id(chunk_id)
            rest_entry = restored.get_by_id(chunk_id)
            assert orig_entry.content_hash == rest_entry.content_hash
            assert orig_entry.category == rest_entry.category

    def test_delete_chunk(self):
        """Delete a chunk from registry."""
        registry = ChunkRegistry()
        chunk_id = registry.register(chunk_data=b"to_delete", category="texture")

        assert registry.count == 1
        registry.delete(chunk_id)
        assert registry.count == 0
        assert registry.get_by_id(chunk_id) is None

    def test_delete_nonexistent_chunk(self):
        """Deleting nonexistent chunk raises error."""
        registry = ChunkRegistry()

        with pytest.raises(KeyError):
            registry.delete("nonexistent_chunk")

    def test_get_all_chunk_ids(self):
        """Get list of all chunk IDs."""
        registry = ChunkRegistry()
        ids = []
        for i in range(5):
            chunk_id = registry.register(
                chunk_data=f"chunk{i}".encode(),
                category="texture",
            )
            ids.append(chunk_id)

        all_ids = registry.get_all_chunk_ids()
        assert set(all_ids) == set(ids)

    def test_statistics(self):
        """Get registry statistics."""
        registry = ChunkRegistry()
        registry.register(chunk_data=b"t1", category="texture", chunk_id_hint="t1")
        registry.register(chunk_data=b"t2", category="texture", chunk_id_hint="t2")
        registry.register(chunk_data=b"l1", category="layout", chunk_id_hint="l1")

        stats = registry.get_statistics()

        assert stats["total_chunks"] == 3
        assert stats["by_category"]["texture"] == 2
        assert stats["by_category"]["layout"] == 1

    def test_query_by_tag(self):
        """Query chunks by tag metadata."""
        registry = ChunkRegistry()

        registry.register(
            chunk_data=b"news_header",
            category="layout",
            chunk_id_hint="header1",
            tags=["news", "header", "top"],
        )
        registry.register(
            chunk_data=b"news_footer",
            category="layout",
            chunk_id_hint="footer1",
            tags=["news", "footer", "bottom"],
        )
        registry.register(
            chunk_data=b"ad_banner",
            category="layout",
            chunk_id_hint="ad1",
            tags=["ad", "banner"],
        )

        # Query by tag
        news_chunks = registry.query_by_tag("news")
        assert len(news_chunks) == 2

        header_chunks = registry.query_by_tag("header")
        assert len(header_chunks) == 1

    def test_concurrent_registration_thread_safe(self):
        """Thread-safe concurrent registration."""
        import threading

        registry = ChunkRegistry()
        errors = []

        def register_chunk(i):
            try:
                registry.register(
                    chunk_data=f"thread_{i}".encode(),
                    category="texture",
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_chunk, args=(i,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert registry.count == 10
