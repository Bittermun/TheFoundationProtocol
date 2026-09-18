# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import time
import pytest
from tfp_client.lib.cache.content_cache import ContentCache


class TestContentCacheTTL:
    """Test suite verifying genuine TTL expiration and LRU behavior in ContentCache."""

    def test_cache_hit_within_ttl(self):
        cache = ContentCache(maxsize=10, ttl_seconds=2)
        h = "a" * 64
        cache.put(h, b"payload_data")

        assert h in cache
        assert cache.get(h) == b"payload_data"

    def test_cache_expiration_after_ttl(self):
        cache = ContentCache(maxsize=10, ttl_seconds=1)
        h = "b" * 64
        cache.put(h, b"expiring_payload")

        assert cache.get(h) == b"expiring_payload"
        # Wait for TTL to expire
        time.sleep(1.1)

        assert cache.get(h) is None
        assert h not in cache
        assert cache.stats()["size"] == 0

    def test_lru_eviction_with_capacity(self):
        cache = ContentCache(maxsize=2, ttl_seconds=100)
        cache.put("1" * 64, b"one")
        cache.put("2" * 64, b"two")

        # Access 1 to mark it recently used
        assert cache.get("1" * 64) == b"one"

        # Insert 3, should evict 2 (least recently used)
        cache.put("3" * 64, b"three")

        assert cache.get("1" * 64) == b"one"
        assert cache.get("3" * 64) == b"three"
        assert cache.get("2" * 64) is None
