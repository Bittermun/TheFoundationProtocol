"""
tests/test_peer_auth.py

Tests for the /api/peer/{hash} peer-mesh endpoint authentication gate.

Verifies:
- Without TFP_PEER_SECRET set: /api/peer returns content with no auth required.
- With TFP_PEER_SECRET set: /api/peer returns 401 for missing/wrong secret.
- With TFP_PEER_SECRET set: /api/peer returns 200 for correct secret.
- _PeerFallback.get() automatically sends X-TFP-Peer-Secret when configured.
- _PeerFallback without secret does not send the header.
"""

import hashlib
import hmac as _hmac
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
# Without peer secret
# ---------------------------------------------------------------------------


def test_peer_endpoint_no_secret_no_auth_required():
    """Without TFP_PEER_SECRET, /api/peer is unauthenticated (backward compat)."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-noauth", puf)
        root_hash = _publish(client, "peer-noauth", puf, "NoAuthTitle", "hello")
        r = client.get(f"/api/peer/{root_hash}")
        assert r.status_code == 200
        assert r.content == b"hello"


def test_peer_endpoint_no_secret_with_wrong_header_still_ok(monkeypatch):
    """If TFP_PEER_SECRET is not set, any (or no) header value is accepted."""
    monkeypatch.delenv("TFP_PEER_SECRET", raising=False)
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-noauth2", puf)
        root_hash = _publish(client, "peer-noauth2", puf, "NoAuth2", "world")
        r = client.get(
            f"/api/peer/{root_hash}",
            headers={"X-TFP-Peer-Secret": "wrong-value"},
        )
        # Without server secret configured, any header is accepted
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# With peer secret
# ---------------------------------------------------------------------------


def test_peer_endpoint_with_secret_missing_header_returns_401(monkeypatch):
    """With TFP_PEER_SECRET set, missing header → 401."""
    monkeypatch.setenv("TFP_PEER_SECRET", "test-shared-secret")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-auth1", puf)
        root_hash = _publish(client, "peer-auth1", puf, "AuthTitle1", "secret content")
        # No header
        r = client.get(f"/api/peer/{root_hash}")
        assert r.status_code == 401


def test_peer_endpoint_with_secret_wrong_header_returns_401(monkeypatch):
    """With TFP_PEER_SECRET set, wrong header value → 401."""
    monkeypatch.setenv("TFP_PEER_SECRET", "test-shared-secret")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-auth2", puf)
        root_hash = _publish(client, "peer-auth2", puf, "AuthTitle2", "secret2")
        r = client.get(
            f"/api/peer/{root_hash}",
            headers={"X-TFP-Peer-Secret": "wrong-secret"},
        )
        assert r.status_code == 401


def test_peer_endpoint_with_secret_correct_header_returns_200(monkeypatch):
    """With TFP_PEER_SECRET set, correct header → 200 with content."""
    monkeypatch.setenv("TFP_PEER_SECRET", "test-shared-secret")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "peer-auth3", puf)
        root_hash = _publish(client, "peer-auth3", puf, "AuthTitle3", "secure content")
        r = client.get(
            f"/api/peer/{root_hash}",
            headers={"X-TFP-Peer-Secret": "test-shared-secret"},
        )
        assert r.status_code == 200
        assert r.content == b"secure content"


def test_peer_endpoint_with_secret_returns_404_correct_secret(monkeypatch):
    """Correct secret but unknown hash → 404 (not 401)."""
    monkeypatch.setenv("TFP_PEER_SECRET", "test-shared-secret")
    with TestClient(app) as client:
        r = client.get(
            f"/api/peer/{'0' * 64}",
            headers={"X-TFP-Peer-Secret": "test-shared-secret"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# _PeerFallback secret propagation
# ---------------------------------------------------------------------------


def test_peer_fallback_sends_secret_header():
    """_PeerFallback with peer_secret sends the X-TFP-Peer-Secret header."""
    captured_headers = []

    def fake_urlopen(req, timeout):
        captured_headers.append(dict(req.headers))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"data"
        return mock_resp

    pf = _PeerFallback(["http://peer1:8000"], peer_secret="my-secret")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = pf.get("a" * 64)

    assert result == b"data"
    assert len(captured_headers) == 1
    # Headers are stored with title-case by urllib
    header_values = {k.lower(): v for k, v in captured_headers[0].items()}
    assert header_values.get("x-tfp-peer-secret") == "my-secret"


def test_peer_fallback_no_secret_no_header_sent():
    """_PeerFallback without peer_secret does not send X-TFP-Peer-Secret."""
    captured_headers = []

    def fake_urlopen(req, timeout):
        captured_headers.append(dict(req.headers))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"data"
        return mock_resp

    pf = _PeerFallback(["http://peer1:8000"])
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = pf.get("a" * 64)

    assert result == b"data"
    for headers in captured_headers:
        assert "x-tfp-peer-secret" not in {k.lower() for k in headers}


def test_peer_fallback_empty_secret_no_header_sent():
    """_PeerFallback with empty string peer_secret does not send the header."""
    captured_headers = []

    def fake_urlopen(req, timeout):
        captured_headers.append(dict(req.headers))
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"no-header"
        return mock_resp

    pf = _PeerFallback(["http://peer1:8000"], peer_secret="")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        pf.get("b" * 64)

    for headers in captured_headers:
        assert "x-tfp-peer-secret" not in {k.lower() for k in headers}
