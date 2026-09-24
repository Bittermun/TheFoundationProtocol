# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for Permanent Bulletin Watermarks and Eviction-Resistant Revision Protection.

Verifies:
1. Watermark advances monotonically on newer revisions.
2. Superseded revisions are rejected with StaleRevisionError.
3. Pruning display bulletins does not erase watermark memory.
4. Replaying an old revision after display archive eviction is still rejected.
5. Exact duplicate of the current watermark is accepted idempotently.
6. Conflicting content on an existing revision is rejected.
7. Conflicting publisher key on an existing bulletin ID is rejected.
8. Watermark verification behaves consistently across SQLite and in-memory stores.
"""

from pathlib import Path
import sqlite3
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode


def test_watermark_advancement_and_stale_rejection(tmp_path: Path):
    db_file = tmp_path / "watermark_test.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "TEST-BULLETIN-001"

    # 1. Admit Revision 1
    content_v1 = b"Advisory Revision 1: Boil water."
    _, sig_v1 = sign_bulletin_content(bid, 1, TFPNode.sha3_hex(content_v1) if hasattr(TFPNode, "sha3_hex") else __import__("hashlib").sha3_256(content_v1).hexdigest(), key, title="Water Advisory")
    node.store_bulletin(bid, 1, content_v1, title="Water Advisory", publisher_id=pub_hex, signature_hex=sig_v1)

    wm = node.get_bulletin_watermark(pub_hex, bid)
    assert wm is not None
    assert wm["max_revision"] == 1

    # 2. Admit Revision 2
    content_v2 = b"Advisory Revision 2: Boil water lifted. Water is sanitized."
    c_hash_v2 = __import__("hashlib").sha3_256(content_v2).hexdigest()
    _, sig_v2 = sign_bulletin_content(bid, 2, c_hash_v2, key, title="Water Advisory")
    node.store_bulletin(bid, 2, content_v2, title="Water Advisory", publisher_id=pub_hex, signature_hex=sig_v2)

    wm2 = node.get_bulletin_watermark(pub_hex, bid)
    assert wm2["max_revision"] == 2
    assert wm2["latest_content_hash"] == c_hash_v2

    # 3. Attempt to replay Revision 1: must be rejected with StaleRevisionError
    with pytest.raises(StaleRevisionError, match="superseded by known watermark"):
        node.store_bulletin(bid, 1, content_v1, title="Water Advisory", publisher_id=pub_hex, signature_hex=sig_v1)


def test_pruning_display_bulletins_does_not_permit_stale_replay(tmp_path: Path):
    """
    CRITICAL INVARIANT:
    Pruning display records from the bulletins table must NEVER allow
    an older revision to be accepted, even if the database has 0 bulletin rows left.
    """
    db_file = tmp_path / "watermark_pruning.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "EVACUATION-ORDER-009"

    # Store rev 1 and rev 2
    c1 = b"Evacuate Sector 4 immediately."
    _, s1 = sign_bulletin_content(bid, 1, __import__("hashlib").sha3_256(c1).hexdigest(), key, title="Evacuation")
    node.store_bulletin(bid, 1, c1, title="Evacuation", publisher_id=pub_hex, signature_hex=s1)

    c2 = b"Sector 4 all-clear. Return to residences."
    _, s2 = sign_bulletin_content(bid, 2, __import__("hashlib").sha3_256(c2).hexdigest(), key, title="Evacuation")
    node.store_bulletin(bid, 2, c2, title="Evacuation", publisher_id=pub_hex, signature_hex=s2)

    # Verify both bulletins exist
    bulletins_before = node.list_bulletins()
    assert len(bulletins_before) == 2

    # Now prune display bulletins to 0 (simulate user clearing archive or aggressive LRU)
    pruned_count = node.prune_display_bulletins(keep_last_n=0)
    assert pruned_count == 2
    assert len(node.list_bulletins()) == 0

    # Ensure get_bulletin returns None for display
    assert node.get_bulletin(bid) is None

    # CRITICAL: Attempt to replay Revision 1.
    # Without watermark protection, this would succeed because bulletins table is empty.
    # With permanent watermark protection, it MUST FAIL with StaleRevisionError!
    with pytest.raises(StaleRevisionError, match="superseded by known watermark 2"):
        node.store_bulletin(bid, 1, c1, title="Evacuation", publisher_id=pub_hex, signature_hex=s1)

    # Admitting Revision 3 should still work smoothly and update the watermark
    c3 = b"Post-emergency recovery meeting at 14:00."
    _, s3 = sign_bulletin_content(bid, 3, __import__("hashlib").sha3_256(c3).hexdigest(), key, title="Evacuation")
    node.store_bulletin(bid, 3, c3, title="Evacuation", publisher_id=pub_hex, signature_hex=s3)

    wm3 = node.get_bulletin_watermark(pub_hex, bid)
    assert wm3["max_revision"] == 3


def test_idempotent_duplicate_of_latest_watermark(tmp_path: Path):
    db_file = tmp_path / "watermark_dup.db"
    node = TFPNode(db_path=db_file)

    bid = "NOTICE-DUP"
    content = b"General notice content."
    node.store_bulletin(bid, 1, content, title="Duplicate Notice")

    # Ingesting the exact same bulletin again must succeed idempotently
    recipe2 = node.store_bulletin(bid, 1, content, title="Duplicate Notice")
    assert recipe2 is not None

    bulletins = node.list_bulletins()
    assert len(bulletins) == 1


def test_conflicting_content_on_same_revision_rejected(tmp_path: Path):
    db_file = tmp_path / "watermark_conflict.db"
    node = TFPNode(db_path=db_file)

    bid = "CONFLICT-TEST"
    c_orig = b"Original content."
    node.store_bulletin(bid, 1, c_orig, title="Conflict")

    c_fake = b"Tampered content."
    with pytest.raises(RevisionConflictError, match="Bulletin revision conflict"):
        node.store_bulletin(bid, 1, c_fake, title="Conflict")


def test_publisher_identity_conflict_rejected_by_watermark(tmp_path: Path):
    db_file = tmp_path / "watermark_pub_conflict.db"
    node = TFPNode(db_path=db_file)

    key1 = ed25519.Ed25519PrivateKey.generate()
    pub1 = key1.public_key().public_bytes_raw().hex()

    key2 = ed25519.Ed25519PrivateKey.generate()
    pub2 = key2.public_key().public_bytes_raw().hex()

    bid = "EXCLUSIVE-STATION-BULLETIN"
    c1 = b"Station 1 announcement."
    _, s1 = sign_bulletin_content(bid, 1, __import__("hashlib").sha3_256(c1).hexdigest(), key1)
    node.store_bulletin(bid, 1, c1, publisher_id=pub1, signature_hex=s1)

    # Station 2 tries to publish the same bulletin ID (even higher revision)
    c2 = b"Station 2 announcement."
    _, s2 = sign_bulletin_content(bid, 2, __import__("hashlib").sha3_256(c2).hexdigest(), key2)
    with pytest.raises(PublisherIdentityConflictError, match="Bulletin publisher identity conflict"):
        node.store_bulletin(bid, 2, c2, publisher_id=pub2, signature_hex=s2)


def test_pruned_authentic_duplicate_replay_succeeds_sqlite(tmp_path: Path):
    """
    If display bulletins are pruned to bound storage size, receiving an authentic
    duplicate of the current watermark revision must NOT raise RevisionConflictError.
    Instead, it must re-admit the display record and return the recipe.
    """
    db_file = tmp_path / "watermark_pruned_dup.db"
    node = TFPNode(db_path=db_file)

    bid = "FLOOD-WARNING-01"
    content = b"Flood level rising at Sector 7."
    recipe1 = node.store_bulletin(bid, 1, content, title="Flood Warning")
    assert recipe1 is not None

    # Prune display bulletins to 0
    assert node.prune_display_bulletins(keep_last_n=0) == 1
    assert node.get_bulletin(bid, 1) is None
    assert len(node.list_bulletins()) == 0

    # Re-transmit authentic duplicate: must NOT raise RevisionConflictError
    recipe2 = node.store_bulletin(bid, 1, content, title="Flood Warning")
    assert recipe2 is not None
    assert recipe2.root_hash == recipe1.root_hash

    # Display bulletin record must be restored
    stored = node.get_bulletin(bid, 1)
    assert stored is not None
    meta, body = stored
    assert meta["bulletin_id"] == bid
    assert meta["revision"] == 1
    assert body == content
    assert len(node.list_bulletins()) == 1


def test_pruned_authentic_duplicate_replay_succeeds_in_memory():
    """
    In-memory nodes must also re-admit display records upon receiving an authentic
    duplicate replay of a pruned bulletin without raising RevisionConflictError.
    """
    node = TFPNode(db_path=None)

    bid = "INMEM-PRUNED-DUP"
    content = b"In-memory advisory content."
    recipe1 = node.store_bulletin(bid, 1, content, title="In-Memory Dup")
    assert recipe1 is not None

    # Prune display bulletins
    assert node.prune_display_bulletins(keep_last_n=0) == 1
    assert node.get_bulletin(bid, 1) is None
    assert len(node.list_bulletins()) == 0

    # Re-admit identical bulletin
    recipe2 = node.store_bulletin(bid, 1, content, title="In-Memory Dup")
    assert recipe2 is not None
    assert recipe2.root_hash == recipe1.root_hash

    stored = node.get_bulletin(bid, 1)
    assert stored is not None
    meta, body = stored
    assert meta["bulletin_id"] == bid
    assert body == content
    assert len(node.list_bulletins()) == 1


def test_in_memory_publisher_identity_conflict_after_pruning():
    """
    In-memory mode must check publisher pinning against permanent watermarks
    even after all display bulletins have been pruned to 0.
    """
    node = TFPNode(db_path=None)

    key1 = ed25519.Ed25519PrivateKey.generate()
    pub1 = key1.public_key().public_bytes_raw().hex()

    key2 = ed25519.Ed25519PrivateKey.generate()
    pub2 = key2.public_key().public_bytes_raw().hex()

    bid = "INMEM-PINNED-ID"
    c1 = b"Original publisher payload."
    _, s1 = sign_bulletin_content(bid, 1, __import__("hashlib").sha3_256(c1).hexdigest(), key1)
    node.store_bulletin(bid, 1, c1, publisher_id=pub1, signature_hex=s1)

    # Prune display records to 0
    assert node.prune_display_bulletins(keep_last_n=0) == 1
    assert len(node.list_bulletins()) == 0

    # Attacker tries to hijack the bulletin ID with a different key
    c2 = b"Adversarial hijack payload."
    _, s2 = sign_bulletin_content(bid, 1, __import__("hashlib").sha3_256(c2).hexdigest(), key2)
    with pytest.raises(PublisherIdentityConflictError, match="Bulletin publisher identity conflict"):
        node.store_bulletin(bid, 1, c2, publisher_id=pub2, signature_hex=s2)


def test_bulletin_watermarks_secondary_index(tmp_path: Path):
    """
    Verify that idx_bulletin_watermarks_bid exists on bulletin_watermarks(bulletin_id).
    """
    db_file = tmp_path / "watermark_index_test.db"
    node = TFPNode(db_path=db_file)

    conn = sqlite3.connect(str(db_file))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA index_list(bulletin_watermarks)")
        indexes = {row[1]: row for row in cur.fetchall()}
        assert "idx_bulletin_watermarks_bid" in indexes, f"Index missing. Found: {list(indexes.keys())}"

        cur.execute("PRAGMA index_info(idx_bulletin_watermarks_bid)")
        cols = [row[2] for row in cur.fetchall()]
        assert cols == ["bulletin_id"]
    finally:
        conn.close()

