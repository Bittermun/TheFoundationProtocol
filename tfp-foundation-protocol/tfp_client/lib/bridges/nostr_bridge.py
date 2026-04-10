"""
NostrBridge - NIP-01 Nostr event publisher for TFP content announcements.

Publishes TFP content announcements as Nostr events so that Nostr relays and
clients can discover and verify TFP content without running a full TFP stack.

This is NOT a full Nostr node — it is a thin adapter that:
- Creates well-formed NIP-01 events (RFC-serialized, SHA-256 id, Schnorr sig)
- Publishes them to one configurable relay via a simple WebSocket send
- Maintains a local history of published events
- Falls back gracefully when the relay is unreachable

NIP-01 event format:
    {
        "id":         "<32-bytes-sha256-of-serialized-event hex>",
        "pubkey":     "<32-bytes-secp256k1-pubkey hex>",
        "created_at": <unix timestamp>,
        "kind":       <integer>,
        "tags":       [["t", "tfp"], ...],
        "content":    "<json string>",
        "sig":        "<64-bytes-schnorr-sig hex>"
    }

TFP-specific event kind: 30078  (parameterized replaceable, app-specific)

Usage:
    bridge = NostrBridge(privkey=os.urandom(32))
    event = bridge.publish_content_announcement(hash_hex, metadata)

Offline (no relay required):
    bridge = NostrBridge(offline=True)
    event = bridge.publish_content_announcement(hash_hex, metadata)
"""

import hashlib
import hmac as _hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TFP-specific Nostr event kind
# ---------------------------------------------------------------------------

TFP_CONTENT_KIND: int = 30078  # parameterized replaceable, application-specific

# ---------------------------------------------------------------------------
# Secp256k1 field / order constants (simplified Schnorr, no external lib)
# NIP-01 uses secp256k1 Schnorr (BIP-340).  For a pure-Python implementation
# we use the secp256k1 curve constants and a simplified BIP-340 Schnorr.
# ---------------------------------------------------------------------------

_P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F  # field prime
_N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141  # group order
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _mod_inv(a: int, m: int) -> int:
    """Extended Euclidean modular inverse."""
    if a == 0:
        return 0
    lm, hm = 1, 0
    lo, hi = a % m, m
    while lo > 1:
        ratio = hi // lo
        lm, hm = hm - lm * ratio, lm
        lo, hi = hi - lo * ratio, lo
    return lm % m


def _point_add(P, Q):
    """Add two secp256k1 points (affine, None = point at infinity)."""
    if P is None:
        return Q
    if Q is None:
        return P
    if P[0] == Q[0]:
        if P[1] != Q[1]:
            return None
        # Point doubling
        lam = (3 * P[0] * P[0] * _mod_inv(2 * P[1], _P)) % _P
    else:
        lam = ((Q[1] - P[1]) * _mod_inv(Q[0] - P[0], _P)) % _P
    x = (lam * lam - P[0] - Q[0]) % _P
    y = (lam * (P[0] - x) - P[1]) % _P
    return (x, y)


def _point_mul(k: int, P):
    """Scalar multiplication on secp256k1."""
    result = None
    addend = P
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


_G_POINT = (_GX, _GY)


def _derive_pubkey_bytes(privkey: bytes) -> bytes:
    """Derive the 32-byte x-only public key from a 32-byte private key."""
    x = int.from_bytes(privkey, "big") % _N
    if x == 0:
        raise ValueError("Invalid private key")
    P = _point_mul(x, _G_POINT)
    assert P is not None
    return P[0].to_bytes(32, "big")


def _schnorr_sign(privkey: bytes, msg32: bytes) -> bytes:
    """
    BIP-340 Schnorr signature (simplified).

    Returns 64-byte signature: R.x (32) || s (32).
    """
    sk = int.from_bytes(privkey, "big") % _N
    # Deterministic nonce per RFC 6979 style: k = H(privkey || msg)
    k_raw = int.from_bytes(
        hashlib.sha256(privkey + msg32).digest(), "big"
    ) % _N
    if k_raw == 0:
        k_raw = 1
    R = _point_mul(k_raw, _G_POINT)
    assert R is not None
    # If R.y is odd, negate k (BIP-340 even-R requirement)
    if R[1] % 2 != 0:
        k_raw = _N - k_raw
        R = _point_mul(k_raw, _G_POINT)
        assert R is not None

    P = _point_mul(sk, _G_POINT)
    assert P is not None
    # If P.y is odd, negate sk (BIP-340 even-P requirement)
    if P[1] % 2 != 0:
        sk = _N - sk

    Rx = R[0].to_bytes(32, "big")
    Px = P[0].to_bytes(32, "big")
    e = int.from_bytes(
        hashlib.sha256(Rx + Px + msg32).digest(), "big"
    ) % _N
    s = (k_raw + e * sk) % _N
    return Rx + s.to_bytes(32, "big")


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class NostrBridgeError(Exception):
    """Raised for unrecoverable bridge errors."""


# ---------------------------------------------------------------------------
# NostrEvent
# ---------------------------------------------------------------------------

class NostrEvent:
    """
    A well-formed NIP-01 Nostr event.

    Use ``NostrEvent.create(...)`` to construct — direct construction is for
    deserialization only.
    """

    def __init__(
        self,
        id: str,
        pubkey: str,
        created_at: int,
        kind: int,
        tags: List[List[str]],
        content: str,
        sig: str,
    ):
        self.id = id
        self.pubkey = pubkey
        self.created_at = created_at
        self.kind = kind
        self.tags = tags
        self.content = content
        self.sig = sig

    @classmethod
    def create(
        cls,
        privkey: bytes,
        kind: int,
        content: str,
        tags: List[List[str]],
        created_at: Optional[int] = None,
    ) -> "NostrEvent":
        """
        Create and sign a NIP-01 event.

        Args:
            privkey: 32-byte private key.
            kind: Nostr event kind integer.
            content: Arbitrary string content.
            tags: List of tag arrays, e.g. ``[["t", "tfp"]]``.
            created_at: Unix timestamp (defaults to ``int(time.time())``).
        """
        if created_at is None:
            created_at = int(time.time())

        pubkey_bytes = _derive_pubkey_bytes(privkey)
        pubkey_hex = pubkey_bytes.hex()

        # NIP-01 canonical serialization for id computation
        serialized = json.dumps(
            [0, pubkey_hex, created_at, kind, tags, content],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        event_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        id_bytes = bytes.fromhex(event_id)
        sig_bytes = _schnorr_sign(privkey, id_bytes)
        sig_hex = sig_bytes.hex()

        return cls(
            id=event_id,
            pubkey=pubkey_hex,
            created_at=created_at,
            kind=kind,
            tags=tags,
            content=content,
            sig=sig_hex,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# NostrBridge
# ---------------------------------------------------------------------------

class NostrBridge:
    """
    Thin TFP → Nostr bridge.

    Publishes TFP content announcements as NIP-01 Nostr events.

    Args:
        privkey: 32-byte private key (generated randomly if not provided).
        relay_url: WebSocket URL of the Nostr relay.
        offline: If True, suppress all network calls.
    """

    DEFAULT_RELAY = "wss://relay.damus.io"

    def __init__(
        self,
        privkey: Optional[bytes] = None,
        relay_url: str = DEFAULT_RELAY,
        offline: bool = False,
    ):
        if privkey is None:
            privkey = secrets.token_bytes(32)
        self._privkey = privkey
        self.relay_url = relay_url
        self.offline = offline
        self.pubkey_hex = _derive_pubkey_bytes(privkey).hex()
        self._history: List[NostrEvent] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_content_announcement(
        self,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NostrEvent:
        """
        Build a TFP content announcement event (does not publish).

        Args:
            content_hash: Hex SHA3-256 content hash.
            metadata: Optional dict with title, tags, domain, etc.

        Returns:
            Unsigned (but id-computed) NostrEvent.
        """
        if metadata is None:
            metadata = {}

        payload = {"hash": content_hash, **metadata}
        content_str = json.dumps(payload, separators=(",", ":"))

        tags: List[List[str]] = [["t", "tfp"]]
        for tag in metadata.get("tags", []):
            tags.append(["t", str(tag)])
        if "domain" in metadata:
            tags.append(["d", metadata["domain"]])

        return NostrEvent.create(
            privkey=self._privkey,
            kind=TFP_CONTENT_KIND,
            content=content_str,
            tags=tags,
        )

    def publish_content_announcement(
        self,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NostrEvent:
        """
        Build and publish a TFP content announcement to the relay.

        Args:
            content_hash: Hex SHA3-256 content hash.
            metadata: Optional metadata dict.

        Returns:
            The NostrEvent (regardless of delivery success).
        """
        event = self.build_content_announcement(content_hash, metadata)
        self._history.append(event)

        if not self.offline:
            try:
                self._send_to_relay(event)
            except Exception as exc:
                logger.warning("Nostr publish failed (relay=%s): %s", self.relay_url, exc)

        return event

    def get_history(self) -> List[NostrEvent]:
        """Return list of published events (newest last)."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear local event history."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Internal helpers (injectable for testing)
    # ------------------------------------------------------------------

    def _send_to_relay(self, event: NostrEvent) -> bool:
        """
        Send a NIP-01 EVENT message to the relay.

        Uses a synchronous websockets send if the library is available;
        falls back to a logging-only stub when not installed.

        Returns:
            True if sent successfully, False otherwise.
        """
        msg = json.dumps(["EVENT", event.to_dict()], separators=(",", ":"))
        try:
            import websockets.sync.client as _ws_sync  # websockets ≥ 11
            with _ws_sync.connect(self.relay_url, open_timeout=5) as ws:
                ws.send(msg)
                return True
        except ImportError:
            # websockets not installed — log and return False (graceful degradation)
            logger.debug("websockets not installed; event not delivered: id=%s", event.id)
            return False
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
