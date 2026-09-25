# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Multi-Step State Sequence Test Suite for Bulletin Persistence and Transport.

Validates interacting lifecycle states:
1. Legacy DB Upgrade: Opening a pre-upgrade database without bulletin_watermarks
   backfills watermark rows, advances on correction, survives pruning and restarts,
   and prevents stale downgrade re-admission while permitting authentic duplicates.
2. Same-Revision Title Conflict: Re-submitting an existing revision with a conflicting
   title is rejected as RevisionConflictError.
3. Pruned Record Title Conflict: Watermarks retain latest_title so that even after
   display records are pruned (keep_last_n=0), conflicting titles on the same revision
   are strictly rejected.
4. In-Memory Mode Consistency: Ephemeral nodes without SQLite enforce title conflict
   and watermark downgrade protections identically.
5. Browser Repeat Restoration: Clearing visual archive followed by receiving an exact
   repeat restores the visual display and offline archive while strictly preserving
   watermark downgrade rejections.
"""

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode
from tfp_client.lib.audio.afsk_modulator import AFSKModulator

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def test_legacy_db_upgrade_backfills_watermarks_and_prevents_pruned_stale_replay(tmp_path: Path):
    """
    State Sequence A:
    1. Create pre-upgrade SQLite database containing ONLY 'bulletins' table (no 'bulletin_watermarks').
    2. Populate with Revision 1.
    3. Initialize modern TFPNode -> verify bulletin_watermarks is populated with latest_title.
    4. Ingest Revision 2 (legitimate correction).
    5. Prune display bulletins to 0 (keep_last_n=0).
    6. Restart TFPNode (simulate process restart).
    7. Replay Revision 1 -> assert StaleRevisionError raised (downgrade prevented).
    8. Replay Revision 2 -> assert accepted as duplicate and re-admitted to display.
    """
    db_file = tmp_path / "legacy_migration_test.db"

    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "MIGRATE-BULLETIN-001"

    # Step 1 & 2: Construct legacy database schema with NO bulletin_watermarks table
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute(
            """
            CREATE TABLE bulletins (
                bulletin_id TEXT,
                revision INTEGER,
                content_hash TEXT,
                root_hash TEXT,
                publisher_id TEXT,
                signature_hex TEXT,
                title TEXT,
                received_at REAL,
                verified_status TEXT,
                data_size INTEGER,
                metadata_json TEXT,
                PRIMARY KEY (bulletin_id, revision)
            )
            """
        )
        c1 = b"Legacy Notice Revision 1 content."
        h1 = hashlib.sha3_256(c1).hexdigest()
        title_v1 = "Legacy Notice Original"
        _, sig_v1 = sign_bulletin_content(bid, 1, h1, key, title=title_v1)
        r1 = "placeholder_root_hash_v1"
        rec1_time = time.time() - 3600.0
        meta1 = {
            "bulletin_id": bid, "revision": 1, "title": title_v1, "publisher_id": pub_hex,
            "signature_hex": sig_v1, "verified_status": "verified_ed25519",
            "content_hash": h1, "root_hash": r1, "received_at": rec1_time,
        }
        conn.execute(
            """
            INSERT INTO bulletins
            (bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex,
             title, received_at, verified_status, data_size, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bid, 1, h1, r1, pub_hex, sig_v1, title_v1, rec1_time, "verified_ed25519", len(c1), json.dumps(meta1)),
        )
        conn.commit()

        # Confirm bulletin_watermarks table DOES NOT exist prior to upgrade
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bulletin_watermarks'")
        assert cur.fetchone() is None
    finally:
        conn.close()

    # Step 3: Open database with modern TFPNode
    node = TFPNode(db_path=db_file)

    # Verify bulletin_watermarks is created and backfilled with historical Revision 1
    wm1 = node.get_bulletin_watermark(pub_hex, bid)
    assert wm1 is not None, "bulletin_watermarks must be backfilled upon DB opening"
    assert wm1["max_revision"] == 1
    assert wm1["latest_content_hash"] == h1
    assert wm1["latest_title"] == title_v1

    # Step 4: Receive Revision 2 (legitimate correction)
    c2 = b"Legacy Notice Revision 2: Lift advisory."
    h2 = hashlib.sha3_256(c2).hexdigest()
    title_v2 = "Legacy Notice Corrected"
    _, sig_v2 = sign_bulletin_content(bid, 2, h2, key, title=title_v2)
    recipe_v2 = node.store_bulletin(bid, 2, c2, title=title_v2, publisher_id=pub_hex, signature_hex=sig_v2)
    assert recipe_v2 is not None

    wm2 = node.get_bulletin_watermark(pub_hex, bid)
    assert wm2["max_revision"] == 2
    assert wm2["latest_title"] == title_v2
    assert wm2["latest_content_hash"] == h2

    # Step 5: Prune display bulletins to 0
    pruned = node.prune_display_bulletins(keep_last_n=0)
    assert pruned >= 1
    assert len(node.list_bulletins()) == 0
    assert node.get_bulletin(bid) is None

    # Step 6: Restart TFPNode (new instance over the same persistent SQLite database)
    node_restarted = TFPNode(db_path=db_file)
    wm_restarted = node_restarted.get_bulletin_watermark(pub_hex, bid)
    assert wm_restarted is not None
    assert wm_restarted["max_revision"] == 2
    assert wm_restarted["latest_title"] == title_v2

    # Step 7: Replay Revision 1 -> assert StaleRevisionError raised
    with pytest.raises(StaleRevisionError, match="superseded by known watermark"):
        node_restarted.store_bulletin(bid, 1, c1, title=title_v1, publisher_id=pub_hex, signature_hex=sig_v1)

    # Step 8: Replay Revision 2 -> assert accepted as duplicate
    recipe_dup = node_restarted.store_bulletin(bid, 2, c2, title=title_v2, publisher_id=pub_hex, signature_hex=sig_v2)
    assert recipe_dup is not None
    assert recipe_dup.root_hash == recipe_v2.root_hash

    # Display bulletin record is re-admitted
    stored_dup = node_restarted.get_bulletin(bid)
    assert stored_dup is not None
    record_dup, data_dup = stored_dup
    assert record_dup["revision"] == 2
    assert record_dup["title"] == title_v2
    assert data_dup == c2


def test_same_revision_title_conflict_rejected(tmp_path: Path):
    """
    State Sequence B:
    1. Store Revision 1 with Title A.
    2. Attempt store Revision 1 with Title B (same content bytes) -> RevisionConflictError.
    3. Attempt store Revision 1 with Title B (different content bytes) -> RevisionConflictError.
    4. Authentic duplicate (Revision 1 with Title A and same content) -> Accepted idempotently.
    """
    db_file = tmp_path / "same_rev_title_conflict.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "TITLE-CONFLICT-001"

    c_orig = b"Flash flood warning for County Sector 5."
    h_orig = hashlib.sha3_256(c_orig).hexdigest()
    title_a = "Flash Flood Warning [Zone 5]"
    _, sig_a = sign_bulletin_content(bid, 1, h_orig, key, title=title_a)

    # 1. Store authentic initial bulletin
    recipe1 = node.store_bulletin(bid, 1, c_orig, title=title_a, publisher_id=pub, signature_hex=sig_a)
    assert recipe1 is not None

    # 2. Attempt same revision, same content, but altered Title B
    title_b = "Flash Flood Lifted [Zone 5]"
    _, sig_b = sign_bulletin_content(bid, 1, h_orig, key, title=title_b)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid, 1, c_orig, title=title_b, publisher_id=pub, signature_hex=sig_b)

    # 3. Attempt same revision, altered content, and altered Title B
    c_tampered = b"Altered malicious payload."
    h_tampered = hashlib.sha3_256(c_tampered).hexdigest()
    _, sig_tampered = sign_bulletin_content(bid, 1, h_tampered, key, title=title_b)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid, 1, c_tampered, title=title_b, publisher_id=pub, signature_hex=sig_tampered)

    # 4. Also verify unsigned same-revision title conflict
    node.store_bulletin("UNSIGN-TITLE-01", 1, b"Unsigned content", title="Unsigned Title A")
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin("UNSIGN-TITLE-01", 1, b"Unsigned content", title="Unsigned Title B")

    # 5. Authentic repeat with exact same title and content is accepted idempotently
    recipe_repeat = node.store_bulletin(bid, 1, c_orig, title=title_a, publisher_id=pub, signature_hex=sig_a)
    assert recipe_repeat is not None
    assert recipe_repeat.root_hash == recipe1.root_hash


def test_pruned_record_title_conflict_rejected_by_watermark(tmp_path: Path):
    """
    State Sequence C:
    1. Store Revision 1 with Title A.
    2. Prune display bulletins (bulletins table empty, bulletin_watermarks retains latest_title).
    3. Attempt store Revision 1 with Title B -> RevisionConflictError even with 0 display rows.
    4. Replay Revision 1 with Title A -> Restores display row and succeeds.
    """
    db_file = tmp_path / "pruned_title_conflict.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "PRUNED-CONFLICT-001"

    c_orig = b"High winds advisory. Secure outdoor equipment."
    h_orig = hashlib.sha3_256(c_orig).hexdigest()
    title_a = "High Winds Advisory"
    _, sig_a = sign_bulletin_content(bid, 1, h_orig, key, title=title_a)

    # 1. Store authentic Revision 1
    node.store_bulletin(bid, 1, c_orig, title=title_a, publisher_id=pub, signature_hex=sig_a)

    # 2. Prune display table to 0
    pruned = node.prune_display_bulletins(keep_last_n=0)
    assert pruned == 1
    assert node.get_bulletin(bid) is None

    # Verify watermark persisted title
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm is not None
    assert wm["latest_title"] == title_a

    # 3. Attempt same revision with altered Title B on pruned record
    title_b = "Sunny Weather Advisory"
    _, sig_b = sign_bulletin_content(bid, 1, h_orig, key, title=title_b)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid, 1, c_orig, title=title_b, publisher_id=pub, signature_hex=sig_b)

    # Also verify unsigned pruned title conflict
    node.store_bulletin("PRUNED-UNSIGN-01", 1, b"Unsigned pruned", title="Unsigned Pruned Title A")
    node.prune_display_bulletins(keep_last_n=0)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin("PRUNED-UNSIGN-01", 1, b"Unsigned pruned", title="Unsigned Pruned Title B")

    # 4. Authentic replay with Title A succeeds and restores display record
    recipe_restored = node.store_bulletin(bid, 1, c_orig, title=title_a, publisher_id=pub, signature_hex=sig_a)
    assert recipe_restored is not None

    stored = node.get_bulletin(bid)
    assert stored is not None
    assert stored[0]["title"] == title_a
    assert stored[1] == c_orig


def test_in_memory_mode_consistency():
    """
    State Sequence D:
    Verify title conflict, watermark monotonic advance, and downgrade rejection
    in in-memory mode (db_path=None).
    """
    node = TFPNode(db_path=None)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "INMEM-CONSISTENCY-001"

    c1 = b"In-memory advisory payload 1"
    h1 = hashlib.sha3_256(c1).hexdigest()
    title1 = "Advisory Initial"
    _, sig1 = sign_bulletin_content(bid, 1, h1, key, title=title1)

    # Store Revision 1
    node.store_bulletin(bid, 1, c1, title=title1, publisher_id=pub, signature_hex=sig1)

    # Same revision title conflict in memory (signed and unsigned)
    title1_tampered = "Advisory Tampered"
    _, sig1_tampered = sign_bulletin_content(bid, 1, h1, key, title=title1_tampered)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid, 1, c1, title=title1_tampered, publisher_id=pub, signature_hex=sig1_tampered)

    node.store_bulletin("INMEM-UNSIGN-01", 1, b"Unsigned inmem", title="InMem Unsign Title A")
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin("INMEM-UNSIGN-01", 1, b"Unsigned inmem", title="InMem Unsign Title B")

    # Advance to Revision 2
    c2 = b"In-memory advisory payload 2"
    h2 = hashlib.sha3_256(c2).hexdigest()
    title2 = "Advisory Lifted"
    _, sig2 = sign_bulletin_content(bid, 2, h2, key, title=title2)
    node.store_bulletin(bid, 2, c2, title=title2, publisher_id=pub, signature_hex=sig2)

    # Prune in-memory display records
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    # Stale replay in memory rejected
    with pytest.raises(StaleRevisionError, match="superseded by known watermark"):
        node.store_bulletin(bid, 1, c1, title=title1, publisher_id=pub, signature_hex=sig1)

    # Pruned title conflict in memory rejected
    title2_tampered = "Advisory Fake Title"
    _, sig2_tampered = sign_bulletin_content(bid, 2, h2, key, title=title2_tampered)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid, 2, c2, title=title2_tampered, publisher_id=pub, signature_hex=sig2_tampered)

    # Authentic repeat in memory restores display record
    rec_restored = node.store_bulletin(bid, 2, c2, title=title2, publisher_id=pub, signature_hex=sig2)
    assert rec_restored is not None
    stored_mem = node.get_bulletin(bid)
    assert stored_mem is not None
    assert stored_mem[0]["title"] == title2


def test_browser_repeat_restoration_lifecycle(tmp_path: Path):
    """
    State Sequence E:
    Verify browser receiver repeat restoration lifecycle using headless Chromium:
    1. Demodulate and ingest Revision 1.
    2. Clear visual archive (clearArchive()).
    3. Replay exact duplicate of Revision 1 -> Restored to display and archive.
    4. Ingest Revision 2 (advances watermark).
    5. Clear visual archive.
    6. Replay stale Revision 1 -> Rejected with Downgrade rejected, not restored.
    7. Replay authentic Revision 2 -> Restored to display and archive.
    """
    html_path = Path(__file__).resolve().parent.parent / "tfp-foundation-protocol" / "tfp_demo" / "static" / "acoustic_receiver.html"
    assert html_path.exists()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        # 1. Ingest initial revision 1
        b1 = {
            "id": "SEQ-ALERT-01",
            "rev": 1,
            "pub": "station-echo",
            "title": "Boil Water Notice (Rev 1)",
            "body": "Boil water for 1 minute before drinking or cooking.",
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1

        assert "Boil Water Notice (Rev 1)" in page.locator("#contentArea").inner_text()
        assert "Boil water for 1 minute" in page.locator("#contentArea").inner_text()

        # 2. Clear visual archive
        clear_btn = page.locator("button:has-text('Clear')")
        clear_btn.click()
        assert page.locator("#archiveCount").inner_text() == "0"
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        wm1 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm1["station-echo:SEQ-ALERT-01"]["revision"] == 1

        # 3. Transmit exact duplicate of Revision 1 -> Restored to display and archive
        res1_dup = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1_dup["count"] == 1

        feed = page.locator("#packetFeed").inner_text()
        assert "Authentic repeat restored to display archive." in feed
        assert "Boil Water Notice (Rev 1)" in page.locator("#contentArea").inner_text()
        assert "Boil water for 1 minute" in page.locator("#contentArea").inner_text()

        archive_restored = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive_restored) == 1
        assert archive_restored[0]["bulletinId"] == "SEQ-ALERT-01"

        # Watermark remains at revision 1
        wm_still_1 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_still_1["station-echo:SEQ-ALERT-01"]["revision"] == 1

        # 4. Advance to Revision 2
        b2 = {
            "id": "SEQ-ALERT-01",
            "rev": 2,
            "pub": "station-echo",
            "title": "Boil Water Notice Lifted (Rev 2)",
            "body": "Municipal water tested clean. Boil advisory cancelled.",
        }
        wav2 = modulator.synthesize_wav(json.dumps(b2).encode("utf-8"))
        res2 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2["count"] == 1

        wm2 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm2["station-echo:SEQ-ALERT-01"]["revision"] == 2

        # 5. Clear visual archive again
        clear_btn.click()
        assert page.locator("#archiveCount").inner_text() == "0"

        # 6. Replay stale Revision 1 -> Must be rejected with Downgrade rejected
        res1_stale = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1_stale["count"] == 1

        feed_stale = page.locator("#packetFeed").inner_text()
        assert "Downgrade rejected" in feed_stale
        assert "[REJECTED STALE]" in feed_stale

        # Display remains empty
        archive_empty = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive_empty) == 0

        # 7. Replay authentic Revision 2 -> Restored
        res2_dup = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2_dup["count"] == 1

        assert "Boil Water Notice Lifted (Rev 2)" in page.locator("#contentArea").inner_text()
        assert "Municipal water tested clean." in page.locator("#contentArea").inner_text()

        archive_final = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive_final) == 1
        assert archive_final[0]["revision"] == 2

        browser.close()


def test_partial_prune_restart_preserves_higher_watermark_metadata(tmp_path: Path):
    """
    Regression test for _init_db() watermark consistency and prune cache synchronization:
    1. Store Revision 1 and Revision 2 in SQLite.
    2. Verify prune_display_bulletins synchronizes in-memory _bulletins cache.
    3. Simulate a database state where bulletin_watermarks is at Revision 2, but only
       Revision 1 remains in the bulletins table (e.g. out-of-order receive timestamps or partial prune).
    4. Re-open TFPNode(db_path=db_file) -> verify _init_db() does NOT overwrite
       bulletin_watermarks.latest_content_hash or latest_title with Revision 1's older values.
    5. Verify replaying authentic Revision 2 succeeds with duplicate=True, while replaying
       Revision 2 with Revision 1's title/content raises RevisionConflictError.
    """
    db_file = tmp_path / "partial_prune_watermark_sync.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "PARTIAL-PRUNE-001"

    node = TFPNode(db_path=db_file)

    c1 = b"Initial evacuation boundary: Sector A."
    h1 = hashlib.sha3_256(c1).hexdigest()
    t1 = "Evacuation Advisory (Rev 1)"
    _, sig1 = sign_bulletin_content(bid, 1, h1, key, title=t1)
    r1 = node.store_bulletin(bid, 1, c1, title=t1, publisher_id=pub_hex, signature_hex=sig1)
    assert r1.metadata.get("duplicate") is not True

    c2 = b"Updated evacuation boundary: Sectors A and B."
    h2 = hashlib.sha3_256(c2).hexdigest()
    t2 = "Evacuation Advisory Expanded (Rev 2)"
    _, sig2 = sign_bulletin_content(bid, 2, h2, key, title=t2)
    r2 = node.store_bulletin(bid, 2, c2, title=t2, publisher_id=pub_hex, signature_hex=sig2)
    assert r2.metadata.get("duplicate") is not True

    # Verify prune_display_bulletins keeps in-memory _bulletins cache synchronized with SQLite
    assert len(node._bulletins) == 2
    node.prune_display_bulletins(keep_last_n=1)
    assert len(node._bulletins) == 1
    assert (bid, 2) in node._bulletins

    # Simulate partial-prune state where only Revision 1 exists in bulletins table while watermark is at Revision 2
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("DELETE FROM bulletins WHERE bulletin_id = ? AND revision = 2", (bid,))
        conn.execute(
            """INSERT OR REPLACE INTO bulletins
            (bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex,
             title, received_at, verified_status, data_size, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bid, 1, h1, r1.root_hash, pub_hex, sig1, t1, time.time(), "verified_ed25519", len(c1), "{}"),
        )
        conn.commit()
    finally:
        conn.close()

    # Restart node -> _init_db() runs
    restarted = TFPNode(db_path=db_file)
    wm = restarted.get_bulletin_watermark(pub_hex, bid)
    assert wm is not None
    assert wm["max_revision"] == 2
    assert wm["latest_content_hash"] == h2, "Watermark content hash must NOT regress to Rev 1"
    assert wm["latest_title"] == t2, "Watermark title must NOT regress to Rev 1"
    assert restarted.get_max_bulletin_revision(bid, publisher_id=pub_hex) == 2

    # Authentic Revision 2 replay must be accepted as duplicate=True
    r2_dup = restarted.store_bulletin(bid, 2, c2, title=t2, publisher_id=pub_hex, signature_hex=sig2)
    assert r2_dup.metadata.get("duplicate") is True

    # Conflicting Revision 2 with Revision 1's title must be rejected
    _, sig2_bad_title = sign_bulletin_content(bid, 2, h2, key, title=t1)
    with pytest.raises(RevisionConflictError):
        restarted.store_bulletin(bid, 2, c2, title=t1, publisher_id=pub_hex, signature_hex=sig2_bad_title)

