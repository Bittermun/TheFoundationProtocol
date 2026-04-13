import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import TFP_CONTENT_ANNOUNCE_KIND, app


def test_production_requires_peer_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_MODE", "production")
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "tfp.db"))
    monkeypatch.delenv("TFP_PEER_SECRET", raising=False)
    monkeypatch.setenv("TFP_ADMIN_DEVICE_IDS", "admin-1")
    with pytest.raises(ValueError, match="TFP_PEER_SECRET"):
        with TestClient(app):
            pass


def test_production_defaults_nostr_publish_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_MODE", "production")
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "tfp.db"))
    monkeypatch.setenv("TFP_PEER_SECRET", "peer-secret")
    monkeypatch.setenv("TFP_ADMIN_DEVICE_IDS", "admin-1")
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.setenv("NOSTR_RELAY", "wss://relay.damus.io")
    monkeypatch.delenv("TFP_NOSTR_PUBLISH_ENABLED", raising=False)

    import tfp_demo.server as srv

    with TestClient(app):
        assert srv._nostr_bridge is not None
        assert srv._nostr_bridge.offline is True


def test_production_drops_nostr_events_without_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_MODE", "production")
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "tfp.db"))
    monkeypatch.setenv("TFP_PEER_SECRET", "peer-secret")
    monkeypatch.setenv("TFP_ADMIN_DEVICE_IDS", "admin-1")
    monkeypatch.setenv("TFP_ENABLE_NOSTR", "1")
    monkeypatch.delenv("TFP_NOSTR_TRUSTED_PUBKEYS", raising=False)

    import tfp_demo.server as srv

    event = {
        "id": f"{int(time.time() * 1_000_000):064x}"[-64:],
        "kind": TFP_CONTENT_ANNOUNCE_KIND,
        "pubkey": "a" * 64,
        "created_at": int(time.time()),
        "tags": [],
        "content": "{}",
        "sig": "b" * 128,
    }

    with TestClient(app):
        with (
            patch.object(srv, "_verify_nostr_event", return_value=True),
            patch.object(srv, "_check_replay_window", return_value=True),
            patch.object(srv._tag_overlay, "add_entry") as add_entry,
        ):
            srv._on_nostr_event(event)
            add_entry.assert_not_called()


def test_admin_dashboard_requires_peer_secret_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_MODE", "production")
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "tfp.db"))
    monkeypatch.setenv("TFP_PEER_SECRET", "peer-secret")
    monkeypatch.setenv("TFP_ADMIN_DEVICE_IDS", "admin-1")

    with TestClient(app) as client:
        no_header = client.get("/admin")
        assert no_header.status_code == 401
        ok = client.get("/admin", headers={"X-TFP-Peer-Secret": "peer-secret"})
        assert ok.status_code == 200
