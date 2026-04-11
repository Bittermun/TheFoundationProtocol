"""
IPFSBridge - Lightweight HTTP client bridge from TFP to IPFS.

Connects TFP content hashes to IPFS CIDs via the kubo HTTP API
(default endpoint: http://127.0.0.1:5001/api/v0/).

This is NOT a full IPFS node — it is a thin HTTP adapter that:
- Pins TFP content to a local or remote kubo node
- Retrieves content from IPFS by CID
- Maintains a local TFP-hash ↔ CID mapping table
- Falls back gracefully when no kubo node is reachable

Usage:
    bridge = IPFSBridge()
    result = bridge.pin(b"my content", metadata={"title": "Test"})
    if result.pinned:
        content = bridge.get(result.cid)

Offline mode (no kubo required):
    bridge = IPFSBridge(offline=True)
    result = bridge.pin(b"content")   # returns result with pinned=False, cid="offline:<hash>"
"""

import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attempt to import httpx; fall back to a minimal stub so unit tests can
# run without the live dependency when the module is imported.
# ---------------------------------------------------------------------------
try:
    import httpx as _httpx

    _HTTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]
    _HTTP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public exceptions / result types
# ---------------------------------------------------------------------------


class IPFSBridgeError(Exception):
    """Raised for unrecoverable bridge configuration errors."""


class IPFSPinResult:
    """Result of a pin operation."""

    def __init__(
        self,
        content_hash: str,
        cid: str,
        size_bytes: int,
        pinned: bool,
        error: Optional[str] = None,
    ):
        self.content_hash = content_hash
        self.cid = cid
        self.size_bytes = size_bytes
        self.pinned = pinned
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "cid": self.cid,
            "size_bytes": self.size_bytes,
            "pinned": self.pinned,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# IPFSBridge
# ---------------------------------------------------------------------------


class IPFSBridge:
    """
    Lightweight TFP → IPFS bridge using the kubo HTTP API.

    Args:
        api_url: Base URL of the kubo HTTP API (default: http://127.0.0.1:5001).
        timeout_seconds: HTTP request timeout.
        offline: If True, all network calls are suppressed; useful for testing.
    """

    DEFAULT_API_URL = "http://127.0.0.1:5001"

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        timeout_seconds: int = 10,
        offline: bool = False,
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.offline = offline

        # Bidirectional mapping: TFP hash ↔ IPFS CID
        self._hash_to_cid: Dict[str, str] = {}
        self._cid_to_hash: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pin(
        self, content: bytes, metadata: Optional[Dict[str, Any]] = None
    ) -> IPFSPinResult:
        """
        Add and pin content to IPFS.

        Computes SHA3-256 of the content for the TFP-side identifier,
        then submits the raw bytes to kubo's ``/api/v0/add`` endpoint.

        Args:
            content: Raw bytes to pin.
            metadata: Optional metadata (stored in result but not uploaded separately).

        Returns:
            IPFSPinResult with ``pinned=True`` and the resulting CID on success.
        """
        if not content:
            raise ValueError("Cannot pin empty content")

        content_hash = hashlib.sha3_256(content).hexdigest()

        if self.offline:
            # Return a deterministic stub without any network call
            stub_cid = f"offline:{content_hash[:20]}"
            return IPFSPinResult(
                content_hash=content_hash,
                cid=stub_cid,
                size_bytes=len(content),
                pinned=False,
                error="offline mode",
            )

        try:
            response = self._post(
                "/api/v0/add",
                files={"file": content},
                params={"pin": "true"},
            )
            if response.status_code == 200:
                data = response.json()
                cid = data.get("Hash", "")
                self.record_mapping(content_hash, cid)
                return IPFSPinResult(
                    content_hash=content_hash,
                    cid=cid,
                    size_bytes=len(content),
                    pinned=True,
                )
            return IPFSPinResult(
                content_hash=content_hash,
                cid="",
                size_bytes=0,
                pinned=False,
                error=f"HTTP {response.status_code}",
            )
        except Exception as exc:
            logger.warning("IPFS pin failed: %s", exc)
            return IPFSPinResult(
                content_hash=content_hash,
                cid="",
                size_bytes=0,
                pinned=False,
                error=str(exc),
            )

    def get(self, cid: str) -> Optional[bytes]:
        """
        Retrieve content from IPFS by CID.

        Args:
            cid: IPFS content identifier.

        Returns:
            Raw bytes, or ``None`` if not found / unreachable.
        """
        if self.offline:
            return None

        try:
            response = self._post("/api/v0/cat", params={"arg": cid})
            if response.status_code == 200 and response.content:
                return response.content
            return None
        except Exception as exc:
            logger.warning("IPFS get failed for cid=%s: %s", cid, exc)
            return None

    def health_check(self) -> Dict[str, Any]:
        """
        Check whether the kubo node is reachable.

        Returns:
            ``{"available": bool, "version": str | None, "error": str | None}``
        """
        if self.offline:
            return {"available": False, "version": None, "error": "offline mode"}

        try:
            response = self._post("/api/v0/id")
            if response.status_code == 200:
                data = response.json()
                return {
                    "available": True,
                    "version": data.get("AgentVersion"),
                    "error": None,
                }
            return {
                "available": False,
                "version": None,
                "error": f"HTTP {response.status_code}",
            }
        except Exception as exc:
            return {"available": False, "version": None, "error": str(exc)}

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def record_mapping(self, content_hash: str, cid: str) -> None:
        """Store a TFP hash ↔ CID mapping."""
        self._hash_to_cid[content_hash] = cid
        self._cid_to_hash[cid] = content_hash

    def get_cid_for_hash(self, content_hash: str) -> Optional[str]:
        """Return the IPFS CID for a TFP content hash, or None."""
        return self._hash_to_cid.get(content_hash)

    def get_hash_for_cid(self, cid: str) -> Optional[str]:
        """Return the TFP content hash for an IPFS CID, or None."""
        return self._cid_to_hash.get(cid)

    def export_mappings(self) -> Dict[str, str]:
        """Return a copy of the hash→CID mapping table."""
        return dict(self._hash_to_cid)

    # ------------------------------------------------------------------
    # Internal HTTP helper (injectable for testing)
    # ------------------------------------------------------------------

    def _post(self, path: str, **kwargs):
        """Thin wrapper around httpx.post — injectable in tests."""
        if not _HTTP_AVAILABLE:
            raise IPFSBridgeError("httpx is not installed; cannot make HTTP requests")
        url = f"{self.api_url}{path}"
        # Explicitly verify SSL/TLS certificates to prevent MITM attacks
        # Allow override via kwargs for testing with custom certs
        if "verify" not in kwargs:
            kwargs["verify"] = True
        return _httpx.post(url, timeout=self.timeout_seconds, **kwargs)
