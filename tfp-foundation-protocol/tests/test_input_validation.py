# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_input_validation.py

Verifies that Pydantic model bounds on every POST body are enforced:
  - puf_entropy_hex must be exactly 64 hex characters
  - title must be 1–120 characters
  - text must be 1–20 000 characters
  - task difficulty must be 1–10
  - output_hash must be exactly 64 hex characters
  - exec_time_s must be >= 0
"""

import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

from fastapi.testclient import TestClient
from tfp_demo.server import app


# ---------------------------------------------------------------------------
# /api/enroll validation
# ---------------------------------------------------------------------------


def test_enroll_puf_entropy_too_short_returns_422():
    """puf_entropy_hex shorter than 64 chars must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/enroll",
            json={"device_id": "dev", "puf_entropy_hex": "ab" * 31},  # 62 chars
        )
        assert r.status_code == 422


def test_enroll_puf_entropy_too_long_returns_422():
    """puf_entropy_hex longer than 64 chars must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/enroll",
            json={"device_id": "dev", "puf_entropy_hex": "ab" * 33},  # 66 chars
        )
        assert r.status_code == 422


def test_enroll_puf_entropy_exact_64_chars_succeeds():
    """Exactly 64 hex chars must be accepted."""
    with TestClient(app) as client:
        r = client.post(
            "/api/enroll",
            json={"device_id": "valid-dev", "puf_entropy_hex": "0a" * 32},
        )
        assert r.status_code == 200


def test_enroll_invalid_hex_returns_422():
    """Non-hex characters in puf_entropy_hex must result in a 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/enroll",
            # 62 chars of valid hex + 2 non-hex chars = 64 chars, invalid
            json={"device_id": "dev", "puf_entropy_hex": "zz" + "00" * 31},
        )
        assert r.status_code == 422


def test_enroll_device_id_empty_returns_422():
    """An empty device_id must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/enroll",
            json={"device_id": "", "puf_entropy_hex": "00" * 32},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# /api/publish validation
# ---------------------------------------------------------------------------


def test_publish_title_empty_returns_422():
    """Empty title must return 422 (min_length=1)."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b":ignored", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/publish",
            json={"title": "", "text": "body", "tags": [], "device_id": "dev"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_publish_title_too_long_returns_422():
    """Title longer than 120 characters must return 422."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:x", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/publish",
            json={"title": "x" * 121, "text": "body", "tags": [], "device_id": "dev"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_publish_text_empty_returns_422():
    """Empty text body must return 422 (min_length=1)."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:title", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/publish",
            json={"title": "title", "text": "", "tags": [], "device_id": "dev"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_publish_text_too_long_returns_422():
    """text longer than 10MB must return 422."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:t", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/publish",
            json={
                "title": "t",
                "text": "x" * 10_485_761,  # Exceeds 10MB max_length
                "tags": [],
                "device_id": "dev",
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# /api/task validation
# ---------------------------------------------------------------------------


def test_create_task_difficulty_zero_returns_422():
    """difficulty=0 is below the minimum of 1 and must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/task",
            json={"task_type": "hash_preimage", "difficulty": 0, "seed_hex": ""},
        )
        assert r.status_code == 422


def test_create_task_difficulty_eleven_returns_422():
    """difficulty=11 exceeds the maximum of 10 and must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/task",
            json={"task_type": "hash_preimage", "difficulty": 11, "seed_hex": ""},
        )
        assert r.status_code == 422


def test_create_task_difficulty_boundary_1_succeeds():
    """difficulty=1 (minimum boundary) must succeed."""
    with TestClient(app) as client:
        r = client.post(
            "/api/task",
            json={"task_type": "content_verify", "difficulty": 1, "seed_hex": ""},
        )
        assert r.status_code == 200


def test_create_task_difficulty_boundary_10_succeeds():
    """difficulty=10 (maximum boundary) must succeed."""
    with TestClient(app) as client:
        r = client.post(
            "/api/task",
            json={"task_type": "content_verify", "difficulty": 10, "seed_hex": ""},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# /api/task/{id}/result validation
# ---------------------------------------------------------------------------


def test_result_output_hash_too_short_returns_422():
    """output_hash shorter than 64 chars must return 422."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:task", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/task/some-task/result",
            json={
                "device_id": "dev",
                "output_hash": "a" * 63,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_result_output_hash_too_long_returns_422():
    """output_hash longer than 64 chars must return 422."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:task", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/task/some-task/result",
            json={
                "device_id": "dev",
                "output_hash": "a" * 65,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_result_exec_time_negative_returns_422():
    """exec_time_s < 0 must return 422."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:task", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/task/some-task/result",
            json={
                "device_id": "dev",
                "output_hash": "a" * 64,
                "exec_time_s": -0.001,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 422


def test_result_valid_boundary_values_pass_validation():
    """exec_time_s=0.0 and output_hash=64 chars must pass Pydantic validation
    (downstream auth/task-lookup will still return 401/404)."""
    import hashlib
    import hmac as _hmac

    puf = bytes(range(32))
    sig = _hmac.new(puf, b"dev:no-task", hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        r = client.post(
            "/api/task/no-task/result",
            json={
                "device_id": "dev",
                "output_hash": "a" * 64,
                "exec_time_s": 0.0,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        # Not 422 — must be 401 (auth) or 404 (no task)
        assert r.status_code in (200, 401, 404, 409, 410)
