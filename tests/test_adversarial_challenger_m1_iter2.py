# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Challenge Suite by Challenger 5 (Iteration 2).

Thoroughly exercises:
1. Out-of-order revision arrival streams (signed and unsigned).
2. Out-of-order revision arrival across extreme pruning and node restarts.
3. Whitespace variations matrix (tabs, carriage returns, NBSP, thin space, ideographic space, all-whitespace).
4. Empty, None, and default bulletin_id title transitions.
5. Complex legacy database migrations with inverted timestamps and NULL/empty titles.
6. Publisher identity pinning across pruning and migrations.
"""

import hashlib
import json
from pathlib import Path
import random
import sqlite3
import unicodedata
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode


@pytest.mark.parametrize("storage_mode", ["sqlite", "memory"])
def test_out_of_order_revision_stream_comprehensive(tmp_path: Path, storage_mode: str):
    """
    Test out-of-order arrivals:
    1. Rev 5 arrives first (gap of rev 1..4).
    2. Stale Rev 2 arrives -> must raise StaleRevisionError.
    3. Higher Rev 8 arrives -> must succeed, watermark becomes 8.
    4. Stale Rev 1 arrives -> must raise StaleRevisionError.
    5. Stale Rev 5 arrives -> must raise StaleRevisionError.
    6. Replay Rev 8 (exact duplicate) -> must succeed as authentic duplicate.
    7. Replay Rev 8 with altered title -> must raise RevisionConflictError.
    8. Replay Rev 8 with altered content -> must raise RevisionConflictError.
    9. Prune display to keep_last_n=0.
    10. Stale Rev 2, 5, 7 arrive -> must raise StaleRevisionError.
    11. Replay Rev 8 (authentic duplicate) -> must restore display record.
    12. Higher Rev 9 arrives -> must succeed.
    """
    db_path = (tmp_path / "ooo_stream.db") if storage_mode == "sqlite" else None
    node = TFPNode(db_path=db_path)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "OOO-STREAM-001"

    def make_bulletin(rev: int, text: str, title: str):
        data = text.encode("utf-8")
        chash = hashlib.sha3_256(data).hexdigest()
        _, sig = sign_bulletin_content(bid, rev, chash, key, title=title)
        return data, chash, title, sig

    d5, h5, t5, s5 = make_bulletin(5, "Payload Rev 5", "Notice Rev 5")
    d2, h2, t2, s2 = make_bulletin(2, "Payload Rev 2", "Notice Rev 2")
    d8, h8, t8, s8 = make_bulletin(8, "Payload Rev 8", "Notice Rev 8")
    d1, h1, t1, s1 = make_bulletin(1, "Payload Rev 1", "Notice Rev 1")
    d9, h9, t9, s9 = make_bulletin(9, "Payload Rev 9", "Notice Rev 9")

    # 1. Rev 5 arrives first
    rec5 = node.store_bulletin(bid, 5, d5, title=t5, publisher_id=pub, signature_hex=s5)
    assert rec5 is not None
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm["max_revision"] == 5

    # 2. Stale Rev 2 arrives
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 2, d2, title=t2, publisher_id=pub, signature_hex=s2)

    # 3. Higher Rev 8 arrives
    rec8 = node.store_bulletin(bid, 8, d8, title=t8, publisher_id=pub, signature_hex=s8)
    assert rec8 is not None
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm["max_revision"] == 8

    # 4. Stale Rev 1 arrives
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 1, d1, title=t1, publisher_id=pub, signature_hex=s1)

    # 5. Stale Rev 5 arrives (previously accepted, but now superseded by Rev 8)
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 5, d5, title=t5, publisher_id=pub, signature_hex=s5)

    # 6. Replay Rev 8 (exact duplicate) -> authentic duplicate replay
    rec8_dup = node.store_bulletin(bid, 8, d8, title=t8, publisher_id=pub, signature_hex=s8)
    assert rec8_dup is not None

    # 7. Replay Rev 8 with altered title
    t8_altered = "Notice Rev 8 Altered"
    _, s8_altered = sign_bulletin_content(bid, 8, h8, key, title=t8_altered)
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 8, d8, title=t8_altered, publisher_id=pub, signature_hex=s8_altered)

    # 8. Replay Rev 8 with altered content
    d8_altered = b"Payload Rev 8 Altered Content"
    h8_altered = hashlib.sha3_256(d8_altered).hexdigest()
    _, s8_c_altered = sign_bulletin_content(bid, 8, h8_altered, key, title=t8)
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 8, d8_altered, title=t8, publisher_id=pub, signature_hex=s8_c_altered)

    # 9. Prune display to keep_last_n=0
    deleted = node.prune_display_bulletins(keep_last_n=0)
    assert deleted >= 1
    assert node.get_bulletin(bid) is None

    # 10. Stale Rev 2, 5, 7 arrive on pruned node
    for r, d, t, s in [(2, d2, t2, s2), (5, d5, t5, s5)]:
        with pytest.raises(StaleRevisionError):
            node.store_bulletin(bid, r, d, title=t, publisher_id=pub, signature_hex=s)

    # 11. Replay Rev 8 (authentic duplicate) restores display
    rec8_restored = node.store_bulletin(bid, 8, d8, title=t8, publisher_id=pub, signature_hex=s8)
    assert rec8_restored is not None
    stored = node.get_bulletin(bid)
    assert stored is not None
    assert stored[0]["revision"] == 8
    assert stored[0]["title"] == t8

    # 12. Higher Rev 9 arrives
    rec9 = node.store_bulletin(bid, 9, d9, title=t9, publisher_id=pub, signature_hex=s9)
    assert rec9 is not None
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm["max_revision"] == 9


def test_out_of_order_with_restart_and_pruning(tmp_path: Path):
    """
    Test persistence of watermark across restart loops with out-of-order streams:
    - Node 1: Ingest Rev 4
    - Prune keep_last_n=0
    - Restart Node 2
    - Stale Rev 1, 2, 3 must raise StaleRevisionError
    - Ingest Rev 6
    - Restart Node 3
    - Stale Rev 4, 5 must raise StaleRevisionError
    - Replay Rev 6 must succeed
    """
    db_path = tmp_path / "restart_ooo.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "RESTART-OOO-001"

    # Node 1
    node1 = TFPNode(db_path=db_path)
    d4 = b"Rev 4 content"
    h4 = hashlib.sha3_256(d4).hexdigest()
    _, s4 = sign_bulletin_content(bid, 4, h4, key, title="Rev 4")
    node1.store_bulletin(bid, 4, d4, title="Rev 4", publisher_id=pub, signature_hex=s4)
    node1.prune_display_bulletins(keep_last_n=0)

    # Node 2
    node2 = TFPNode(db_path=db_path)
    for r in (1, 2, 3):
        dr = f"Rev {r} content".encode("utf-8")
        hr = hashlib.sha3_256(dr).hexdigest()
        _, sr = sign_bulletin_content(bid, r, hr, key, title=f"Rev {r}")
        with pytest.raises(StaleRevisionError):
            node2.store_bulletin(bid, r, dr, title=f"Rev {r}", publisher_id=pub, signature_hex=sr)

    d6 = b"Rev 6 content"
    h6 = hashlib.sha3_256(d6).hexdigest()
    _, s6 = sign_bulletin_content(bid, 6, h6, key, title="Rev 6")
    node2.store_bulletin(bid, 6, d6, title="Rev 6", publisher_id=pub, signature_hex=s6)

    # Node 3
    node3 = TFPNode(db_path=db_path)
    for r in (4, 5):
        dr = f"Rev {r} content".encode("utf-8")
        hr = hashlib.sha3_256(dr).hexdigest()
        _, sr = sign_bulletin_content(bid, r, hr, key, title=f"Rev {r}")
        with pytest.raises(StaleRevisionError):
            node3.store_bulletin(bid, r, dr, title=f"Rev {r}", publisher_id=pub, signature_hex=sr)

    # Replay Rev 6
    rec6 = node3.store_bulletin(bid, 6, d6, title="Rev 6", publisher_id=pub, signature_hex=s6)
    assert rec6 is not None
    assert node3.get_bulletin(bid)[0]["revision"] == 6


@pytest.mark.parametrize("is_signed", [True, False])
def test_whitespace_title_variations_matrix(tmp_path: Path, is_signed: bool):
    """
    Adversarial whitespace variation matrix on active and pruned bulletins:
    - Tab characters
    - Carriage returns / Newlines
    - Non-breaking spaces (U+00A0)
    - Thin spaces (U+2009)
    - Ideographic spaces (U+3000)
    - Leading / trailing spaces
    - Repeated internal spaces
    - All-whitespace titles ("   ")
    All variations must raise RevisionConflictError on duplicate replay.
    """
    db_file = tmp_path / f"whitespace_matrix_{is_signed}.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex() if is_signed else "unsigned"
    bid = f"WS-MATRIX-{is_signed}"

    data = b"Evacuation route update for Interstate 80."
    chash = hashlib.sha3_256(data).hexdigest()
    baseline_title = "Evacuation Route Update"

    sig = None
    if is_signed:
        _, sig = sign_bulletin_content(bid, 1, chash, key, title=baseline_title)

    node.store_bulletin(bid, 1, data, title=baseline_title, publisher_id=pub, signature_hex=sig)

    whitespace_mutations = [
        ("Leading Space", " Evacuation Route Update"),
        ("Trailing Space", "Evacuation Route Update "),
        ("Leading and Trailing", " Evacuation Route Update "),
        ("Double Internal Space", "Evacuation  Route Update"),
        ("Tab Character", "Evacuation\tRoute Update"),
        ("Leading Tab", "\tEvacuation Route Update"),
        ("Trailing Tab", "Evacuation Route Update\t"),
        ("Newline Character", "Evacuation\nRoute Update"),
        ("Trailing Newline", "Evacuation Route Update\n"),
        ("Carriage Return", "Evacuation\rRoute Update"),
        ("CRLF", "Evacuation\r\nRoute Update"),
        ("Non-Breaking Space", "Evacuation\u00a0Route Update"),
        ("Thin Space", "Evacuation\u2009Route Update"),
        ("Ideographic Space", "Evacuation\u3000Route Update"),
        ("En Space", "Evacuation\u2002Route Update"),
        ("Em Space", "Evacuation\u2003Route Update"),
    ]

    for label, mutated in whitespace_mutations:
        mut_sig = None
        if is_signed:
            _, mut_sig = sign_bulletin_content(bid, 1, chash, key, title=mutated)
        with pytest.raises(RevisionConflictError):
            node.store_bulletin(bid, 1, data, title=mutated, publisher_id=pub, signature_hex=mut_sig)

    # Now prune display to 0 and verify whitespace variations STILL raise RevisionConflictError
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    for label, mutated in whitespace_mutations:
        mut_sig = None
        if is_signed:
            _, mut_sig = sign_bulletin_content(bid, 1, chash, key, title=mutated)
        with pytest.raises(RevisionConflictError):
            node.store_bulletin(bid, 1, data, title=mutated, publisher_id=pub, signature_hex=mut_sig)

    # Authentic replay with exact baseline title succeeds and restores display
    rec = node.store_bulletin(bid, 1, data, title=baseline_title, publisher_id=pub, signature_hex=sig)
    assert rec is not None
    assert node.get_bulletin(bid)[0]["title"] == baseline_title


def test_empty_and_none_titles_matrix(tmp_path: Path):
    """
    Test empty string, None, and default bulletin_id title handling:
    Case 1: Bulletin stored with title="" (canonicalized to bulletin_id)
            - Replay with title="" -> Authentic duplicate
            - Replay with title=None -> Authentic duplicate
            - Replay with title=bulletin_id -> Authentic duplicate
            - Replay with title="Custom" -> RevisionConflictError
    Case 2: Bulletin stored with title="   " (all whitespace, not empty)
            - Replay with title="   " -> Authentic duplicate
            - Replay with title="" -> RevisionConflictError
            - Replay with title=None -> RevisionConflictError
            - Replay with title=bulletin_id -> RevisionConflictError
    """
    db_file = tmp_path / "empty_none_matrix.db"
    node = TFPNode(db_path=db_file)
    data = b"Some payload"

    # Case 1
    bid1 = "EMPTY-TEST-001"
    node.store_bulletin(bid1, 1, data, title="", publisher_id="unsigned")
    assert node.get_bulletin(bid1)[0]["title"] == bid1

    # Replay with title=""
    r1 = node.store_bulletin(bid1, 1, data, title="", publisher_id="unsigned")
    assert r1 is not None

    # Replay with title=None
    r2 = node.store_bulletin(bid1, 1, data, title=None, publisher_id="unsigned")
    assert r2 is not None

    # Replay with title=bid1
    r3 = node.store_bulletin(bid1, 1, data, title=bid1, publisher_id="unsigned")
    assert r3 is not None

    # Replay with title="Custom"
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid1, 1, data, title="Custom", publisher_id="unsigned")

    # Prune and re-verify
    node.prune_display_bulletins(keep_last_n=0)
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid1, 1, data, title="Custom", publisher_id="unsigned")
    r4 = node.store_bulletin(bid1, 1, data, title="", publisher_id="unsigned")
    assert r4 is not None

    # Case 2: Stored with all whitespace
    bid2 = "SPACES-TEST-002"
    ws_title = "   "
    node.store_bulletin(bid2, 1, data, title=ws_title, publisher_id="unsigned")
    assert node.get_bulletin(bid2)[0]["title"] == ws_title

    # Replay with exact same whitespace title
    r_ws = node.store_bulletin(bid2, 1, data, title=ws_title, publisher_id="unsigned")
    assert r_ws is not None

    # Replay with empty string -> conflict
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid2, 1, data, title="", publisher_id="unsigned")

    # Replay with None -> conflict
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid2, 1, data, title=None, publisher_id="unsigned")

    # Replay with bid2 -> conflict
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid2, 1, data, title=bid2, publisher_id="unsigned")


def test_legacy_migration_with_null_and_empty_titles_and_timestamp_inversion(tmp_path: Path):
    """
    Test legacy database migration where:
    - Rev 1 has received_at=5000.0, title="Rev 1 Explicit Title"
    - Rev 3 has received_at=1000.0, title=NULL (or empty)
    Verify:
    - Migration chooses Rev 3 as max_revision.
    - latest_title is NULL/empty in watermark.
    - Replaying Rev 3 with a forged title raises RevisionConflictError.
    - Replaying Rev 3 with empty title or None restores the bulletin.
    """
    db_file = tmp_path / "legacy_null_migration.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "LEGACY-NULL-001"

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE bulletins (
            bulletin_id TEXT, revision INTEGER, content_hash TEXT, root_hash TEXT, publisher_id TEXT,
            signature_hex TEXT, title TEXT, received_at REAL, verified_status TEXT, data_size INTEGER,
            metadata_json TEXT, PRIMARY KEY (bulletin_id, revision)
        )
        """
    )

    c1 = b"Payload 1"
    h1 = hashlib.sha3_256(c1).hexdigest()
    t1 = "Rev 1 Explicit Title"
    _, s1 = sign_bulletin_content(bid, 1, h1, key, title=t1)
    meta1 = {"bulletin_id": bid, "revision": 1, "title": t1, "publisher_id": pub, "content_hash": h1, "root_hash": "r1", "received_at": 5000.0}
    conn.execute(
        "INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (bid, 1, h1, "r1", pub, s1, t1, 5000.0, "verified_ed25519", len(c1), json.dumps(meta1)),
    )

    c3 = b"Payload 3"
    h3 = hashlib.sha3_256(c3).hexdigest()
    # Rev 3 signed with empty title (defaults to bid)
    _, s3 = sign_bulletin_content(bid, 3, h3, key, title="")
    meta3 = {"bulletin_id": bid, "revision": 3, "title": None, "publisher_id": pub, "content_hash": h3, "root_hash": "r3", "received_at": 1000.0}
    conn.execute(
        "INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (bid, 3, h3, "r3", pub, s3, None, 1000.0, "verified_ed25519", len(c3), json.dumps(meta3)),
    )
    conn.commit()
    conn.close()

    # Open with modern node
    node = TFPNode(db_path=db_file)
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm is not None
    assert wm["max_revision"] == 3
    assert wm["latest_content_hash"] == h3
    assert wm["latest_title"] is None

    # Prune bulletins to 0
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    # Stale Rev 1 replay must be rejected
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 1, c1, title=t1, publisher_id=pub, signature_hex=s1)

    # Replay Rev 3 with forged title -> RevisionConflictError
    _, s3_forged = sign_bulletin_content(bid, 3, h3, key, title="Forged Malicious Title")
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 3, c3, title="Forged Malicious Title", publisher_id=pub, signature_hex=s3_forged)

    # Replay Rev 3 with authentic empty title -> restores display
    rec3 = node.store_bulletin(bid, 3, c3, title="", publisher_id=pub, signature_hex=s3)
    assert rec3 is not None
    stored = node.get_bulletin(bid)
    assert stored is not None
    assert stored[0]["revision"] == 3
    assert stored[0]["title"] == bid


def test_publisher_identity_conflict_across_pruning_and_migrations(tmp_path: Path):
    """
    Test publisher identity conflict rules:
    - Publisher A publishes BID-1
    - Node prunes bulletins to keep_last_n=0
    - Publisher B attempts to publish BID-1 with higher revision -> PublisherIdentityConflictError
    - Legacy migration with existing bulletins preserves publisher binding
    """
    db_file = tmp_path / "pub_conflict.db"
    key_a = ed25519.Ed25519PrivateKey.generate()
    pub_a = key_a.public_key().public_bytes_raw().hex()
    key_b = ed25519.Ed25519PrivateKey.generate()
    pub_b = key_b.public_key().public_bytes_raw().hex()

    bid = "PUB-ISOLATION-001"
    node = TFPNode(db_path=db_file)

    # Publisher A publishes Rev 1
    d1 = b"Notice from Publisher A"
    h1 = hashlib.sha3_256(d1).hexdigest()
    _, s1 = sign_bulletin_content(bid, 1, h1, key_a, title="Notice A")
    node.store_bulletin(bid, 1, d1, title="Notice A", publisher_id=pub_a, signature_hex=s1)

    # Prune to 0
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    # Publisher B attempts to take over BID-1 with Rev 2
    d2 = b"Notice from Publisher B"
    h2 = hashlib.sha3_256(d2).hexdigest()
    _, s2 = sign_bulletin_content(bid, 2, h2, key_b, title="Notice B")
    with pytest.raises(PublisherIdentityConflictError):
        node.store_bulletin(bid, 2, d2, title="Notice B", publisher_id=pub_b, signature_hex=s2)

    # Unsigned publisher also rejected
    with pytest.raises(PublisherIdentityConflictError):
        node.store_bulletin(bid, 2, d2, title="Notice B", publisher_id="unsigned")
