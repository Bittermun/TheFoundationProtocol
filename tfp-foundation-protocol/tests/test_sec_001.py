# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import os
import pytest
from fastapi.testclient import TestClient

# Mock the environment variable before importing the app
os.environ["TFP_MAX_UPLOAD_BYTES"] = "100"

import tfp_demo.server as demo_server
from tfp_demo.server import app

@pytest.fixture(autouse=True)
def mock_upload_bytes_limit(monkeypatch):
    monkeypatch.setattr(demo_server, "TFP_MAX_UPLOAD_BYTES", 100)
    yield

def test_upload_size_limit_enforced():
    """SEC-001: Rejects uploads exceeding TFP_MAX_UPLOAD_BYTES with 413."""
    assert demo_server.TFP_MAX_UPLOAD_BYTES == 100
    
    with TestClient(app) as client:
        upload_id = "test-session-limit"
        
        # 1. Small chunk should succeed (50 bytes)
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/0",
            content=b"A" * 50
        )
        assert resp.status_code == 200
        
        # 2. Another chunk that stays within limit (50 bytes)
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/1",
            content=b"B" * 50
        )
        assert resp.status_code == 200
        
        # 3. Third chunk that exceeds cumulative limit (1 byte)
        # Total would be 101 bytes
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/2",
            content=b"C" * 1
        )
        assert resp.status_code == 413
        assert "Upload size limit exceeded" in resp.json()["detail"]

def test_upload_single_large_chunk_rejected():
    """SEC-001: Rejects a single chunk that is larger than the limit."""
    with TestClient(app) as client:
        upload_id = "test-session-large-single"
        
        # Single chunk of 101 bytes
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/0",
            content=b"X" * 101
        )
        assert resp.status_code == 413

def test_upload_replacement_chunk_limit():
    """SEC-001: Correctly handles chunk replacement and size tracking."""
    with TestClient(app) as client:
        upload_id = "test-session-replace"
        
        # 1. Upload 90 bytes to chunk 0
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/0",
            content=b"A" * 90
        )
        assert resp.status_code == 200
        
        # 2. Replace chunk 0 with 20 bytes (total 20 bytes)
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/0",
            content=b"B" * 20
        )
        assert resp.status_code == 200
        
        # 3. Upload 80 bytes to chunk 1 (total 100 bytes) - should succeed
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/1",
            content=b"C" * 80
        )
        assert resp.status_code == 200
        
        # 4. Upload 1 more byte (total 101 bytes) - should fail
        resp = client.post(
            f"/api/upload/chunk/{upload_id}/2",
            content=b"D" * 1
        )
        assert resp.status_code == 413
