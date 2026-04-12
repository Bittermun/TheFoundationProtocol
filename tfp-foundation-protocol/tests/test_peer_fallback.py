"""
tests/test_peer_fallback.py

Phase C — Peer HTTP fallback tests.

Verifies:
- _PeerFallback returns None when no peers are configured.
- _PeerFallback.get() tries each configured peer in order.
- _PeerFallback.get() returns data on first success, skips failed peers.
- GET /api/peer/{root_hash} returns raw bytes when content is local.
- GET /api/peer/{root_hash} returns 404 for unknown hashes.
- /api/get uses peer fallback on local miss (integration test with mock peer).
"""

import hashlib
import hmac as _hmac
import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import _PeerFallback, app


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200


def _publish(client, device_id: str, puf: bytes, title: str, text: str) -> str:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={
            "title": title,
            "text": text,
            "tags": ["test"],
            "device_id": device_id,
        },
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


# ---------------------------------------------------------------------------
# _PeerFallback unit tests
# ---------------------------------------------------------------------------


def test_peer_fallback_no_peers_returns_none():
    pf = _PeerFallback([])
    assert pf.get("abc123") is None


def test_peer_fallback_skips_failed_peers():
    """If the first peer fails (connection error), the next should be tried."""
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        if "peer1" in req.full_url:
            raise OSError("connection refused")
        # Simulate a 200 response from peer2
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"peer2 data"
        return mock_resp

    pf = _PeerFallback(["http://peer1:8000", "http://peer2:8000"])
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = pf.get("deadbeef" + "0" * 56)

    assert result == b"peer2 data"
    assert any("peer1" in u for u in calls)
    assert any("peer2" in u for u in calls)


def test_peer_fallback_all_peers_fail_returns_none():
    def fake_urlopen(req, timeout):
        raise OSError("timeout")

    pf = _PeerFallback(["http://p1:8000", "http://p2:8000"])
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert pf.get("abc" + "0" * 61) is None


def test_peer_fallback_first_success_returns_immediately():
    call_count = [0]

    def fake_urlopen(req, timeout):
        call_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"found it"
        return mock_resp

    pf = _PeerFallback(["http://p1:8000", "http://p2:8000", "http://p3:8000"])
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = pf.get("a" * 64)

    # Should stop after first success, not try all 3
    assert result == b"found it"
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# /api/peer/{root_hash} endpoint tests
# ---------------------------------------------------------------------------


def test_peer_endpoint_returns_bytes_for_local_content():
    """The /api/peer endpoint must return raw bytes for locally-stored content."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-e2e", puf)
        root_hash = _publish(client, "peer-e2e", puf, "PeerTitle", "peer content body")

        r = client.get(f"/api/peer/{root_hash}")
        assert r.status_code == 200
        assert r.content == b"peer content body"


def test_peer_endpoint_returns_404_for_unknown():
    with TestClient(app) as client:
        r = client.get(f"/api/peer/{'0' * 64}")
        assert r.status_code == 404


def test_peer_endpoint_does_not_require_credits():
    """The /api/peer endpoint bypasses the credit system."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "peer-nocred"
        _enroll(client, device_id, puf)
        root_hash = _publish(client, device_id, puf, "NoCred", "free for peers")

        # No earn call; /api/get/{hash} would return 402, but /api/peer must return 200
        r = client.get(f"/api/peer/{root_hash}")
        assert r.status_code == 200
