# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Chunk Cache Manager - LRU eviction + Credit reward for pinning rare chunks

Provides efficient chunk caching with:
- LRU (Least Recently Used) eviction policy
- Bloom filter for fast existence checks
- Rare-chunk credit rewards
- Thread-safe concurrent access
"""

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Import BloomFilter from metadata module
try:
    from tfp_client.lib.metadata.bloom_filter import BloomFilter
except ImportError:
    # Fallback if bloom_filter not available
    class BloomFilter:
        """Minimal fallback Bloom filter."""

        def __init__(self, *args, **kwargs):
            self._items = set()

        def add(self, item):
            self._items.add(hash(item))

        def __contains__(self, item):
            return hash(item) in self._items


@dataclass
class ChunkCacheEntry:
    """
    Represents a cached chunk entry.

    Attributes:
        chunk_id: Unique identifier for the chunk
        content_hash: SHA3-256 hash of the chunk data
        data: Raw chunk data bytes
        category: Category name (texture, layout, etc.)
        access_count: Number of times this chunk has been accessed
        last_access_time: Timestamp of last access
        pinned: Whether this chunk is pinned (protected from eviction)
    """

    chunk_id: str
    content_hash: str
    data: bytes
    category: str
    access_count: int = 0
    last_access_time: float = field(default_factory=time.time)
    pinned: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize entry to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "data": self.data,
            "category": self.category,
            "access_count": self.access_count,
            "last_access_time": self.last_access_time,
            "pinned": self.pinned,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkCacheEntry":
        """Deserialize entry from dictionary."""
        return cls(
            chunk_id=data["chunk_id"],
            content_hash=data["content_hash"],
            data=data["data"],
            category=data["category"],
            access_count=data.get("access_count", 0),
            last_access_time=data.get("last_access_time", time.time()),
            pinned=data.get("pinned", False),
        )


class LRUEvictionPolicy:
    """
    LRU (Least Recently Used) eviction policy tracker.

    Maintains access order to determine which items should be evicted first.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize LRU policy.

        Args:
            max_size: Maximum number of items to track
        """
        self._max_size = max_size
        self._access_order: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def track_access(self, chunk_id: str) -> None:
        """
        Track an access event for a chunk.

        Moves the chunk to the most-recently-used position.

        Args:
            chunk_id: ID of the accessed chunk
        """
        with self._lock:
            # Remove if exists (to re-add at end)
            if chunk_id in self._access_order:
                del self._access_order[chunk_id]

            # Add at end (most recently used)
            self._access_order[chunk_id] = time.time()

            # Trim if exceeds max size
            while len(self._access_order) > self._max_size:
                self._access_order.popitem(last=False)

    def remove(self, chunk_id: str) -> None:
        """
        Remove a chunk from the policy.

        Args:
            chunk_id: ID of chunk to remove
        """
        with self._lock:
            if chunk_id in self._access_order:
                del self._access_order[chunk_id]

    def get_victim(self) -> Optional[str]:
        """
        Get the least-recently-used chunk ID for eviction.

        Returns:
            Chunk ID of LRU item, or None if empty
        """
        with self._lock:
            if not self._access_order:
                return None
            # First item is LRU
            return next(iter(self._access_order))


class ChunkStore:
    """
    Thread-safe chunk cache with LRU eviction and credit rewards.

    Features:
    - LRU eviction by count and byte size
    - Bloom filter for fast existence checks
    - Rare-chunk credit rewards
    - Eviction callbacks
    - Category-based queries
    """

    def __init__(
        self,
        max_chunks: int = 1000,
        max_bytes: int = 10_000_000,
        eviction_callback: Optional[Callable[[str, ChunkCacheEntry], None]] = None,
    ):
        """
        Initialize chunk store.

        Args:
            max_chunks: Maximum number of chunks to cache
            max_bytes: Maximum total bytes to cache
            eviction_callback: Optional callback(chunk_id, entry) on eviction
        """
        self._max_chunks = max_chunks
        self._max_bytes = max_bytes
        self._eviction_callback = eviction_callback

        self._chunks: Dict[str, ChunkCacheEntry] = {}
        self._total_bytes = 0
        self._lock = threading.RLock()

        # LRU policy
        self._lru = LRUEvictionPolicy(max_size=max_chunks)

        # Bloom filter for fast existence checks
        # Estimate 1% false positive rate
        bloom_size = BloomFilter.optimal_size(n=max_chunks, p=0.01)
        bloom_hashes = BloomFilter.optimal_hash_count(m=bloom_size, n=max_chunks)
        self._bloom = BloomFilter(size_bits=bloom_size, hash_count=bloom_hashes)

    def __contains__(self, chunk_id: str) -> bool:
        """
        Check if a chunk exists in the cache using 'in' operator.

        Args:
            chunk_id: ID to check

        Returns:
            True if chunk exists, False otherwise
        """
        return self.contains(chunk_id)

    @property
    def count(self) -> int:
        """Get current number of cached chunks."""
        with self._lock:
            return len(self._chunks)

    @property
    def total_bytes(self) -> int:
        """Get total bytes currently cached."""
        with self._lock:
            return self._total_bytes

    def put(
        self,
        chunk_data: bytes,
        category: str,
        chunk_id_hint: Optional[str] = None,
    ) -> str:
        """
        Store a chunk in the cache.

        Args:
            chunk_data: Raw chunk data bytes
            category: Category name
            chunk_id_hint: Optional hint for chunk ID (auto-generated if None)

        Returns:
            The chunk ID
        """
        import uuid

        # Generate or use provided chunk ID
        if chunk_id_hint:
            chunk_id = chunk_id_hint
        else:
            chunk_id = f"cached_{uuid.uuid4().hex[:8]}"

        # Compute content hash
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()

        # Create entry
        entry = ChunkCacheEntry(
            chunk_id=chunk_id,
            content_hash=content_hash,
            data=chunk_data,
            category=category,
            access_count=1,  # Initial access from put
            last_access_time=time.time(),
        )

        with self._lock:
            # Check if updating existing chunk
            if chunk_id in self._chunks:
                old_entry = self._chunks[chunk_id]
                self._total_bytes -= (
                    old_entry.size_bytes
                    if hasattr(old_entry, "size_bytes")
                    else len(old_entry.data)
                )

            # Store chunk
            self._chunks[chunk_id] = entry
            self._total_bytes += len(chunk_data)

            # Update LRU
            self._lru.track_access(chunk_id)

            # Update Bloom filter
            self._bloom.add(chunk_id)

            # Enforce limits
            self._enforce_limits()

        return chunk_id

    def get(self, chunk_id: str) -> Optional[ChunkCacheEntry]:
        """
        Retrieve a chunk from the cache.

        Args:
            chunk_id: ID of chunk to retrieve

        Returns:
            ChunkCacheEntry if found, None otherwise
        """
        with self._lock:
            entry = self._chunks.get(chunk_id)
            if entry:
                # Update access tracking
                entry.access_count += 1
                entry.last_access_time = time.time()
                self._lru.track_access(chunk_id)
            return entry

    def get_chunk(self, chunk_id: str) -> ChunkCacheEntry:
        """
        Retrieve a chunk from the cache (raises if not found).

        Args:
            chunk_id: ID of chunk to retrieve

        Returns:
            ChunkCacheEntry

        Raises:
            KeyError: If chunk not found
        """
        entry = self.get(chunk_id)
        if entry is None:
            raise KeyError(f"Chunk '{chunk_id}' not found")
        return entry

    def contains(self, chunk_id: str) -> bool:
        """
        Check if a chunk exists in the cache.

        Args:
            chunk_id: ID to check

        Returns:
            True if chunk exists, False otherwise
        """
        with self._lock:
            return chunk_id in self._chunks

    def probably_exists(self, chunk_id: str) -> bool:
        """
        Fast probabilistic existence check using Bloom filter.

        May return false positives but never false negatives.

        Args:
            chunk_id: ID to check

        Returns:
            True if chunk probably exists, False if definitely doesn't
        """
        with self._lock:
            return self._bloom.contains(chunk_id)

    def delete(self, chunk_id: str) -> None:
        """
        Delete a chunk from the cache.

        Args:
            chunk_id: ID of chunk to delete

        Raises:
            KeyError: If chunk doesn't exist
        """
        with self._lock:
            if chunk_id not in self._chunks:
                raise KeyError(f"Chunk '{chunk_id}' not found")

            entry = self._chunks.pop(chunk_id)
            self._total_bytes -= len(entry.data)
            self._lru.remove(chunk_id)

    def clear(self) -> None:
        """Clear all chunks from the cache."""
        with self._lock:
            self._chunks.clear()
            self._total_bytes = 0
            # Reinitialize Bloom filter
            bloom_size = BloomFilter.optimal_size(n=self._max_chunks, p=0.01)
            bloom_hashes = BloomFilter.optimal_hash_count(
                m=bloom_size, n=self._max_chunks
            )
            self._bloom = BloomFilter(size_bits=bloom_size, hash_count=bloom_hashes)

    def get_by_category(self, category: str) -> List[ChunkCacheEntry]:
        """
        Get all chunks in a category.

        Args:
            category: Category name to filter by

        Returns:
            List of ChunkCacheEntry objects
        """
        with self._lock:
            return [
                entry for entry in self._chunks.values() if entry.category == category
            ]

    def calculate_pin_reward(self, chunk_id: str) -> float:
        """
        Calculate credit reward for pinning a chunk.

        Rare chunks (low access count) earn higher rewards.

        Formula: reward = base_rate / (access_count + 1)

        Args:
            chunk_id: ID of chunk to calculate reward for

        Returns:
            Credit reward value
        """
        with self._lock:
            entry = self._chunks.get(chunk_id)
            if not entry:
                return 0.0

            # Base reward
            base_rate = 1.0

            # Rarity multiplier: inverse of access count
            rarity_multiplier = 1.0 / (entry.access_count + 1)

            return base_rate * rarity_multiplier

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            by_category: Dict[str, int] = {}

            for entry in self._chunks.values():
                cat = entry.category
                by_category[cat] = by_category.get(cat, 0) + 1

            return {
                "count": len(self._chunks),
                "total_bytes": self._total_bytes,
                "max_chunks": self._max_chunks,
                "max_bytes": self._max_bytes,
                "by_category": by_category,
                "utilization_chunks": len(self._chunks) / self._max_chunks
                if self._max_chunks > 0
                else 0,
                "utilization_bytes": self._total_bytes / self._max_bytes
                if self._max_bytes > 0
                else 0,
            }

    def _enforce_limits(self) -> None:
        """
        Enforce size and byte limits through LRU eviction.

        Must be called with lock held.
        """
        evicted = []

        # Evict by chunk count
        while len(self._chunks) > self._max_chunks:
            victim = self._lru.get_victim()
            if not victim or victim not in self._chunks:
                break

            entry = self._chunks.pop(victim)
            self._total_bytes -= len(entry.data)
            self._lru.remove(victim)
            evicted.append((victim, entry))

        # Evict by byte size
        while self._total_bytes > self._max_bytes and self._chunks:
            victim = self._lru.get_victim()
            if not victim or victim not in self._chunks:
                break

            entry = self._chunks.pop(victim)
            self._total_bytes -= len(entry.data)
            self._lru.remove(victim)
            evicted.append((victim, entry))

        # Call eviction callbacks
        if self._eviction_callback and evicted:
            for chunk_id, entry in evicted:
                try:
                    self._eviction_callback(chunk_id, entry)
                except Exception:
                    pass  # Don't let callback errors break eviction


# Add property for size_bytes on entry
def _entry_size_bytes(self) -> int:
    return len(self.data)


ChunkCacheEntry.size_bytes = property(_entry_size_bytes)
