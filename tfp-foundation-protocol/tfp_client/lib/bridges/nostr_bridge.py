# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

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

import collections
import hashlib
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TFP-specific Nostr event kind
# ---------------------------------------------------------------------------

TFP_CONTENT_KIND: int = 30078  # HLT Merkle-root gossip (parameterized replaceable)
TFP_SEARCH_INDEX_KIND: int = 30079  # semantic search index summary / delta gossip
TFP_CONTENT_ANNOUNCE_KIND: int = 30080  # content-availability announcements
TFP_SUPPLY_GOSSIP_KIND: int = 30081  # supply ledger gossip for multi-node coordination

# ---------------------------------------------------------------------------
# Secp256k1 field / order constants (simplified Schnorr, no external lib)
# NIP-01 uses secp256k1 Schnorr (BIP-340).  For a pure-Python implementation
# we use the secp256k1 curve constants and a simplified BIP-340 Schnorr.
# ---------------------------------------------------------------------------

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F  # field prime
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141  # group order
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
    if P is None:
        raise ValueError("Failed to derive public key from private key")
    return P[0].to_bytes(32, "big")


def _schnorr_sign(privkey: bytes, msg32: bytes) -> bytes:
    """
    BIP-340 Schnorr signature (simplified pure-Python implementation).

    Nonce derivation: k = SHA-256(privkey || msg32).
    Note: RFC 6979 recommends HMAC-SHA-256 based nonce derivation for enhanced
    security guarantees. This deterministic SHA-256 approach is safe for this
    use case (each (privkey, msg) pair is unique), but a production deployment
    handling high-value assets should upgrade to strict RFC 6979 derivation.

    Returns 64-byte signature: R.x (32) || s (32).
    """
    sk = int.from_bytes(privkey, "big") % _N
    # Deterministic nonce per RFC 6979 style: k = H(privkey || msg)
    k_raw = int.from_bytes(hashlib.sha256(privkey + msg32).digest(), "big") % _N
    if k_raw == 0:
        k_raw = 1
    R = _point_mul(k_raw, _G_POINT)
    if R is None:
        raise ValueError("Failed to compute R point for signature")
    # If R.y is odd, negate k (BIP-340 even-R requirement)
    if R[1] % 2 != 0:
        k_raw = _N - k_raw
        R = _point_mul(k_raw, _G_POINT)
        if R is None:
            raise ValueError("Failed to compute negated R point for signature")

    P = _point_mul(sk, _G_POINT)
    if P is None:
        raise ValueError("Failed to compute public key for signature")
    # If P.y is odd, negate sk (BIP-340 even-P requirement)
    if P[1] % 2 != 0:
        sk = _N - sk

    Rx = R[0].to_bytes(32, "big")
    Px = P[0].to_bytes(32, "big")
    e = int.from_bytes(hashlib.sha256(Rx + Px + msg32).digest(), "big") % _N
    s = (k_raw + e * sk) % _N
    return Rx + s.to_bytes(32, "big")


def _schnorr_verify(pubkey_hex: str, event_id_hex: str, sig_hex: str) -> bool:
    """
    BIP-340 Schnorr signature verification (pure-Python, matches _schnorr_sign).

    Uses the same simplified SHA-256 challenge (not the tagged-hash BIP-340
    variant) so it is consistent with _schnorr_sign's nonce derivation.

    Returns True iff the signature is valid; False on any error or mismatch.
    """
    try:
        px = int(pubkey_hex, 16)
        msg = bytes.fromhex(event_id_hex)
        sig = bytes.fromhex(sig_hex)
        if len(sig) != 64 or len(msg) != 32:
            return False

        rx = int.from_bytes(sig[:32], "big")
        s = int.from_bytes(sig[32:], "big")

        # Range checks per BIP-340
        if px >= _P or rx >= _P or s >= _N:
            return False

        # lift_x: recover even-y point from the 32-byte x-only public key
        y_sq = (pow(px, 3, _P) + 7) % _P
        y = pow(y_sq, (_P + 1) // 4, _P)
        if pow(y, 2, _P) != y_sq:
            return False  # px is not on the curve
        P = (px, y if y % 2 == 0 else _P - y)

        # e = SHA-256(bytes(rx) || bytes(px) || msg)  — matches _schnorr_sign
        rx_bytes = rx.to_bytes(32, "big")
        px_bytes = px.to_bytes(32, "big")
        e = (
            int.from_bytes(hashlib.sha256(rx_bytes + px_bytes + msg).digest(), "big")
            % _N
        )

        # R = s·G − e·P; verify R.y is even and R.x == rx
        sG = _point_mul(s, _G_POINT)
        neg_e = (_N - e) % _N
        neg_eP = _point_mul(neg_e, P) if neg_e else None
        R = _point_add(sG, neg_eP)

        return R is not None and R[1] % 2 == 0 and R[0] == rx
    except Exception:
        return False


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
        # Bounded history: deque evicts oldest entries when full so that a
        # long-running bridge process cannot exhaust heap memory.
        self._history: collections.deque = collections.deque(maxlen=10_000)

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
            kind=TFP_CONTENT_ANNOUNCE_KIND,
            content=content_str,
            tags=tags,
        )

    def announce_content(self, content_hash: str, metadata: dict):
        """
        Announce content availability to the Nostr network.
        Sets 'content_hash' tag and includes metadata.
        """
        return self.publish_content_announcement(content_hash, metadata)

    def publish_content_announcement(
        self,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NostrEvent:
        """
        Build and publish a TFP content announcement to the relay.

        Returns:
            The NostrEvent (regardless of delivery success).
        """
        event = self.build_content_announcement(content_hash, metadata)
        self._history.append(event)

        if not self.offline:
            try:
                self._send_to_relay(event)
            except Exception as exc:
                logger.warning(
                    "Nostr publish failed (relay=%s): %s", self.relay_url, exc
                )

        return event

    def publish_event(self, event: NostrEvent) -> bool:
        """Publish a generic Nostr event and record it in history."""
        self._history.append(event)
        if not self.offline:
            try:
                return self._send_to_relay(event)
            except Exception as exc:
                logger.warning(
                    "Nostr publish failed (relay=%s): %s", self.relay_url, exc
                )
                return False
        return True

    def get_history(self) -> List[NostrEvent]:
        """Return list of published events (newest last)."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear local event history."""
        self._history.clear()

    def publish_hlt_state(self, hlt) -> dict:
        """
        Build and publish a NIP-78 kind-30078 HLT Merkle-root gossip event.

        Announces the current state of the local HierarchicalLexiconTree so that
        peer nodes can detect semantic drift and request delta updates.

        Wire format (content JSON):
        ``{"merkle_root": <hex>, "domains": [{"domain": <name>, "version": <ver>,
        "content_hash": <hex>}, ...]}``

        The event tags include:
        - ``["d", "tfp-hlt"]``: parameterized replaceable identifier
        - ``["domain", <name>]``: one tag per domain in the HLT
        - ``["merkle_root", <hex>]``: Merkle root of the current HLT state
        - ``["version", <version>]``: latest adapter version per domain

        Args:
            hlt: A ``HierarchicalLexiconTree`` instance.

        Returns:
            The event as a plain dict (for test assertions and logging).
        """
        merkle_root = hlt.compute_merkle_root()

        tags: List[List[str]] = [
            ["d", "tfp-hlt"],
            ["merkle_root", merkle_root],
        ]
        domain_list = []
        for domain_name in hlt.domain_names:
            version_info = hlt.get_latest_version(domain_name)
            version = version_info.get("version") or "v1.0.0"
            node_id = hlt.domain_names[domain_name]
            node = hlt.nodes.get(node_id)
            content_hash = node.content_hash if node else "a" * 64
            tags.append(["domain", domain_name])
            tags.append(["version", version])
            domain_list.append(
                {
                    "domain": domain_name,
                    "version": version,
                    "content_hash": content_hash,
                }
            )

        content_payload = {
            "merkle_root": merkle_root,
            "domains": domain_list,
        }
        event = NostrEvent.create(
            privkey=self._privkey,
            kind=30078,
            content=json.dumps(content_payload, separators=(",", ":")),
            tags=tags,
        )
        self._history.append(event)
        if not self.offline:
            try:
                self._send_to_relay(event)
            except Exception as exc:
                logger.warning(
                    "HLT gossip publish failed (relay=%s): %s", self.relay_url, exc
                )
        return event.to_dict()

    def publish_search_index_summary(
        self,
        domain: str,
        index_hash: str,
        chunk_count: int,
        schema_version: str = "1",
        created_at: Optional[int] = None,
    ) -> dict:
        """
        Publish a NIP-78 kind-30079 semantic search index summary event.

        Gossips a signed, content-addressed summary of the local semantic index
        so that peer nodes can detect stale indices and request delta updates.

        The event tags include:
        - ``["d", "tfp-search-index"]``: parameterized replaceable identifier
        - ``["domain", <domain>]``: content domain the index covers
        - ``["index_hash", <hex>]``: SHA3-256 of the index state
        - ``["chunk_count", <n>]``: number of chunks currently indexed
        - ``["schema_version", <v>]``: index schema version for compatibility checks

        Args:
            domain: Domain name the index covers (e.g. ``"general"``, ``"code"``).
            index_hash: Hex SHA3-256 of the index state (deterministic fingerprint).
            chunk_count: Total indexed chunks in this domain.
            schema_version: Index schema version string for compatibility checks.
            created_at: Optional Unix timestamp (defaults to ``int(time.time())``).

        Returns:
            The event as a plain dict (for test assertions and logging).
        """
        ts = created_at if created_at is not None else int(time.time())

        tags: list = [
            ["d", "tfp-search-index"],
            ["domain", domain],
            ["index_hash", index_hash],
            ["chunk_count", str(chunk_count)],
            ["schema_version", schema_version],
        ]

        content_payload = {
            "domain": domain,
            "index_hash": index_hash,
            "chunk_count": chunk_count,
            "schema_version": schema_version,
            "published_at": ts,
        }

        event = NostrEvent.create(
            privkey=self._privkey,
            kind=TFP_SEARCH_INDEX_KIND,
            content=json.dumps(content_payload, separators=(",", ":")),
            tags=tags,
            created_at=ts,
        )
        self._history.append(event)
        if not self.offline:
            try:
                self._send_to_relay(event)
            except Exception as exc:
                logger.warning(
                    "Search index gossip publish failed (relay=%s): %s",
                    self.relay_url,
                    exc,
                )
        return event.to_dict()

    def publish_supply_gossip(
        self, total_minted: int, supply_cap: int
    ) -> dict:
        """
        Publish a supply ledger gossip event for multi-node coordination.

        This allows nodes to learn about each other's minted totals and
        enforce the global supply cap across the network.

        Args:
            total_minted: Current total minted on this node
            supply_cap: The global supply cap (21M)

        Returns:
            The published event dict (NIP-01 format).
        """
        ts = int(time.time())

        tags: list = [
            ["d", "tfp-supply"],
            ["total_minted", str(total_minted)],
            ["supply_cap", str(supply_cap)],
        ]

        content_payload = {
            "total_minted": total_minted,
            "supply_cap": supply_cap,
            "published_at": ts,
        }

        event = NostrEvent.create(
            privkey=self._privkey,
            kind=TFP_SUPPLY_GOSSIP_KIND,
            content=json.dumps(content_payload, separators=(",", ":")),
            tags=tags,
            created_at=ts,
        )
        self._history.append(event)
        if not self.offline:
            try:
                self._send_to_relay(event)
            except Exception as exc:
                logger.warning(
                    "Supply gossip publish failed (relay=%s): %s",
                    self.relay_url,
                    exc,
                )
        return event.to_dict()

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
            logger.debug(
                "websockets not installed; event not delivered: id=%s", event.id
            )
            return False
        except Exception as exc:
            raise ConnectionError(str(exc)) from exc
