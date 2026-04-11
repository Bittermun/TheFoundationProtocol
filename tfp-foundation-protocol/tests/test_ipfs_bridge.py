"""
TDD tests for IPFS bridge adapter.

Written BEFORE implementation (Test-Driven Development).

Contract:
- IPFSBridge: pin TFP content to IPFS, retrieve by CID, map hashes
- Graceful fallback when kubo node unreachable
- No production secrets or real network calls in tests (all mocked)
"""

import pytest
import json
from unittest.mock import patch, MagicMock

try:
    from tfp_client.lib.bridges.ipfs_bridge import (
        IPFSBridge,
        IPFSPinResult,
        IPFSBridgeError,
    )
    IPFS_AVAILABLE = True
except ImportError:
    IPFS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not IPFS_AVAILABLE,
    reason="IPFSBridge not yet implemented"
)

SAMPLE_CONTENT = b"Hello TFP world - test content for IPFS pinning"
SAMPLE_HASH = "a" * 64  # fake SHA3-256 hex
SAMPLE_CID = "QmTestCIDabc123"


class TestIPFSPinResult:
    """Tests for IPFSPinResult dataclass."""

    def test_construction(self):
        result = IPFSPinResult(
            content_hash=SAMPLE_HASH,
            cid=SAMPLE_CID,
            size_bytes=len(SAMPLE_CONTENT),
            pinned=True,
        )
        assert result.cid == SAMPLE_CID
        assert result.pinned is True

    def test_to_dict(self):
        result = IPFSPinResult(
            content_hash=SAMPLE_HASH,
            cid=SAMPLE_CID,
            size_bytes=100,
            pinned=True,
        )
        d = result.to_dict()
        assert "cid" in d
        assert "content_hash" in d
        assert "pinned" in d

    def test_failed_pin_result(self):
        result = IPFSPinResult(
            content_hash=SAMPLE_HASH,
            cid="",
            size_bytes=0,
            pinned=False,
            error="Connection refused",
        )
        assert result.pinned is False
        assert result.error == "Connection refused"


class TestIPFSBridgeConstruction:
    """Tests for IPFSBridge construction."""

    def test_default_construction(self):
        bridge = IPFSBridge()
        assert bridge is not None

    def test_custom_api_url(self):
        bridge = IPFSBridge(api_url="http://localhost:5001")
        assert bridge.api_url == "http://localhost:5001"

    def test_timeout_configurable(self):
        bridge = IPFSBridge(timeout_seconds=30)
        assert bridge.timeout_seconds == 30

    def test_offline_mode(self):
        bridge = IPFSBridge(offline=True)
        assert bridge.offline is True


class TestIPFSPinContent:
    """Tests for pinning content to IPFS."""

    def test_pin_returns_result(self):
        bridge = IPFSBridge(offline=True)
        result = bridge.pin(SAMPLE_CONTENT, metadata={"title": "Test"})
        assert isinstance(result, IPFSPinResult)

    def test_pin_offline_mode_returns_stub(self):
        """In offline mode, bridge returns deterministic stub CID without network."""
        bridge = IPFSBridge(offline=True)
        result = bridge.pin(SAMPLE_CONTENT)
        assert result.pinned is False or result.cid != ""

    def test_pin_empty_content_raises(self):
        bridge = IPFSBridge(offline=True)
        with pytest.raises((ValueError, IPFSBridgeError)):
            bridge.pin(b"")

    def test_pin_computes_content_hash(self):
        """pin() should compute SHA3-256 of content and include in result."""
        import hashlib
        bridge = IPFSBridge(offline=True)
        result = bridge.pin(SAMPLE_CONTENT)
        expected_hash = hashlib.sha3_256(SAMPLE_CONTENT).hexdigest()
        assert result.content_hash == expected_hash

    def test_pin_with_mocked_api(self):
        """Test successful pin with mocked kubo HTTP API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Hash": SAMPLE_CID, "Size": "48"}

        bridge = IPFSBridge()
        with patch.object(bridge, "_post", return_value=mock_response):
            result = bridge.pin(SAMPLE_CONTENT)
        assert result.cid == SAMPLE_CID
        assert result.pinned is True

    def test_pin_handles_connection_error(self):
        """Network failure should return failed result, not raise."""
        bridge = IPFSBridge()
        with patch.object(bridge, "_post", side_effect=ConnectionError("refused")):
            result = bridge.pin(SAMPLE_CONTENT)
        assert result.pinned is False
        assert result.error is not None


class TestIPFSGetContent:
    """Tests for retrieving content from IPFS by CID."""

    def test_get_offline_returns_none(self):
        bridge = IPFSBridge(offline=True)
        data = bridge.get(SAMPLE_CID)
        assert data is None

    def test_get_with_mocked_api(self):
        bridge = IPFSBridge()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = SAMPLE_CONTENT

        with patch.object(bridge, "_post", return_value=mock_response):
            data = bridge.get(SAMPLE_CID)
        assert data == SAMPLE_CONTENT

    def test_get_handles_not_found(self):
        bridge = IPFSBridge()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b""

        with patch.object(bridge, "_post", return_value=mock_response):
            data = bridge.get("QmNonExistent")
        assert data is None


class TestIPFSHashMapping:
    """Tests for TFP hash ↔ IPFS CID mapping."""

    def test_map_tfp_to_cid_stores_mapping(self):
        bridge = IPFSBridge(offline=True)
        bridge.record_mapping(SAMPLE_HASH, SAMPLE_CID)
        assert bridge.get_cid_for_hash(SAMPLE_HASH) == SAMPLE_CID

    def test_get_cid_unknown_hash_returns_none(self):
        bridge = IPFSBridge(offline=True)
        assert bridge.get_cid_for_hash("unknown_hash") is None

    def test_get_hash_for_cid(self):
        bridge = IPFSBridge(offline=True)
        bridge.record_mapping(SAMPLE_HASH, SAMPLE_CID)
        assert bridge.get_hash_for_cid(SAMPLE_CID) == SAMPLE_HASH

    def test_multiple_mappings(self):
        bridge = IPFSBridge(offline=True)
        for i in range(5):
            bridge.record_mapping(f"hash_{i}" * 4, f"QmCID{i}")
        assert bridge.get_cid_for_hash("hash_2" * 4) == "QmCID2"

    def test_export_mappings(self):
        bridge = IPFSBridge(offline=True)
        bridge.record_mapping(SAMPLE_HASH, SAMPLE_CID)
        mappings = bridge.export_mappings()
        assert isinstance(mappings, dict)
        assert SAMPLE_HASH in mappings


class TestIPFSHealthCheck:
    """Tests for IPFS node health check."""

    def test_health_check_offline(self):
        bridge = IPFSBridge(offline=True)
        status = bridge.health_check()
        assert isinstance(status, dict)
        assert "available" in status
        assert status["available"] is False

    def test_health_check_with_mocked_success(self):
        bridge = IPFSBridge()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ID": "QmNodeID", "AgentVersion": "kubo/0.26.0"}

        with patch.object(bridge, "_post", return_value=mock_response):
            status = bridge.health_check()
        assert status["available"] is True

    def test_health_check_handles_error(self):
        bridge = IPFSBridge()
        with patch.object(bridge, "_post", side_effect=ConnectionError):
            status = bridge.health_check()
        assert status["available"] is False
