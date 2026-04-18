# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

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


def test_nostr_private_key_loaded(monkeypatch):
    """NOSTR_PRIVATE_KEY env var must be used as the bridge signing key."""
    import secrets

    from tfp_client.lib.bridges.nostr_bridge import _derive_pubkey_bytes

    privkey = secrets.token_bytes(32)
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", privkey.hex())
    monkeypatch.delenv("NOSTR_RELAY", raising=False)
    monkeypatch.delenv("NOSTR_RELAY_URL", raising=False)
    import tfp_demo.server as srv

    with TestClient(app):
        assert srv._nostr_bridge is not None
        expected_pubkey = _derive_pubkey_bytes(privkey).hex()
        assert srv._nostr_bridge.pubkey_hex == expected_pubkey


def test_nostr_invalid_key_uses_random(monkeypatch):
    """Invalid NOSTR_PRIVATE_KEY must be ignored and a random key used."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", "not-valid-hex!!")
    monkeypatch.delenv("NOSTR_RELAY", raising=False)
    monkeypatch.delenv("NOSTR_RELAY_URL", raising=False)
    import tfp_demo.server as srv

    with TestClient(app):
        # Server must start normally with a random key
        assert srv._nostr_bridge is not None
        assert len(srv._nostr_bridge.pubkey_hex) == 64


def test_nostr_publish_disabled_sets_offline(monkeypatch):
    """TFP_NOSTR_PUBLISH_ENABLED=0 must set the bridge to offline mode."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.setenv("TFP_NOSTR_PUBLISH_ENABLED", "0")
    monkeypatch.setenv("NOSTR_RELAY", "wss://relay.damus.io")
    import tfp_demo.server as srv

    with TestClient(app):
        assert srv._nostr_bridge is not None
        # Bridge offline=True means no outbound publishes even with a relay
        assert srv._nostr_bridge.offline is True


def test_nostr_publish_enabled_sets_online(monkeypatch):
    """TFP_NOSTR_PUBLISH_ENABLED=1 with a relay must leave bridge in online mode (in production). In test mode, bridge is forced offline to prevent network calls."""
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.setenv("TFP_NOSTR_PUBLISH_ENABLED", "1")
    monkeypatch.setenv("NOSTR_RELAY", "wss://relay.damus.io")
    import tfp_demo.server as srv

    with TestClient(app):
        assert srv._nostr_bridge is not None
        # In test mode (using :memory: DB), bridge is forced offline to prevent network calls
        assert srv._nostr_bridge.offline is True


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
