"""
Tests for Chunk Cache Manager - LRU eviction + Credit reward for pinning rare chunks

TDD: Tests written before implementation.
"""

import hashlib
import time

import pytest
from tfp_client.lib.cache.chunk_store import (
    ChunkCacheEntry,
    ChunkStore,
    LRUEvictionPolicy,
)


class TestChunkCacheEntry:
    """Test individual cache entry structure."""

    def test_create_cache_entry(self):
        """Create a valid cache entry."""
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        entry = ChunkCacheEntry(
            chunk_id="test_chunk",
            content_hash=content_hash,
            data=chunk_data,
            category="texture",
        )

        assert entry.chunk_id == "test_chunk"
        assert entry.content_hash == content_hash
        assert entry.data == chunk_data
        assert entry.category == "texture"
        assert entry.access_count == 0
        assert entry.last_access_time > 0

    def test_entry_serialization(self):
        """Serialize and deserialize cache entry."""
        chunk_data = b"test chunk data"
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        entry = ChunkCacheEntry(
            chunk_id="test_chunk",
            content_hash=content_hash,
            data=chunk_data,
            category="texture",
        )

        # Serialize
        serialized = entry.to_dict()
        assert "chunk_id" in serialized
        assert "data" in serialized

        # Deserialize
        restored = ChunkCacheEntry.from_dict(serialized)
        assert restored.chunk_id == entry.chunk_id
        assert restored.data == entry.data
        assert restored.content_hash == entry.content_hash


class TestLRUEvictionPolicy:
    """Test LRU eviction policy."""

    def test_track_access_updates_order(self):
        """Accessing an item moves it to most recently used."""
        policy = LRUEvictionPolicy(max_size=3)

        # Add items
        policy.track_access("item1")
        policy.track_access("item2")
        policy.track_access("item3")

        # Access item1 again (should move to end)
        policy.track_access("item1")

        # Now item2 should be least recently used
        assert policy.get_victim() == "item2"

    def test_get_victim_returns_lru(self):
        """Get victim returns least recently used item."""
        policy = LRUEvictionPolicy(max_size=3)

        policy.track_access("first")
        policy.track_access("second")
        policy.track_access("third")

        # First added is LRU
        assert policy.get_victim() == "first"

    def test_remove_item(self):
        """Remove item from policy."""
        policy = LRUEvictionPolicy(max_size=3)

        policy.track_access("item1")
        policy.track_access("item2")

        policy.remove("item1")

        # item1 should no longer be in policy
        policy.track_access("item3")
        assert policy.get_victim() == "item2"  # item2 is now LRU

    def test_max_size_enforcement(self):
        """Policy respects max size."""
        policy = LRUEvictionPolicy(max_size=2)

        policy.track_access("item1")
        policy.track_access("item2")
        policy.track_access("item3")  # Exceeds max

        # Should still only track 2 items internally
        victims = []
        while True:
            victim = policy.get_victim()
            if victim is None:
                break
            victims.append(victim)
            policy.remove(victim)

        assert len(victims) == 2


class TestChunkStore:
    """Test the main chunk store functionality."""

    def test_create_empty_store(self):
        """Create an empty chunk store with default capacity."""
        store = ChunkStore(max_chunks=100, max_bytes=1000000)
        assert store.count == 0
        assert store.total_bytes == 0

    def test_store_chunk(self):
        """Store a chunk in the cache."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)
        chunk_data = b"test chunk data for caching"

        chunk_id = store.put(
            chunk_data=chunk_data,
            category="texture",
            chunk_id_hint="cached_chunk",
        )

        assert chunk_id is not None
        assert store.count == 1
        assert store.total_bytes == len(chunk_data)

    def test_get_stored_chunk(self):
        """Retrieve a stored chunk by ID."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)
        chunk_data = b"retrievable chunk data"

        chunk_id = store.put(
            chunk_data=chunk_data,
            category="layout",
            chunk_id_hint="retrievable",
        )

        retrieved = store.get(chunk_id)
        assert retrieved is not None
        assert retrieved.data == chunk_data

    def test_get_nonexistent_chunk(self):
        """Getting nonexistent chunk returns None."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)
        retrieved = store.get("nonexistent_chunk")
        assert retrieved is None

    def test_contains_check(self):
        """Check if chunk exists in store."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)
        chunk_id = store.put(chunk_data=b"data", category="texture")

        assert store.contains(chunk_id) is True
        assert store.contains("nonexistent") is False

    def test_lru_eviction_by_count(self):
        """LRU eviction when max_chunks exceeded."""
        store = ChunkStore(max_chunks=3, max_bytes=1000000)

        # Fill store
        store.put(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        store.put(chunk_data=b"chunk2", category="texture", chunk_id_hint="c2")
        store.put(chunk_data=b"chunk3", category="texture", chunk_id_hint="c3")

        # Access c1 to make it recently used
        store.get("c1")

        # Add new chunk - should evict c2 (LRU, since c1 was accessed, c3 was added last)
        store.put(chunk_data=b"chunk4", category="texture", chunk_id_hint="c4")

        assert store.count == 3
        assert store.contains("c1") is True  # Accessed recently
        # c2 or c3 could be evicted depending on exact LRU ordering
        # c2 was accessed before c3, so c2 is LRU
        evicted_count = sum(
            [
                not store.contains("c2"),
                not store.contains("c3"),
            ]
        )
        assert evicted_count >= 1  # At least one was evicted
        assert store.contains("c4") is True

    def test_lru_eviction_by_bytes(self):
        """LRU eviction when max_bytes exceeded."""
        store = ChunkStore(max_chunks=100, max_bytes=100)

        # Add chunks that exceed byte limit
        store.put(chunk_data=b"a" * 40, category="texture", chunk_id_hint="big1")
        store.put(chunk_data=b"b" * 40, category="texture", chunk_id_hint="big2")
        store.put(
            chunk_data=b"c" * 40, category="texture", chunk_id_hint="big3"
        )  # Should trigger eviction

        # Should have evicted at least one chunk
        assert store.total_bytes <= 100

    def test_update_existing_chunk(self):
        """Updating existing chunk replaces data."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        chunk_id = store.put(
            chunk_data=b"version1", category="texture", chunk_id_hint="updatable"
        )
        initial_time = store.get(chunk_id).last_access_time

        time.sleep(0.01)  # Small delay to ensure different timestamp

        # Update with same ID
        store.put(chunk_data=b"version2", category="texture", chunk_id_hint="updatable")

        retrieved = store.get(chunk_id)
        assert retrieved.data == b"version2"
        assert retrieved.last_access_time > initial_time

    def test_delete_chunk(self):
        """Delete a chunk from store."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)
        chunk_id = store.put(chunk_data=b"to_delete", category="texture")

        assert store.count == 1
        store.delete(chunk_id)
        assert store.count == 0
        assert store.contains(chunk_id) is False

    def test_delete_nonexistent_chunk(self):
        """Deleting nonexistent chunk raises KeyError."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        with pytest.raises(KeyError):
            store.delete("nonexistent_chunk")

    def test_clear_store(self):
        """Clear all chunks from store."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        store.put(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        store.put(chunk_data=b"chunk2", category="layout", chunk_id_hint="c2")
        store.put(chunk_data=b"chunk3", category="texture", chunk_id_hint="c3")

        store.clear()

        assert store.count == 0
        assert store.total_bytes == 0

    def test_get_by_category(self):
        """Get all chunks in a category."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        store.put(chunk_data=b"t1", category="texture", chunk_id_hint="t1")
        store.put(chunk_data=b"t2", category="texture", chunk_id_hint="t2")
        store.put(chunk_data=b"l1", category="layout", chunk_id_hint="l1")

        texture_chunks = store.get_by_category("texture")
        assert len(texture_chunks) == 2

        layout_chunks = store.get_by_category("layout")
        assert len(layout_chunks) == 1

    def test_statistics(self):
        """Get store statistics."""
        store = ChunkStore(max_chunks=100, max_bytes=10000)

        store.put(chunk_data=b"a" * 100, category="texture", chunk_id_hint="t1")
        store.put(chunk_data=b"b" * 200, category="layout", chunk_id_hint="l1")
        store.put(chunk_data=b"c" * 150, category="texture", chunk_id_hint="t2")

        stats = store.get_statistics()

        assert stats["count"] == 3
        assert stats["total_bytes"] == 450
        assert stats["max_chunks"] == 100
        assert stats["max_bytes"] == 10000
        assert stats["by_category"]["texture"] == 2
        assert stats["by_category"]["layout"] == 1

    def test_rare_chunk_credit_reward(self):
        """Rare chunks earn higher credit rewards."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        # Common chunk (accessed many times)
        common_id = store.put(
            chunk_data=b"common", category="texture", chunk_id_hint="common"
        )
        for _ in range(100):
            store.get(common_id)

        # Rare chunk (accessed once)
        rare_id = store.put(
            chunk_data=b"rare", category="texture", chunk_id_hint="rare"
        )
        store.get(rare_id)

        # Get credit rewards
        common_reward = store.calculate_pin_reward(common_id)
        rare_reward = store.calculate_pin_reward(rare_id)

        # Rare chunk should earn more
        assert rare_reward > common_reward

    def test_bloom_filter_existence_check(self):
        """Bloom filter provides fast existence checks."""
        store = ChunkStore(max_chunks=100, max_bytes=10000)

        id1 = store.put(chunk_data=b"chunk1", category="texture")
        id2 = store.put(chunk_data=b"chunk2", category="layout")

        # Bloom filter should indicate possible existence
        assert store.probably_exists(id1) is True
        assert store.probably_exists(id2) is True

        # Nonexistent chunk should return False (no false negatives)
        assert store.probably_exists("definitely_not_here") is False

    def test_access_count_tracking(self):
        """Track access count for each chunk."""
        store = ChunkStore(max_chunks=10, max_bytes=10000)

        chunk_id = store.put(
            chunk_data=b"tracked", category="texture", chunk_id_hint="tracked"
        )

        # Initial access count should be 1 (from put)
        entry = store.get(chunk_id)
        assert entry.access_count >= 1

        # Additional accesses increment counter
        store.get(chunk_id)
        store.get(chunk_id)

        entry = store.get(chunk_id)
        assert entry.access_count >= 3

    def test_concurrent_access_thread_safe(self):
        """Thread-safe concurrent access."""
        import threading

        store = ChunkStore(max_chunks=1000, max_bytes=1000000)
        errors = []

        def store_chunk(i):
            try:
                chunk_id = store.put(
                    chunk_data=f"thread_{i}".encode(),
                    category="texture",
                )
                store.get(chunk_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=store_chunk, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert store.count == 50

    def test_eviction_callback(self):
        """Callback triggered on eviction."""
        evicted_ids = []

        def on_evict(chunk_id, entry):
            evicted_ids.append(chunk_id)

        store = ChunkStore(
            max_chunks=2,
            max_bytes=1000000,
            eviction_callback=on_evict,
        )

        store.put(chunk_data=b"chunk1", category="texture", chunk_id_hint="c1")
        store.put(chunk_data=b"chunk2", category="texture", chunk_id_hint="c2")
        store.put(
            chunk_data=b"chunk3", category="texture", chunk_id_hint="c3"
        )  # Triggers eviction

        assert len(evicted_ids) >= 1
        # Either c1 or c2 should be evicted (both were LRU at some point)
        assert "c1" in evicted_ids or "c2" in evicted_ids
