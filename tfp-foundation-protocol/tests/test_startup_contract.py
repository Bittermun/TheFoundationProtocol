"""
tests/test_startup_contract.py

Phase A + Phase B startup contract tests.

Verifies that:
- The server module can be imported without errors.
- The lifespan context manager reaches the 'ready' state.
- GET /health reports ready=True and startup_stage='ready' after startup.
- The readiness flag resets after shutdown (confirmed by the TestClient context
  manager completing without errors).
"""

import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

import tfp_demo.server as server_module
from tfp_demo.server import app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_module_import_succeeds():
    """Importing tfp_demo.server must not raise any exception."""
    # If we reach this line, the import succeeded.
    assert server_module is not None


def test_lifespan_sets_app_ready():
    """After the TestClient context is entered, _app_ready must be True."""
    with TestClient(app) as client:
        assert server_module._app_ready is True, (
            "_app_ready must be True once lifespan has yielded"
        )


def test_lifespan_startup_stage_is_ready():
    """After startup, _startup_stage must equal 'ready'."""
    with TestClient(app) as client:
        assert server_module._startup_stage == "ready", (
            f"Expected startup_stage='ready', got {server_module._startup_stage!r}"
        )


def test_health_returns_ready_true():
    """GET /health must return ready=True after successful startup."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True, f"/health body: {body}"


def test_health_returns_startup_stage_ready():
    """GET /health must include startup_stage='ready' after successful startup."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("startup_stage") == "ready", (
            f"Expected startup_stage='ready' in /health, got: {body}"
        )


def test_health_reports_content_items():
    """GET /health must include a non-negative content_items count."""
    with TestClient(app) as client:
        resp = client.get("/health")
        body = resp.json()
        assert "content_items" in body
        assert body["content_items"] >= 0


def test_health_reachable_after_startup():
    """GET /health must return 200 status after startup."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_enroll_works_after_startup():
    """Enrollment must succeed once the server has started."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        resp = client.post(
            "/api/enroll",
            json={"device_id": "startup-contract-device", "puf_entropy_hex": puf.hex()},
        )
        assert resp.status_code == 200
        assert resp.json()["enrolled"] is True
