import hashlib
import hmac as _hmac
import os

os.environ["TFP_DB_PATH"] = ":memory:"

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sig(puf_entropy: bytes, message: str) -> str:
    """Compute HMAC-SHA-256(puf_entropy, message) as hex."""
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf_entropy: bytes) -> None:
    resp = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["content_items"] >= 1


def test_enroll_device():
    with TestClient(app) as client:
        puf_entropy = bytes(range(32))
        response = client.post(
            "/api/enroll",
            json={"device_id": "test-device", "puf_entropy_hex": puf_entropy.hex()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enrolled"] is True
        assert body["device_id"] == "test-device"


def test_enroll_invalid_hex():
    with TestClient(app) as client:
        response = client.post(
            "/api/enroll",
            json={"device_id": "dev", "puf_entropy_hex": "not-valid-hex" + "0" * 51},
        )
        assert response.status_code == 422


def test_publish_missing_sig_header_returns_422():
    with TestClient(app) as client:
        response = client.post(
            "/api/publish",
            json={"title": "Demo", "text": "Hello", "tags": [], "device_id": "anon"},
        )
        assert response.status_code == 422


def test_publish_unknown_device_returns_401():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        sig = _make_sig(puf_entropy, "ghost:Demo")
        response = client.post(
            "/api/publish",
            json={"title": "Demo", "text": "Hello", "tags": [], "device_id": "ghost"},
            headers={"X-Device-Sig": sig},
        )
        assert response.status_code == 401


def test_earn_missing_sig_header_returns_422():
    with TestClient(app) as client:
        response = client.post(
            "/api/earn",
            json={"device_id": "anon", "task_id": "t1"},
        )
        assert response.status_code == 422


def test_publish_and_get_requires_credits():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "tester"
        _enroll(client, device_id, puf_entropy)

        # Publish with valid signature
        title = "Demo"
        publish_sig = _make_sig(puf_entropy, f"{device_id}:{title}")
        publish = client.post(
            "/api/publish",
            json={
                "title": title,
                "text": "Hello network",
                "tags": ["demo"],
                "device_id": device_id,
            },
            headers={"X-Device-Sig": publish_sig},
        )
        assert publish.status_code == 200
        root_hash = publish.json()["root_hash"]

        # Get without credits → 402
        denied = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert denied.status_code == 402

        # Earn credits
        task_id = "task-1"
        earn_sig = _make_sig(puf_entropy, f"{device_id}:{task_id}")
        earn = client.post(
            "/api/earn",
            json={"device_id": device_id, "task_id": task_id},
            headers={"X-Device-Sig": earn_sig},
        )
        assert earn.status_code == 200
        assert earn.json()["credits_earned"] == 10

        # Get with credits → 200
        ok = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert ok.status_code == 200
        body = ok.json()
        assert body["text"] == "Hello network"
        assert body["root_hash"] == root_hash


def test_search_by_tag():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "tag-tester"
        _enroll(client, device_id, puf_entropy)

        title = "Tagged Content"
        sig = _make_sig(puf_entropy, f"{device_id}:{title}")
        pub = client.post(
            "/api/publish",
            json={
                "title": title,
                "text": "tag filtering test",
                "tags": ["unique-tag-xyz"],
                "device_id": device_id,
            },
            headers={"X-Device-Sig": sig},
        )
        assert pub.status_code == 200
        root_hash = pub.json()["root_hash"]

        results = client.get("/api/content", params={"tag": "unique-tag-xyz"}).json()
        hashes = [item["root_hash"] for item in results["items"]]
        assert root_hash in hashes

        no_results = client.get("/api/content", params={"tag": "nonexistent-tag"}).json()
        assert no_results["items"] == []


def test_get_missing_content_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/get/deadbeef" + "0" * 56)
        assert response.status_code == 404
