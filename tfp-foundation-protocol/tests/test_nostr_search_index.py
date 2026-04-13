"""
tests/test_nostr_search_index.py

Tests for Nostr kind-30079 semantic search index gossip.

Verifies:
- NostrBridge.publish_search_index_summary() creates a well-formed kind-30079 event.
- The event is added to the bridge's local history (offline mode).
- _on_nostr_event() dispatches kind-30079 to _handle_search_index_event().
- Replay guard: events older than _SEARCH_INDEX_REPLAY_WINDOW_S are dropped.
- Events with malformed fields are silently ignored.
- Valid events increment the tfp_search_index_gossip_received_total metric.
"""

import json
import os
import time

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_client.lib.bridges.nostr_bridge import (
    NostrBridge,
    NostrEvent,
    TFP_SEARCH_INDEX_KIND,
)

_TEST_PRIVKEY = b"\xbb" * 32


def _signed_event(kind: int, content: str, tags=None, created_at=None) -> dict:
    """Return a properly signed NIP-01 event dict for use in server ingest tests."""
    return NostrEvent.create(
        privkey=_TEST_PRIVKEY,
        kind=kind,
        content=content,
        tags=tags or [],
        created_at=created_at,
    ).to_dict()


# ---------------------------------------------------------------------------
# NostrBridge.publish_search_index_summary unit tests
# ---------------------------------------------------------------------------


def test_publish_search_index_summary_returns_dict():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    event = bridge.publish_search_index_summary(
        domain="general",
        index_hash="a" * 64,
        chunk_count=42,
        schema_version="1",
    )
    assert isinstance(event, dict)


def test_publish_search_index_summary_kind():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    event = bridge.publish_search_index_summary(
        domain="code",
        index_hash="b" * 64,
        chunk_count=100,
    )
    assert event.get("kind") == TFP_SEARCH_INDEX_KIND


def test_publish_search_index_summary_tags():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    event = bridge.publish_search_index_summary(
        domain="text",
        index_hash="c" * 64,
        chunk_count=7,
        schema_version="2",
    )
    tags = event.get("tags", [])
    tag_map = {t[0]: t[1] for t in tags if len(t) >= 2}
    assert tag_map.get("d") == "tfp-search-index"
    assert tag_map.get("domain") == "text"
    assert tag_map.get("index_hash") == "c" * 64
    assert tag_map.get("chunk_count") == "7"
    assert tag_map.get("schema_version") == "2"


def test_publish_search_index_summary_content_payload():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    event = bridge.publish_search_index_summary(
        domain="general",
        index_hash="d" * 64,
        chunk_count=50,
    )
    payload = json.loads(event["content"])
    assert payload["domain"] == "general"
    assert payload["index_hash"] == "d" * 64
    assert payload["chunk_count"] == 50


def test_publish_search_index_summary_custom_created_at():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    ts = int(time.time()) - 30
    event = bridge.publish_search_index_summary(
        domain="general",
        index_hash="e" * 64,
        chunk_count=1,
        created_at=ts,
    )
    assert event["created_at"] == ts


def test_publish_search_index_summary_added_to_history():
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    initial_count = len(bridge.get_history())
    bridge.publish_search_index_summary(
        domain="general",
        index_hash="f" * 64,
        chunk_count=5,
    )
    assert len(bridge.get_history()) == initial_count + 1


def test_search_index_kind_constant_value():
    assert TFP_SEARCH_INDEX_KIND == 30079


# ---------------------------------------------------------------------------
# Server-side _on_nostr_event kind-30079 dispatch
# ---------------------------------------------------------------------------


def test_kind_30079_increments_gossip_metric():
    """A valid kind-30079 event reaching _on_nostr_event increments the metric."""
    import tfp_demo.server as srv

    with TestClient(__import__("tfp_demo.server", fromlist=["app"]).app):
        before = srv._metrics.get("tfp_search_index_gossip_received_total")
        srv._on_nostr_event(
            _signed_event(
                30079,
                json.dumps(
                    {
                        "domain": "general",
                        "index_hash": "a" * 64,
                        "chunk_count": 10,
                        "schema_version": "1",
                    }
                ),
            )
        )
        after = srv._metrics.get("tfp_search_index_gossip_received_total")
    assert after == before + 1


def test_kind_30079_replay_guard_old_event():
    """An event with created_at far in the past is silently dropped."""
    import tfp_demo.server as srv

    with TestClient(__import__("tfp_demo.server", fromlist=["app"]).app):
        before = srv._metrics.get("tfp_search_index_gossip_received_total")
        old_ts = int(time.time()) - 600  # 10 minutes ago
        srv._on_nostr_event(
            _signed_event(
                30079,
                json.dumps(
                    {
                        "domain": "general",
                        "index_hash": "b" * 64,
                        "chunk_count": 5,
                        "schema_version": "1",
                    }
                ),
                created_at=old_ts,
            )
        )
        after = srv._metrics.get("tfp_search_index_gossip_received_total")
    assert after == before  # Dropped: metric not incremented


def test_kind_30079_replay_guard_future_event():
    """An event with created_at far in the future is also dropped."""
    import tfp_demo.server as srv

    with TestClient(__import__("tfp_demo.server", fromlist=["app"]).app):
        before = srv._metrics.get("tfp_search_index_gossip_received_total")
        future_ts = int(time.time()) + 600  # 10 minutes in the future
        srv._on_nostr_event(
            _signed_event(
                30079,
                json.dumps(
                    {
                        "domain": "general",
                        "index_hash": "c" * 64,
                        "chunk_count": 3,
                        "schema_version": "1",
                    }
                ),
                created_at=future_ts,
            )
        )
        after = srv._metrics.get("tfp_search_index_gossip_received_total")
    assert after == before  # Dropped


def test_kind_30079_malformed_content_ignored():
    """Malformed JSON content must not raise and must not increment metric."""
    import tfp_demo.server as srv

    with TestClient(__import__("tfp_demo.server", fromlist=["app"]).app):
        before = srv._metrics.get("tfp_search_index_gossip_received_total")
        srv._on_nostr_event(_signed_event(30079, "not valid json {{"))
        after = srv._metrics.get("tfp_search_index_gossip_received_total")
    # Malformed JSON → exception caught → no increment
    assert after == before


def test_kind_30079_missing_index_hash_ignored():
    """Event missing index_hash is silently ignored."""
    import tfp_demo.server as srv

    with TestClient(__import__("tfp_demo.server", fromlist=["app"]).app):
        before = srv._metrics.get("tfp_search_index_gossip_received_total")
        srv._on_nostr_event(
            _signed_event(
                30079,
                json.dumps({"domain": "general", "chunk_count": 5}),
            )
        )
        after = srv._metrics.get("tfp_search_index_gossip_received_total")
    # Empty index_hash → ignored
    assert after == before
