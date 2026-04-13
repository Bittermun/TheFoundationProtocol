"""
tests/test_hlt_nostr.py

Phase E — HLT Nostr gossip event tests.

Verifies:
- NostrBridge.publish_hlt_state() emits a NIP-78 kind-30078 event with
  merkle_root and domain tags.
- _on_nostr_event() handles kind 30078 and updates the local HLT.
- GET /api/status includes hlt_domains count.
"""

import hashlib
import json
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree
from tfp_client.lib.bridges.nostr_bridge import NostrBridge, NostrEvent
from tfp_demo.server import app, _on_nostr_event

_TEST_PRIVKEY = b"\xaa" * 32


# ---------------------------------------------------------------------------
# NostrBridge.publish_hlt_state() tests
# ---------------------------------------------------------------------------


def test_publish_hlt_state_returns_event_dict():
    """publish_hlt_state() must return a dict with kind, tags, and content."""
    hlt = HierarchicalLexiconTree()
    hlt.add_domain("medical", "v1.0.0", "a" * 64, tags=["healthcare"])

    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    result = bridge.publish_hlt_state(hlt)

    assert isinstance(result, dict)
    assert result.get("kind") == 30078
    tags_dict = {t[0]: t[1] for t in result.get("tags", []) if len(t) >= 2}
    assert "d" in tags_dict
    assert "merkle_root" in tags_dict


def test_publish_hlt_state_includes_all_domains():
    """All domain names from the HLT must appear in event tags."""
    hlt = HierarchicalLexiconTree()
    hlt.add_domain("medical", "v1.0.0", "a" * 64)
    hlt.add_domain("legal", "v1.0.0", "b" * 64)
    hlt.add_domain("technical", "v1.0.0", "c" * 64)

    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)
    result = bridge.publish_hlt_state(hlt)

    domain_tags = [t[1] for t in result.get("tags", []) if t[0] == "domain"]
    for expected in ("medical", "legal", "technical"):
        assert expected in domain_tags, f"{expected!r} missing from domain tags"


def test_publish_hlt_state_merkle_root_changes_when_hlt_changes():
    """Distinct HLT states must produce distinct merkle_roots."""
    bridge = NostrBridge(relay_url="wss://relay.example.com", offline=True)

    hlt1 = HierarchicalLexiconTree()
    hlt1.add_domain("medical", "v1.0.0", "a" * 64)

    hlt2 = HierarchicalLexiconTree()
    hlt2.add_domain("medical", "v2.0.0", "b" * 64)

    r1 = bridge.publish_hlt_state(hlt1)
    r2 = bridge.publish_hlt_state(hlt2)

    mr1 = next((t[1] for t in r1["tags"] if t[0] == "merkle_root"), None)
    mr2 = next((t[1] for t in r2["tags"] if t[0] == "merkle_root"), None)
    assert mr1 != mr2


# ---------------------------------------------------------------------------
# _on_nostr_event kind-30078 ingestion tests
# ---------------------------------------------------------------------------


def test_on_nostr_event_kind_30078_updates_hlt():
    """A kind-30078 event must trigger HLT domain addition on the local tree."""
    from tfp_demo.server import _hlt, app as server_app

    # Ensure HLT is initialised by using TestClient context
    with TestClient(server_app) as _:
        from tfp_demo.server import _hlt as hlt_ref

        if hlt_ref is None:
            pytest.skip("HLT not initialised")

        domain_hash = hashlib.sha3_256(b"medical v1.0.0").hexdigest()
        event = NostrEvent.create(
            privkey=_TEST_PRIVKEY,
            kind=30078,
            content=json.dumps(
                {
                    "merkle_root": "abcd1234",
                    "domains": [
                        {
                            "domain": "medical",
                            "version": "v1.0.0",
                            "content_hash": domain_hash,
                        }
                    ],
                }
            ),
            tags=[
                ["d", "tfp-hlt"],
                ["domain", "medical"],
                ["version", "v1.0.0"],
                ["merkle_root", "abcd1234"],
            ],
        ).to_dict()
        _on_nostr_event(event)
        # After handling the event, HLT should have the medical domain
        assert hlt_ref.has_domain("medical")


def test_on_nostr_event_kind_30078_with_testclient():
    """Integration: HLT domain added via Nostr event survives within a lifecycle."""
    domain_hash = hashlib.sha3_256(b"legal v1.0.0").hexdigest()
    event = NostrEvent.create(
        privkey=_TEST_PRIVKEY,
        kind=30078,
        content=json.dumps(
            {
                "merkle_root": "feed1234",
                "domains": [
                    {
                        "domain": "legal",
                        "version": "v1.0.0",
                        "content_hash": domain_hash,
                    }
                ],
            }
        ),
        tags=[
            ["d", "tfp-hlt"],
            ["domain", "legal"],
            ["version", "v1.0.0"],
            ["merkle_root", "feed1234"],
        ],
    ).to_dict()
    with TestClient(app) as _:
        from tfp_demo.server import _hlt as hlt_ref

        if hlt_ref is not None:
            _on_nostr_event(event)
            assert hlt_ref.has_domain("legal")


# ---------------------------------------------------------------------------
# /api/status includes hlt_domains
# ---------------------------------------------------------------------------


def test_status_includes_hlt_domains():
    with TestClient(app) as client:
        r = client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert "hlt_domains" in body
        # Root node is always present; additional domains may exist
        assert isinstance(body["hlt_domains"], int)
        assert body["hlt_domains"] >= 0
