"""
TDD tests for Nostr bridge adapter.

Written BEFORE implementation (Test-Driven Development).

Contract:
- NostrBridge: publish TFP content announcements as NIP-01 Nostr events
- NostrEvent: well-formed NIP-01 event (id, pubkey, created_at, kind, tags, content, sig)
- Graceful fallback when relay unreachable
- No real network calls in tests (all mocked)
- Uses pure-Python Schnorr signing (same approach as zkp_real.py)
"""

import json
import time
from unittest.mock import patch

import pytest

try:
    from tfp_client.lib.bridges.nostr_bridge import (
        TFP_CONTENT_KIND,
        TFP_CONTENT_ANNOUNCE_KIND,
        NostrBridge,
        NostrBridgeError,
        NostrEvent,
        _schnorr_verify,
    )

    NOSTR_AVAILABLE = True
except ImportError:
    NOSTR_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not NOSTR_AVAILABLE, reason="NostrBridge not yet implemented"
)

SAMPLE_HASH = "b" * 64
SAMPLE_METADATA = {
    "title": "Test Content",
    "tags": ["education", "science"],
    "domain": "science",
}


class TestNostrEventConstruction:
    """Tests for well-formed NIP-01 Nostr events."""

    def test_event_has_required_fields(self):
        privkey = b"\x01" * 32
        event = NostrEvent.create(
            privkey=privkey,
            kind=TFP_CONTENT_KIND,
            content=json.dumps({"hash": SAMPLE_HASH}),
            tags=[["t", "tfp"]],
        )
        for field in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
            assert hasattr(event, field), f"missing field: {field}"

    def test_event_id_is_32_bytes_hex(self):
        privkey = b"\x02" * 32
        event = NostrEvent.create(
            privkey=privkey,
            kind=1,
            content="hello",
            tags=[],
        )
        assert len(event.id) == 64  # 32 bytes as hex
        bytes.fromhex(event.id)  # must be valid hex

    def test_event_sig_is_64_bytes_hex(self):
        privkey = b"\x03" * 32
        event = NostrEvent.create(privkey=privkey, kind=1, content="hi", tags=[])
        assert len(event.sig) == 128  # 64 bytes as hex

    def test_event_created_at_is_recent(self):
        privkey = b"\x04" * 32
        before = int(time.time()) - 2
        event = NostrEvent.create(privkey=privkey, kind=1, content="now", tags=[])
        after = int(time.time()) + 2
        assert before <= event.created_at <= after

    def test_event_kind_preserved(self):
        privkey = b"\x05" * 32
        event = NostrEvent.create(
            privkey=privkey, kind=TFP_CONTENT_KIND, content="x", tags=[]
        )
        assert event.kind == TFP_CONTENT_KIND

    def test_event_to_dict(self):
        privkey = b"\x06" * 32
        event = NostrEvent.create(privkey=privkey, kind=1, content="test", tags=[])
        d = event.to_dict()
        for field in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
            assert field in d

    def test_event_serializes_to_json(self):
        privkey = b"\x07" * 32
        event = NostrEvent.create(privkey=privkey, kind=1, content="test", tags=[])
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["kind"] == 1

    def test_event_id_deterministic(self):
        """Same inputs → same event id (canonical serialization)."""
        privkey = b"\x08" * 32
        ts = 1_700_000_000
        event_a = NostrEvent.create(
            privkey=privkey, kind=1, content="abc", tags=[], created_at=ts
        )
        event_b = NostrEvent.create(
            privkey=privkey, kind=1, content="abc", tags=[], created_at=ts
        )
        assert event_a.id == event_b.id

    def test_different_content_different_id(self):
        privkey = b"\x09" * 32
        ts = 1_700_000_000
        event_a = NostrEvent.create(
            privkey=privkey, kind=1, content="abc", tags=[], created_at=ts
        )
        event_b = NostrEvent.create(
            privkey=privkey, kind=1, content="xyz", tags=[], created_at=ts
        )
        assert event_a.id != event_b.id


class TestNostrBridgeConstruction:
    """Tests for NostrBridge construction."""

    def test_default_construction(self):
        bridge = NostrBridge()
        assert bridge is not None

    def test_custom_relay_url(self):
        bridge = NostrBridge(relay_url="wss://relay.example.com")
        assert bridge.relay_url == "wss://relay.example.com"

    def test_offline_mode(self):
        bridge = NostrBridge(offline=True)
        assert bridge.offline is True

    def test_generates_keypair_if_not_provided(self):
        bridge = NostrBridge(offline=True)
        assert bridge.pubkey_hex is not None
        assert len(bridge.pubkey_hex) == 64

    def test_accepts_existing_privkey(self):
        privkey = b"\xaa" * 32
        bridge = NostrBridge(privkey=privkey, offline=True)
        # pubkey should be derived deterministically from privkey
        assert bridge.pubkey_hex is not None


class TestNostrPublishAnnouncement:
    """Tests for publishing TFP content announcements to Nostr."""

    def test_build_announcement_event(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        event = bridge.build_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        assert isinstance(event, NostrEvent)
        assert event.kind == TFP_CONTENT_ANNOUNCE_KIND

    def test_announcement_contains_hash(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        event = bridge.build_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        content = json.loads(event.content)
        assert content.get("hash") == SAMPLE_HASH

    def test_announcement_contains_metadata(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        event = bridge.build_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        content = json.loads(event.content)
        assert "title" in content or "metadata" in content

    def test_announcement_has_tfp_tag(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        event = bridge.build_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        tag_values = [t[1] for t in event.tags if t[0] == "t"]
        assert "tfp" in tag_values

    def test_publish_offline_returns_event_not_sent(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        result = bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        assert isinstance(result, NostrEvent)

    def test_publish_with_mocked_relay(self):
        bridge = NostrBridge(
            offline=False, privkey=b"\x02" * 32, relay_url="wss://test"
        )
        with patch.object(bridge, "_send_to_relay", return_value=True) as mock_send:
            result = bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        assert isinstance(result, NostrEvent)
        mock_send.assert_called_once()

    def test_publish_handles_relay_error(self):
        """Relay failure should not raise — returns event with sent=False."""
        bridge = NostrBridge(privkey=b"\x03" * 32)
        with patch.object(
            bridge, "_send_to_relay", side_effect=ConnectionError("refused")
        ):
            result = bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        # Should still return the event (it was built, just not delivered)
        assert isinstance(result, NostrEvent)


class TestNostrEventHistory:
    """Tests for local event history tracking."""

    def test_history_starts_empty(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        assert bridge.get_history() == []

    def test_publish_adds_to_history(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        history = bridge.get_history()
        assert len(history) == 1

    def test_history_contains_event_id(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        event = bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        history = bridge.get_history()
        assert history[0].id == event.id

    def test_clear_history(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        bridge.publish_content_announcement(SAMPLE_HASH, SAMPLE_METADATA)
        bridge.clear_history()
        assert bridge.get_history() == []

    def test_multiple_announcements_tracked(self):
        bridge = NostrBridge(offline=True, privkey=b"\x01" * 32)
        for i in range(5):
            bridge.publish_content_announcement(f"hash_{i}" * 8, {"title": f"t{i}"})
        assert len(bridge.get_history()) == 5


class TestNostrTFPContentKind:
    """Tests for TFP_CONTENT_KIND constant."""

    def test_kind_is_integer(self):
        assert isinstance(TFP_CONTENT_KIND, int)

    def test_kind_in_custom_range(self):
        # NIP-01: kinds 1000-9999 are custom/application-specific
        # or ephemeral 20000-29999, parameterized replaceable 30000-39999
        assert TFP_CONTENT_KIND >= 1000


@pytest.mark.skipif(not NOSTR_AVAILABLE, reason="nostr_bridge not available")
class TestSchnorrVerify:
    """Tests for _schnorr_verify: BIP-340 round-trip with _schnorr_sign."""

    _PRIVKEY = b"\x01" * 32

    def _make_event(self, kind=30078, content="hello"):
        return NostrEvent.create(
            privkey=self._PRIVKEY, kind=kind, content=content, tags=[]
        )

    def test_valid_sig_verifies(self):
        ev = self._make_event()
        assert _schnorr_verify(ev.pubkey, ev.id, ev.sig) is True

    def test_wrong_sig_rejected(self):
        ev = self._make_event()
        bad_sig = "ff" * 64
        assert _schnorr_verify(ev.pubkey, ev.id, bad_sig) is False

    def test_wrong_id_rejected(self):
        ev = self._make_event()
        bad_id = "00" * 32
        assert _schnorr_verify(ev.pubkey, bad_id, ev.sig) is False

    def test_wrong_pubkey_rejected(self):
        ev = self._make_event()
        other = NostrEvent.create(privkey=b"\x02" * 32, kind=1, content="x", tags=[])
        assert _schnorr_verify(other.pubkey, ev.id, ev.sig) is False

    def test_different_privkeys_produce_different_sigs(self):
        ev1 = NostrEvent.create(privkey=b"\x01" * 32, kind=1, content="x", tags=[])
        ev2 = NostrEvent.create(privkey=b"\x02" * 32, kind=1, content="x", tags=[])
        assert ev1.sig != ev2.sig

    def test_sig_length_64_bytes(self):
        ev = self._make_event()
        assert len(bytes.fromhex(ev.sig)) == 64

    def test_garbage_pubkey_returns_false(self):
        ev = self._make_event()
        assert _schnorr_verify("zz" * 32, ev.id, ev.sig) is False

    def test_empty_strings_return_false(self):
        assert _schnorr_verify("", "", "") is False
