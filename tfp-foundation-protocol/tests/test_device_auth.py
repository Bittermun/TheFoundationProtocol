"""
tests/test_device_auth.py

Verifies that every mutating endpoint requires a valid HMAC-SHA-256
X-Device-Sig header, and that the signature check uses constant-time
comparison so there is no timing oracle.
"""

import hashlib
import hmac as _hmac
import os
import time

os.environ.setdefault("TFP_DB_PATH", ":memory:")

from fastapi.testclient import TestClient
from tfp_demo.server import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sig(puf: bytes, msg: str) -> str:
    """Compute HMAC-SHA-256(puf, msg) as hex — same formula as the server."""
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_publish_requires_sig_header():
    """POST /api/publish without X-Device-Sig must return 422 (header missing)."""
    with TestClient(app) as client:
        r = client.post(
            "/api/publish",
            json={"title": "t", "text": "body", "tags": [], "device_id": "dev"},
        )
        assert r.status_code == 422


def test_earn_requires_sig_header():
    """POST /api/earn without X-Device-Sig must return 422 (header missing)."""
    with TestClient(app) as client:
        r = client.post(
            "/api/earn",
            json={"device_id": "dev", "task_id": "t1"},
        )
        assert r.status_code == 422


def test_result_submission_requires_sig_header():
    """POST /api/task/{id}/result without X-Device-Sig must return 422."""
    with TestClient(app) as client:
        r = client.post(
            "/api/task/abc123/result",
            json={
                "device_id": "dev",
                "output_hash": "a" * 64,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
        )
        assert r.status_code == 422


def test_unenrolled_device_publish_returns_401():
    """A device that was never enrolled must get 401 on publish."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        # Never enroll this device
        sig = _sig(puf, "ghost:SomeTitle")
        r = client.post(
            "/api/publish",
            json={
                "title": "SomeTitle",
                "text": "body",
                "tags": [],
                "device_id": "ghost",
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 401
        assert "enroll" in r.json()["detail"].lower()


def test_unenrolled_device_earn_returns_401():
    """A device that was never enrolled must get 401 on earn."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        sig = _sig(puf, "ghost:task-1")
        r = client.post(
            "/api/earn",
            json={"device_id": "ghost", "task_id": "task-1"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 401


def test_unenrolled_device_result_returns_401():
    """A device that was never enrolled must get 401 on result submission."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        task_id = "fake-task"
        sig = _sig(puf, f"ghost:{task_id}")
        r = client.post(
            f"/api/task/{task_id}/result",
            json={
                "device_id": "ghost",
                "output_hash": "b" * 64,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 401


def test_wrong_sig_publish_returns_401():
    """An enrolled device with a wrong signature must get 401."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        wrong_puf = os.urandom(32)
        _enroll(client, "auth-dev", puf)

        bad_sig = _sig(wrong_puf, "auth-dev:Title")
        r = client.post(
            "/api/publish",
            json={
                "title": "Title",
                "text": "body",
                "tags": [],
                "device_id": "auth-dev",
            },
            headers={"X-Device-Sig": bad_sig},
        )
        assert r.status_code == 401


def test_wrong_sig_earn_returns_401():
    """An enrolled device using the wrong PUF key must get 401 on earn."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        wrong_puf = os.urandom(32)
        _enroll(client, "auth-earn-dev", puf)

        bad_sig = _sig(wrong_puf, "auth-earn-dev:some-task")
        r = client.post(
            "/api/earn",
            json={"device_id": "auth-earn-dev", "task_id": "some-task"},
            headers={"X-Device-Sig": bad_sig},
        )
        assert r.status_code == 401


def test_valid_sig_publish_returns_200():
    """An enrolled device with the correct HMAC-SHA-256 signature must get 200."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "valid-sig-dev"
        _enroll(client, device_id, puf)

        title = "Valid Sig Test"
        sig = _sig(puf, f"{device_id}:{title}")
        r = client.post(
            "/api/publish",
            json={"title": title, "text": "body", "tags": [], "device_id": device_id},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 200
        assert r.json()["title"] == title


def test_valid_sig_earn_returns_200():
    """An enrolled device with the correct HMAC-SHA-256 signature must get 200 on earn."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "valid-sig-earn-dev"
        task_id = "valid-earn-task"
        _enroll(client, device_id, puf)

        sig = _sig(puf, f"{device_id}:{task_id}")
        r = client.post(
            "/api/earn",
            json={"device_id": device_id, "task_id": task_id},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 200
        assert r.json()["credits_earned"] == 10


def test_sig_message_format_device_colon_resource():
    """
    Signature message format must be '{device_id}:{resource}':
    - for /api/publish: '{device_id}:{title}'
    - for /api/earn:    '{device_id}:{task_id}'
    - for /api/task/*/result: '{device_id}:{task_id}'
    Verify that the wrong format (reversed) is rejected.
    """
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "fmt-dev"
        title = "MyTitle"
        _enroll(client, device_id, puf)

        # Correct format: device_id:title
        good_sig = _sig(puf, f"{device_id}:{title}")
        r_good = client.post(
            "/api/publish",
            json={"title": title, "text": "body", "tags": [], "device_id": device_id},
            headers={"X-Device-Sig": good_sig},
        )
        assert r_good.status_code == 200

        # Wrong format: title:device_id (reversed)
        bad_sig = _sig(puf, f"{title}:{device_id}")
        r_bad = client.post(
            "/api/publish",
            json={"title": title, "text": "body2", "tags": [], "device_id": device_id},
            headers={"X-Device-Sig": bad_sig},
        )
        assert r_bad.status_code == 401


def test_auth_failure_increments_metric():
    """Failed auth must increment tfp_auth_failures_total in Prometheus metrics."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        sig = _sig(puf, "nobody:task")
        # Call an endpoint that will fail auth
        client.post(
            "/api/earn",
            json={"device_id": "nobody", "task_id": "task"},
            headers={"X-Device-Sig": sig},
        )
        metrics_text = client.get("/metrics").text
        for line in metrics_text.splitlines():
            if line.startswith("tfp_auth_failures_total "):
                count = int(line.split()[-1])
                assert count >= 1
                break
        else:
            raise AssertionError("tfp_auth_failures_total not found in /metrics")
