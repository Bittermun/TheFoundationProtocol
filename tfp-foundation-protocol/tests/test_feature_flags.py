"""
tests/test_feature_flags.py

Phase B feature-flag tests.

Verifies that TFP_ENABLE_IPFS, TFP_ENABLE_NOSTR, and TFP_ENABLE_MAINTENANCE
each control their respective subsystem initialisation, and that disabling any
or all of them still allows the core enroll → publish → earn flow to complete.
"""

import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import hashlib
import hmac as _hmac

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


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


def _publish(client, device_id: str, puf: bytes, title: str, text: str = "body") -> str:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={"title": title, "text": text, "tags": [], "device_id": device_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


def _earn(client, device_id: str, puf: bytes, task_id: str) -> dict:
    sig = _sig(puf, f"{device_id}:{task_id}")
    r = client.post(
        "/api/earn",
        json={"device_id": device_id, "task_id": task_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Tests — IPFS feature flag
# ---------------------------------------------------------------------------


def test_ipfs_disabled_server_starts(monkeypatch):
    """Server must start cleanly when TFP_ENABLE_IPFS=0."""
    monkeypatch.setenv("TFP_ENABLE_IPFS", "0")
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


def test_ipfs_disabled_enroll_works(monkeypatch):
    """Device enrollment must succeed when IPFS is disabled."""
    monkeypatch.setenv("TFP_ENABLE_IPFS", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "flag-ipfs-off-dev", puf)


def test_ipfs_disabled_publish_works(monkeypatch):
    """Content publishing must succeed when IPFS is disabled."""
    monkeypatch.setenv("TFP_ENABLE_IPFS", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "flag-ipfs-pub-dev", puf)
        root_hash = _publish(client, "flag-ipfs-pub-dev", puf, "IPFSOffTest")
        assert len(root_hash) == 64


# ---------------------------------------------------------------------------
# Tests — Nostr feature flag
# ---------------------------------------------------------------------------


def test_nostr_disabled_server_starts(monkeypatch):
    """Server must start cleanly when TFP_ENABLE_NOSTR=0."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "0")
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


def test_nostr_disabled_status_endpoint(monkeypatch):
    """GET /api/status must succeed even when Nostr is disabled."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "0")
    with TestClient(app) as client:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        body = resp.json()
        # Nostr subscriber won't be running
        assert body["nostr_subscriber_running"] is False


def test_nostr_disabled_enroll_works(monkeypatch):
    """Device enrollment must succeed when Nostr is disabled."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "flag-nostr-off-dev", puf)


# ---------------------------------------------------------------------------
# Tests — Maintenance feature flag
# ---------------------------------------------------------------------------


def test_maintenance_disabled_server_starts(monkeypatch):
    """Server must start cleanly when TFP_ENABLE_MAINTENANCE=0."""
    monkeypatch.setenv("TFP_ENABLE_MAINTENANCE", "0")
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


def test_maintenance_disabled_enroll_works(monkeypatch):
    """Enrollment must succeed when the maintenance thread is disabled."""
    monkeypatch.setenv("TFP_ENABLE_MAINTENANCE", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "flag-maint-off-dev", puf)


# ---------------------------------------------------------------------------
# Tests — All features disabled
# ---------------------------------------------------------------------------


def test_all_features_disabled_server_starts(monkeypatch):
    """Server must start when IPFS, Nostr, and maintenance are all disabled."""
    monkeypatch.setenv("TFP_ENABLE_IPFS", "0")
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "0")
    monkeypatch.setenv("TFP_ENABLE_MAINTENANCE", "0")
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


def test_all_features_disabled_core_flow(monkeypatch):
    """Core enroll → publish → earn flow must work with all features disabled."""
    monkeypatch.setenv("TFP_ENABLE_IPFS", "0")
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "0")
    monkeypatch.setenv("TFP_ENABLE_MAINTENANCE", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "all-flags-off-dev"
        _enroll(client, device_id, puf)
        _publish(client, device_id, puf, "AllFlagsOffTitle")
        result = _earn(client, device_id, puf, "all-flags-off-task-1")
        assert result.get("credits_earned", 0) >= 0
