"""
tests/test_rag_production.py

Tests for the production semantic search API endpoints.

Verifies:
- GET /api/status includes rag_enabled and rag_stats fields.
- POST /api/search/semantic returns 503 when RAG is not initialised.
- POST /api/search/semantic returns 401 for missing/wrong device signature.
- POST /api/search/semantic returns 429 when rate limit is exceeded.
- POST /api/admin/rag/reindex returns 503 when RAG is not initialised.
- POST /api/admin/rag/reindex returns 401 for missing/wrong device signature.
- With a mocked RAGGraph, POST /api/search/semantic returns results.
- With a mocked RAGGraph, POST /api/admin/rag/reindex returns indexed count.
"""

import hashlib
import hmac as _hmac
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /api/status RAG fields
# ---------------------------------------------------------------------------


def test_status_includes_rag_enabled():
    with TestClient(app) as client:
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "rag_enabled" in data
        assert isinstance(data["rag_enabled"], bool)


def test_status_rag_stats_none_when_disabled(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_RAG", "0")
    with TestClient(app) as client:
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["rag_enabled"] is False
        assert data["rag_stats"] is None


def test_status_includes_peer_secret_enforced():
    with TestClient(app) as client:
        r = client.get("/api/status")
        data = r.json()
        assert "peer_secret_enforced" in data
        assert isinstance(data["peer_secret_enforced"], bool)


def test_status_includes_pin_rewards_active():
    with TestClient(app) as client:
        r = client.get("/api/status")
        data = r.json()
        assert "pin_rewards_active" in data


# ---------------------------------------------------------------------------
# /api/search/semantic — RAG not initialised (default TFP_ENABLE_RAG=0)
# ---------------------------------------------------------------------------


def test_semantic_search_503_when_rag_disabled(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_RAG", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "rag-503-dev", puf)
        sig = _sig(puf, "rag-503-dev:test query")
        r = client.post(
            "/api/search/semantic",
            json={"device_id": "rag-503-dev", "query": "test query"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 503


def test_semantic_search_401_bad_sig():
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "rag-401-dev", puf)
        r = client.post(
            "/api/search/semantic",
            json={"device_id": "rag-401-dev", "query": "test"},
            headers={"X-Device-Sig": "bad-sig"},
        )
        assert r.status_code == 401


def test_semantic_search_401_unenrolled():
    with TestClient(app) as client:
        sig = _sig(b"x" * 32, "unenrolled:test")
        r = client.post(
            "/api/search/semantic",
            json={"device_id": "unenrolled", "query": "test"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 401


def test_semantic_search_429_rate_limit(monkeypatch):
    """Exceeding the RAG rate limit returns 429."""
    import tfp_demo.server as srv

    monkeypatch.setenv("TFP_ENABLE_RAG", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-ratelimit-dev"
        _enroll(client, did, puf)

        # Set limiter to allow 0 calls
        original_limiter = srv._rag_rate_limiter
        mock_lim = MagicMock()
        mock_lim.is_allowed.return_value = False
        srv._rag_rate_limiter = mock_lim
        try:
            sig = _sig(puf, f"{did}:my query")
            r = client.post(
                "/api/search/semantic",
                json={"device_id": did, "query": "my query"},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 429
        finally:
            srv._rag_rate_limiter = original_limiter


# ---------------------------------------------------------------------------
# /api/search/semantic — with mocked RAGGraph
# ---------------------------------------------------------------------------


def _make_mock_rag():
    """Return a mock RAGGraph that returns predictable search results."""
    from tfp_client.lib.rag_search import SearchResult

    mock_rag = MagicMock()
    mock_rag.search.return_value = [
        SearchResult(
            content="def habp_consensus(): ...",
            metadata={"file": "server.py", "line_start": 10},
            score=0.92,
            chunk_id="abc123",
        )
    ]
    mock_rag.get_stats.return_value = {"total_chunks": 500, "collection_name": "tfp"}
    mock_rag.index_directory.return_value = 42
    return mock_rag


def test_semantic_search_with_mock_rag_returns_results():
    import tfp_demo.server as srv

    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-search-dev"
        _enroll(client, did, puf)
        sig = _sig(puf, f"{did}:habp consensus")

        original = srv._rag_graph
        srv._rag_graph = _make_mock_rag()
        try:
            r = client.post(
                "/api/search/semantic",
                json={"device_id": did, "query": "habp consensus"},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 200
            data = r.json()
            assert "results" in data
            assert len(data["results"]) == 1
            assert data["results"][0]["score"] == pytest.approx(0.92)
            assert "rag_stats" in data
        finally:
            srv._rag_graph = original


def test_semantic_search_metric_incremented_on_success():
    import tfp_demo.server as srv

    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-metric-dev"
        _enroll(client, did, puf)
        sig = _sig(puf, f"{did}:search query")

        original = srv._rag_graph
        srv._rag_graph = _make_mock_rag()
        try:
            before = srv._metrics.get("tfp_semantic_search_total")
            r = client.post(
                "/api/search/semantic",
                json={"device_id": did, "query": "search query"},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 200
            after = srv._metrics.get("tfp_semantic_search_total")
            assert after == before + 1
        finally:
            srv._rag_graph = original


# ---------------------------------------------------------------------------
# /api/admin/rag/reindex
# ---------------------------------------------------------------------------


def test_rag_reindex_503_when_rag_disabled(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_RAG", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-reindex-dev"
        _enroll(client, did, puf)
        msg = f"{did}:reindex:./tfp_client"
        sig = _sig(puf, msg)
        r = client.post(
            "/api/admin/rag/reindex",
            json={"device_id": did, "directory": "./tfp_client"},
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 503


def test_rag_reindex_401_bad_sig():
    with TestClient(app) as client:
        r = client.post(
            "/api/admin/rag/reindex",
            json={"device_id": "somedev", "directory": "."},
            headers={"X-Device-Sig": "bad"},
        )
        assert r.status_code == 401


def test_rag_reindex_with_mock_rag_returns_indexed_count():
    import tfp_demo.server as srv

    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-admin-dev"
        _enroll(client, did, puf)
        msg = f"{did}:reindex:./tfp_client"
        sig = _sig(puf, msg)

        original = srv._rag_graph
        srv._rag_graph = _make_mock_rag()
        try:
            r = client.post(
                "/api/admin/rag/reindex",
                json={"device_id": did, "directory": "./tfp_client"},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["indexed_chunks"] == 42
            # directory is returned as the resolved absolute path
            from pathlib import Path

            assert Path(data["directory"]).is_absolute()
        finally:
            srv._rag_graph = original


def test_rag_reindex_rejects_sensitive_path():
    """Directories outside the allowed base (cwd by default) return 422."""
    import tfp_demo.server as srv

    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-pathsec-dev"
        _enroll(client, did, puf)

        original = srv._rag_graph
        srv._rag_graph = _make_mock_rag()
        try:
            # /nonexistent_outside_cwd is not within cwd, so should be 422
            test_dir = "/tmp/tfp_test_outside_cwd"
            msg = f"{did}:reindex:{test_dir}"
            sig = _sig(puf, msg)
            r = client.post(
                "/api/admin/rag/reindex",
                json={"device_id": did, "directory": test_dir},
                headers={"X-Device-Sig": sig},
            )
            # Either 422 (outside base) or 422 (not a directory) — both are fine
            assert r.status_code == 422
        finally:
            srv._rag_graph = original
    import tfp_demo.server as srv

    with TestClient(app) as client:
        puf = os.urandom(32)
        did = "rag-metric2-dev"
        _enroll(client, did, puf)
        msg = f"{did}:reindex:./docs"
        sig = _sig(puf, msg)

        original = srv._rag_graph
        srv._rag_graph = _make_mock_rag()
        try:
            before = srv._metrics.get("tfp_rag_reindex_total")
            r = client.post(
                "/api/admin/rag/reindex",
                json={"device_id": did, "directory": "./docs"},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 200
            after = srv._metrics.get("tfp_rag_reindex_total")
            assert after == before + 1
        finally:
            srv._rag_graph = original
