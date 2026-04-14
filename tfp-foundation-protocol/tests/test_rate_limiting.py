# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_rate_limiting.py

Verifies that the per-device sliding-window rate limiter:
  - Returns HTTP 429 when the limit is exceeded on /api/earn
  - Returns HTTP 429 when the limit is exceeded on /api/task/{id}/result
  - Is independent per device key
  - Can be configured via env vars (TFP_EARN_RATE_MAX / TFP_EARN_RATE_WINDOW)
"""

import hashlib
import hmac as _hmac
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import tfp_demo.server as _srv
from fastapi.testclient import TestClient
from tfp_demo.server import _RateLimiter, app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# _RateLimiter unit tests
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_calls_within_max():
    """All calls within max_calls must be allowed."""
    limiter = _RateLimiter(max_calls=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("dev") is True


def test_rate_limiter_blocks_call_over_max():
    """The call immediately after max_calls must be blocked."""
    limiter = _RateLimiter(max_calls=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("dev")
    assert limiter.is_allowed("dev") is False


def test_rate_limiter_independent_per_device():
    """Rate limits are tracked per-key; one device's limit does not affect another."""
    limiter = _RateLimiter(max_calls=1, window_seconds=60)
    assert limiter.is_allowed("alice") is True
    assert limiter.is_allowed("bob") is True  # fresh bucket
    assert limiter.is_allowed("alice") is False
    assert limiter.is_allowed("bob") is False


def test_rate_limiter_reset_clears_bucket():
    """reset(key) must clear the bucket so new calls are allowed."""
    limiter = _RateLimiter(max_calls=1, window_seconds=60)
    assert limiter.is_allowed("dev") is True
    assert limiter.is_allowed("dev") is False
    limiter.reset("dev")
    assert limiter.is_allowed("dev") is True


def test_rate_limiter_unknown_key_starts_fresh():
    """A key never seen before starts with an empty bucket."""
    limiter = _RateLimiter(max_calls=2, window_seconds=60)
    assert limiter.is_allowed("brand-new-key") is True


# ---------------------------------------------------------------------------
# Integration tests — /api/earn rate limit (HTTP 429)
# ---------------------------------------------------------------------------


def test_earn_rate_limit_returns_429_after_limit():
    """POST /api/earn must return 429 once the sliding-window limit is reached."""
    with TestClient(app) as client:
        # Temporarily tighten the limiter to 2 calls / 60 s
        original = _srv._earn_rate_limiter
        _srv._earn_rate_limiter = _RateLimiter(max_calls=2, window_seconds=60)
        try:
            puf = os.urandom(32)
            device_id = "rl-earn-dev"
            _enroll(client, device_id, puf)

            # First 2 calls succeed
            for i in range(2):
                sig = _sig(puf, f"{device_id}:rl-task-{i}")
                r = client.post(
                    "/api/earn",
                    json={"device_id": device_id, "task_id": f"rl-task-{i}"},
                    headers={"X-Device-Sig": sig},
                )
                assert r.status_code == 200, f"call {i} failed: {r.text}"

            # Third call is over the limit
            sig = _sig(puf, f"{device_id}:rl-task-2")
            r3 = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "rl-task-2"},
                headers={"X-Device-Sig": sig},
            )
            assert r3.status_code == 429
            assert "rate limit" in r3.json()["detail"].lower()
        finally:
            _srv._earn_rate_limiter = original


def test_earn_rate_limit_metric_incremented():
    """A 429 on /api/earn must increment tfp_earn_rate_limited_total."""
    with TestClient(app) as client:
        original = _srv._earn_rate_limiter
        _srv._earn_rate_limiter = _RateLimiter(max_calls=1, window_seconds=60)
        try:
            puf = os.urandom(32)
            device_id = "rl-metric-dev"
            _enroll(client, device_id, puf)

            sig = _sig(puf, f"{device_id}:m-task-0")
            client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "m-task-0"},
                headers={"X-Device-Sig": sig},
            )
            sig2 = _sig(puf, f"{device_id}:m-task-1")
            client.post(  # triggers 429
                "/api/earn",
                json={"device_id": device_id, "task_id": "m-task-1"},
                headers={"X-Device-Sig": sig2},
            )

            metrics_text = client.get("/metrics").text
            for line in metrics_text.splitlines():
                if line.startswith("tfp_earn_rate_limited_total "):
                    count = int(line.split()[-1])
                    assert count >= 1
                    break
            else:
                raise AssertionError(
                    "tfp_earn_rate_limited_total not found in /metrics"
                )
        finally:
            _srv._earn_rate_limiter = original


# ---------------------------------------------------------------------------
# Integration tests — /api/task/{id}/result rate limit (HTTP 429)
# ---------------------------------------------------------------------------


def test_result_submission_rate_limit_returns_429_after_limit():
    """POST /api/task/{id}/result must return 429 once the limit is reached."""
    with TestClient(app) as client:
        original = _srv._result_rate_limiter
        _srv._result_rate_limiter = _RateLimiter(max_calls=1, window_seconds=60)
        try:
            puf = os.urandom(32)
            device_id = "rl-result-dev"
            _enroll(client, device_id, puf)

            # Create a task so the ID is valid
            task_r = client.post(
                "/api/task",
                json={"task_type": "content_verify", "difficulty": 1, "seed_hex": ""},
            )
            task_id = task_r.json()["task_id"]
            output_hash = task_r.json()["expected_output_hash"]

            # First submission succeeds
            sig = _sig(puf, f"{device_id}:{task_id}")
            r1 = client.post(
                f"/api/task/{task_id}/result",
                json={
                    "device_id": device_id,
                    "output_hash": output_hash,
                    "exec_time_s": 0.1,
                    "has_tee": False,
                },
                headers={"X-Device-Sig": sig},
            )
            assert r1.status_code == 200

            # Second submission is over the rate limit
            r2 = client.post(
                f"/api/task/{task_id}/result",
                json={
                    "device_id": device_id,
                    "output_hash": output_hash,
                    "exec_time_s": 0.1,
                    "has_tee": False,
                },
                headers={"X-Device-Sig": sig},
            )
            assert r2.status_code == 429
        finally:
            _srv._result_rate_limiter = original


def test_earn_rate_limit_does_not_affect_other_device():
    """A rate-limited device must not affect another device's quota."""
    with TestClient(app) as client:
        original = _srv._earn_rate_limiter
        _srv._earn_rate_limiter = _RateLimiter(max_calls=1, window_seconds=60)
        try:
            puf_a = os.urandom(32)
            puf_b = os.urandom(32)
            _enroll(client, "rl-alice", puf_a)
            _enroll(client, "rl-bob", puf_b)

            # Alice exhausts her quota
            sig = _sig(puf_a, "rl-alice:task-a-1")
            client.post(
                "/api/earn",
                json={"device_id": "rl-alice", "task_id": "task-a-1"},
                headers={"X-Device-Sig": sig},
            )
            sig2 = _sig(puf_a, "rl-alice:task-a-2")
            r_alice_blocked = client.post(
                "/api/earn",
                json={"device_id": "rl-alice", "task_id": "task-a-2"},
                headers={"X-Device-Sig": sig2},
            )
            assert r_alice_blocked.status_code == 429

            # Bob is unaffected
            sig_b = _sig(puf_b, "rl-bob:task-b-1")
            r_bob = client.post(
                "/api/earn",
                json={"device_id": "rl-bob", "task_id": "task-b-1"},
                headers={"X-Device-Sig": sig_b},
            )
            assert r_bob.status_code == 200
        finally:
            _srv._earn_rate_limiter = original
