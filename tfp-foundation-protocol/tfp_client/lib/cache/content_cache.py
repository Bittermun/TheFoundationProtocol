# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
ContentCache - Thread-safe LRU cache for TFP content retrieval.

Uses collections.OrderedDict for proper LRU eviction with thread safety.
Reduces redundant BlobStore and IPFS lookups for hot content.

Usage:
    cache = ContentCache(maxsize=1000)
    cache.put(content_hash, content_bytes)
    content = cache.get(content_hash)
"""

import logging
import threading
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class ContentCache:
    """
    Thread-safe LRU cache for TFP content using OrderedDict.

    Provides thread-safe caching with automatic LRU eviction when the cache is full.
    Uses content hash as the cache key.

    Args:
        maxsize: Maximum number of items to cache (default: 1000)
        ttl_seconds: Optional time-to-live in seconds (not implemented, reserved for future)
    """

    def __init__(self, maxsize: int = 1000, ttl_seconds: Optional[int] = None):
        self._maxsize = maxsize
        self._ttl_seconds = ttl_seconds
        self._cache_store: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, content_hash: str) -> Optional[bytes]:
        """
        Retrieve content from cache.

        Args:
            content_hash: SHA3-256 content hash

        Returns:
            Cached content bytes, or None if not in cache
        """
        with self._lock:
            if content_hash in self._cache_store:
                # Move to end to mark as recently used (LRU)
                self._cache_store.move_to_end(content_hash)
                return self._cache_store[content_hash]
            return None

    def put(self, content_hash: str, content: bytes) -> None:
        """
        Store content in cache.

        Args:
            content_hash: SHA3-256 content hash
            content: Content bytes to cache
        """
        if not content:
            logger.warning("ContentCache: refusing to cache empty content")
            return

        with self._lock:
            # Store and move to end (recently used)
            self._cache_store[content_hash] = content
            self._cache_store.move_to_end(content_hash)

            # Evict oldest if over limit (LRU eviction)
            if len(self._cache_store) > self._maxsize:
                oldest_key, _ = self._cache_store.popitem(last=False)
                logger.debug(
                    "ContentCache: evicted oldest entry %s (cache size: %d)",
                    oldest_key[:16],
                    len(self._cache_store),
                )

    def invalidate(self, content_hash: str) -> None:
        """
        Remove a specific entry from the cache.

        Args:
            content_hash: SHA3-256 content hash to invalidate
        """
        with self._lock:
            if content_hash in self._cache_store:
                del self._cache_store[content_hash]
                logger.debug("ContentCache: invalidated entry %s", content_hash[:16])

    def clear(self) -> None:
        """Clear all cached content."""
        with self._lock:
            self._cache_store.clear()
            logger.debug("ContentCache: cleared all entries")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache size, maxsize
        """
        with self._lock:
            return {
                "size": len(self._cache_store),
                "maxsize": self._maxsize,
            }

    def __contains__(self, content_hash: str) -> bool:
        """Check if content hash is in cache."""
        with self._lock:
            return content_hash in self._cache_store


# Global singleton cache instance (can be overridden in tests)
_global_cache: Optional[ContentCache] = None
_global_cache_lock = threading.Lock()


def get_global_cache(maxsize: int = 1000) -> ContentCache:
    """
    Get or create the global content cache singleton.

    Args:
        maxsize: Maximum cache size (only used on first call)

    Returns:
        Global ContentCache instance
    """
    global _global_cache
    with _global_cache_lock:
        if _global_cache is None:
            _global_cache = ContentCache(maxsize=maxsize)
        return _global_cache


def reset_global_cache() -> None:
    """Reset the global cache (useful for testing)."""
    global _global_cache
    with _global_cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
        _global_cache = None
