"""
Test rate limiter backends (memory and Redis).
"""

import time
import pytest
from tfp_client.lib.rate_limiter import MemoryRateLimiter, get_rate_limiter


class TestMemoryRateLimiter:
    def test_allows_under_limit(self):
        limiter = MemoryRateLimiter()
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True

    def test_blocks_over_limit(self):
        limiter = MemoryRateLimiter()
        for _ in range(3):
            assert limiter.is_allowed("user2", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user2", max_calls=3, window_seconds=60) is False

    def test_window_expires(self):
        limiter = MemoryRateLimiter()
        # Use up limit
        for _ in range(3):
            limiter.is_allowed("user3", max_calls=3, window_seconds=1)
        assert limiter.is_allowed("user3", max_calls=3, window_seconds=1) is False

        # Wait for window to expire
        time.sleep(1.1)
        assert limiter.is_allowed("user3", max_calls=3, window_seconds=1) is True

    def test_different_keys_independent(self):
        limiter = MemoryRateLimiter()
        for _ in range(5):
            limiter.is_allowed("userA", max_calls=5, window_seconds=60)

        # Different user should not be affected
        assert limiter.is_allowed("userB", max_calls=5, window_seconds=60) is True


try:
    import fakeredis

    FAKE_REDIS_AVAILABLE = True
except ImportError:
    FAKE_REDIS_AVAILABLE = False


@pytest.mark.skipif(not FAKE_REDIS_AVAILABLE, reason="fakeredis not installed")
class TestRedisRateLimiter:
    @pytest.fixture
    def redis_client(self):
        client = fakeredis.FakeRedis()
        yield client
        client.flushall()

    def test_allows_under_limit(self, redis_client):
        limiter = get_rate_limiter("redis", redis_client)
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user1", max_calls=3, window_seconds=60) is True

    def test_blocks_over_limit(self, redis_client):
        limiter = get_rate_limiter("redis", redis_client)
        for _ in range(3):
            assert limiter.is_allowed("user2", max_calls=3, window_seconds=60) is True
        assert limiter.is_allowed("user2", max_calls=3, window_seconds=60) is False

    def test_different_keys_independent(self, redis_client):
        limiter = get_rate_limiter("redis", redis_client)
        for _ in range(5):
            limiter.is_allowed("userA", max_calls=5, window_seconds=60)

        assert limiter.is_allowed("userB", max_calls=5, window_seconds=60) is True
