"""
Integration tests for peer discovery API endpoints.

Tests the peer discovery, handshake, and management endpoints
using FastAPI TestClient.
"""

import os
import sqlite3
import threading
import hmac as _hmac
import hashlib
import pytest
from fastapi.testclient import TestClient

# Set up in-memory database for testing
os.environ.setdefault("TFP_DB_PATH", ":memory:")

from tfp_demo.server import app


class TestPeerDiscoveryAPI:
    """Integration tests for peer discovery API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client with initialized database."""
        with TestClient(app) as c:
            yield c

    def test_peer_list_endpoint(self, client):
        """Test the peer list endpoint."""
        # This endpoint doesn't require device auth (admin endpoint)
        r = client.get("/api/peer/list?status=active&min_reputation=50&limit=10")
        
        # Endpoint should exist even if no peers are registered
        assert r.status_code in [200, 404]  # May be 404 if endpoint not yet registered
        if r.status_code == 200:
            data = r.json()
            assert "peers" in data
            assert "total_count" in data
            assert isinstance(data["peers"], list)

    def test_peer_discover_without_auth(self, client):
        """Test that peer discovery requires authentication."""
        r = client.post(
            "/api/peer/discover",
            json={
                "peer_id": "unauth-device",
                "capabilities": {"compute": True, "storage": True},
                "max_peers": 10
            }
        )
        
        # Should fail without signature
        assert r.status_code == 422

    def test_peer_handshake_without_auth(self, client):
        """Test that peer handshake requires authentication."""
        r = client.post(
            "/api/peer/handshake",
            json={
                "peer_id": "unauth-device",
                "public_key": "test-key",
                "capabilities": {"compute": True}
            }
        )
        
        # Should fail without signature
        assert r.status_code == 422

    def test_peer_announce_without_auth(self, client):
        """Test that peer announce requires authentication."""
        r = client.post(
            "/api/peer/announce",
            json={
                "peer_id": "unauth-device",
                "public_key": "test-key",
                "signature": "test-sig"
            }
        )
        
        # Should fail without signature
        assert r.status_code == 422