"""
Distributed Rate Limiter with Redis Backend for TFP.

Implements sliding window counter algorithm for accurate, low-memory rate limiting
across multiple daemon instances. Protects against DDoS, brute-force attacks on
task dispatch, shard verification, and HABP consensus endpoints.

Algorithm: Sliding Window Counter (Redis official recommendation)
- More accurate than fixed window
- Better memory efficiency than token bucket for bursty workloads
- Atomic execution via Lua scripts

Key format: rate:{client_type}:{client_id}:{endpoint}
Limits: Configurable per endpoint (e.g., 30 tasks/min per device)
Fallback: Configurable fail-open/closed on Redis outage
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from redis import ConnectionPool, Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Default limits per endpoint type
DEFAULT_LIMITS = {
    "task_submit": (30, 60),  # 30 requests per 60 seconds
    "shard_verify": (50, 60),  # 50 verifications per 60 seconds
    "habp_consensus": (100, 60),  # 100 consensus messages per 60 seconds
    "api_general": (100, 60),  # 100 general API calls per 60 seconds
}

# Lua script for atomic sliding window counter
# Uses two windows: current and previous for smooth transitions
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_size = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

local current_window_start = math.floor(now / window_size) * window_size
local previous_window_start = current_window_start - window_size

local current_key = key .. ':' .. current_window_start
local previous_key = key .. ':' .. previous_window_start

-- Get counts from both windows
local current_count = tonumber(redis.call('GET', current_key) or '0')
local previous_count = tonumber(redis.call('GET', previous_key) or '0')

-- Calculate weighted count based on position in current window
local elapsed = now - current_window_start
local weight = (window_size - elapsed) / window_size
local weighted_count = previous_count * weight + current_count

if weighted_count >= limit then
    return {0, weighted_count, limit}
end

-- Increment current window
redis.call('INCR', current_key)
redis.call('EXPIRE', current_key, window_size * 2)

return {1, weighted_count + 1, limit}
"""


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    current_count: float
    limit: int
    retry_after: Optional[float] = None


class DistributedRateLimiter:
    """
    Distributed rate limiter using Redis sliding window counter.

    Thread-safe, atomic operations via Lua scripts.
    Supports graceful degradation on Redis failures.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_limits: dict = DEFAULT_LIMITS,
        fail_open: bool = True,
        connection_pool_size: int = 10,
    ):
        """
        Initialize rate limiter.

        Args:
            redis_url: Redis connection URL
            default_limits: Default limits per endpoint type
            fail_open: Allow requests if Redis is unavailable (True) or deny (False)
            connection_pool_size: Size of Redis connection pool
        """
        self.redis_url = redis_url
        self.default_limits = default_limits
        self.fail_open = fail_open
        self._connection_pool_size = connection_pool_size
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[Redis] = None
        self._script_sha: Optional[str] = None

    def _get_client(self) -> Redis:
        """Get or create Redis client with connection pooling."""
        if self._client is None:
            self._pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self._connection_pool_size,
                decode_responses=False,
            )
            self._client = Redis(connection_pool=self._pool)
            self._load_script()
        return self._client

    def _load_script(self) -> None:
        """Load Lua script into Redis and cache SHA."""
        try:
            client = self._get_client()
            self._script_sha = client.script_load(SLIDING_WINDOW_SCRIPT)
            logger.debug("Rate limiter Lua script loaded")
        except RedisError as e:
            logger.warning(f"Failed to load rate limit script: {e}")
            raise

    def check_rate_limit(
        self,
        client_id: str,
        endpoint_type: str = "api_general",
        custom_limit: Optional[Tuple[int, int]] = None,
    ) -> RateLimitResult:
        """
        Check if request is within rate limit.

        Args:
            client_id: Unique client identifier (PUF-derived, HMAC key, or IP)
            endpoint_type: Type of endpoint (task_submit, shard_verify, etc.)
            custom_limit: Override default limit as (limit, window_seconds)

        Returns:
            RateLimitResult with allowed status and metadata
        """
        limit, window_size = custom_limit or self.default_limits.get(
            endpoint_type, DEFAULT_LIMITS["api_general"]
        )

        key = f"rate:{endpoint_type}:{client_id}"
        now = time.time()

        try:
            client = self._get_client()
            result = client.evalsha(
                self._script_sha,
                1,
                key,
                now,
                window_size,
                limit,
            )

            allowed = bool(result[0])
            current_count = float(result[1])
            limit_val = int(result[2])

            if not allowed:
                # Calculate retry-after based on window position
                elapsed = now % window_size
                retry_after = window_size - elapsed
                logger.info(
                    f"Rate limit exceeded for {client_id}/{endpoint_type}: "
                    f"{current_count:.1f}/{limit}"
                )
                return RateLimitResult(
                    allowed=False,
                    current_count=current_count,
                    limit=limit_val,
                    retry_after=retry_after,
                )

            return RateLimitResult(
                allowed=True,
                current_count=current_count,
                limit=limit_val,
            )

        except RedisError as e:
            logger.error(f"Redis error during rate limit check: {e}")
            if self.fail_open:
                logger.warning("Failing open due to Redis unavailability")
                return RateLimitResult(
                    allowed=True,
                    current_count=0,
                    limit=limit,
                )
            else:
                logger.warning("Failing closed due to Redis unavailability")
                return RateLimitResult(
                    allowed=False,
                    current_count=0,
                    limit=limit,
                    retry_after=5.0,
                )

    def get_remaining(
        self,
        client_id: str,
        endpoint_type: str = "api_general",
    ) -> Tuple[int, int]:
        """
        Get remaining requests and reset time.

        Returns:
            Tuple of (remaining_requests, reset_timestamp)
        """
        limit, window_size = self.default_limits.get(
            endpoint_type, DEFAULT_LIMITS["api_general"]
        )

        key = f"rate:{endpoint_type}:{client_id}"
        now = time.time()
        current_window_start = int(now / window_size) * window_size

        try:
            client = self._get_client()
            current_key = f"{key}:{current_window_start}"
            current_count = int(client.get(current_key) or 0)

            remaining = max(0, limit - current_count)
            reset_time = current_window_start + window_size

            return remaining, int(reset_time)

        except RedisError as e:
            logger.error(f"Redis error getting remaining: {e}")
            return limit, int(now + window_size)

    def close(self) -> None:
        """Close Redis connections."""
        if self._pool:
            self._pool.disconnect()
            self._pool = None
            self._client = None


# FastAPI middleware integration
def create_rate_limit_middleware(limiter: DistributedRateLimiter):
    """
    Create FastAPI middleware for rate limiting.

    Usage:
        app = FastAPI()
        limiter = DistributedRateLimiter()
        app.add_middleware(create_rate_limit_middleware(limiter))
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Extract client ID (PUF identity, HMAC key, or IP fallback)
            client_id = (
                request.headers.get("x-tfp-client-id")
                or request.headers.get("x-forwarded-for", "unknown")
                .split(",")[0]
                .strip()
            )

            # Determine endpoint type from path
            path = request.url.path
            if "/task" in path:
                endpoint_type = "task_submit"
            elif "/shard" in path or "/verify" in path:
                endpoint_type = "shard_verify"
            elif "/consensus" in path or "/habp" in path:
                endpoint_type = "habp_consensus"
            else:
                endpoint_type = "api_general"

            # Check rate limit
            result = limiter.check_rate_limit(client_id, endpoint_type)

            if not result.allowed:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": "Too many requests. Please slow down.",
                        "retry_after": result.retry_after,
                    },
                    headers={
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(
                            int(time.time() + (result.retry_after or 0))
                        ),
                        "Retry-After": str(int(result.retry_after or 1)),
                    },
                )
                return response

            # Add rate limit headers to successful responses
            response = await call_next(request)
            remaining, reset_time = limiter.get_remaining(client_id, endpoint_type)
            response.headers["X-RateLimit-Limit"] = str(result.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_time)

            return response

    return RateLimitMiddleware


# ---------------------------------------------------------------------------
# Simple pluggable backends (memory / Redis) — lighter alternative to
# DistributedRateLimiter for use in tests and local-only nodes.
# ---------------------------------------------------------------------------

class MemoryRateLimiter:
    """In-memory sliding-window rate limiter (dev / test / single-node use)."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}

    def is_allowed(self, key: str, max_calls: int, window_seconds: int) -> bool:
        """Return True if the request is permitted; False if rate-limited."""
        import time as _time

        now = _time.time()
        cutoff = now - window_seconds
        bucket = self._windows.setdefault(key, [])
        # Remove timestamps outside the current window
        self._windows[key] = [t for t in bucket if t > cutoff]
        if len(self._windows[key]) >= max_calls:
            return False
        self._windows[key].append(now)
        return True


class _RedisBackedRateLimiter:
    """Redis-backed sliding-window rate limiter using sorted-set commands.

    Uses ZADD / ZREMRANGEBYSCORE / ZCARD / EXPIRE — all supported by
    real Redis and by fakeredis in tests.  The operations are not fully
    atomic (no Lua), but are safe enough for single-process use-cases and
    CI tests.  For production multi-replica deployments consider wrapping
    in a Lua script via DistributedRateLimiter.
    """

    def __init__(self, redis_client: object) -> None:
        self._redis = redis_client

    def is_allowed(self, key: str, max_calls: int, window_seconds: int) -> bool:
        import time as _time
        import hashlib as _hashlib
        import secrets as _secrets

        now = _time.time()
        cutoff = now - window_seconds
        hk = f"tfp:rl:{_hashlib.sha256(key.encode()).hexdigest()[:16]}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(hk, "-inf", cutoff)
        pipe.zcard(hk)
        _, count = pipe.execute()

        if count >= max_calls:
            return False

        member = f"{now}:{_secrets.token_hex(4)}"
        self._redis.zadd(hk, {member: now})
        self._redis.expire(hk, int(window_seconds) + 1)
        return True


def get_rate_limiter(backend: str = "memory", redis_client: object = None):
    """Factory: return a MemoryRateLimiter or Redis-backed limiter.

    Args:
        backend: ``"memory"`` (default) or ``"redis"``.
        redis_client: Required when *backend* is ``"redis"``.
    """
    if backend == "redis":
        if redis_client is None:
            raise ValueError("redis_client required for Redis backend")
        return _RedisBackedRateLimiter(redis_client)
    return MemoryRateLimiter()
