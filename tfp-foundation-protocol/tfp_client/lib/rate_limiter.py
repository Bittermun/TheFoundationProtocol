"""
TFP Rate Limiter - Pluggable backend (memory/Redis)
Supports atomic sliding window with Redis Lua scripts for production.
"""
import time
from typing import Optional, Protocol
import hashlib

class RateLimiterBackend(Protocol):
    """Interface for rate limiter backends."""
    def is_allowed(self, key: str, max_calls: int, window_seconds: int) -> bool:
        """Return True if request is allowed, False if rate limited."""
        ...

class MemoryRateLimiter:
    """In-memory sliding window rate limiter (dev/test)."""
    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}
    
    def is_allowed(self, key: str, max_calls: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        
        if key not in self._windows:
            self._windows[key] = []
        
        # Clean old entries
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]
        
        if len(self._windows[key]) >= max_calls:
            return False
        
        self._windows[key].append(now)
        return True

class RedisRateLimiter:
    """
    Redis-backed rate limiter using atomic Lua script.
    Production-ready: survives restarts, no race conditions.
    """
    LUA_SCRIPT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local max_calls = tonumber(ARGV[3])
    local cutoff = now - window
    
    -- Remove old entries
    redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
    
    -- Count current entries
    local count = redis.call('ZCARD', key)
    
    if count >= max_calls then
        return 0
    end
    
    -- Add new entry
    redis.call('ZADD', key, now, now .. ':' .. math.random())
    redis.call('EXPIRE', key, window + 1)
    
    return 1
    """
    
    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        self._script = self._redis.register_script(self.LUA_SCRIPT)
    
    def is_allowed(self, key: str, max_calls: int, window_seconds: int) -> bool:
        now = time.time()
        key_hash = f"tfp:ratelimit:{hashlib.sha256(key.encode()).hexdigest()[:16]}"
        result = self._script(
            keys=[key_hash],
            args=[now, window_seconds, max_calls]
        )
        return bool(result)

def get_rate_limiter(backend: str = "memory", redis_client=None):
    """Factory function to get appropriate rate limiter."""
    if backend == "redis":
        if redis_client is None:
            raise ValueError("Redis client required for redis backend")
        return RedisRateLimiter(redis_client)
    else:
        return MemoryRateLimiter()
