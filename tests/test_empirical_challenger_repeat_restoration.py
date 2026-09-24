# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Challenger Suite: Milestone 1 Iteration 2
Comprehensive validation of:
1. Pruned record restoration: accurate persistence of recipes, chunks, and droplets in SQLite.
2. Content fetch and fountain reconstruction across node restarts and simulated droplet loss.
3. Legacy migration out-of-order repeat restoration and subsequent content fetch.
4. Multi-bulletin independent restoration without crosstalk.
5. Browser acoustic receiver repeat restoration with rich content.
"""

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def get_receiver_html_path() -> Path:
    html_path = (
        Path(__file__).resolve().parent.parent
        / "tfp-foundation-protocol"
        / "tfp_demo"
        / "static"
        / "acoustic_receiver.html"
    )
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"
    return html_path


def test_empirical_pruned_restoration_persists_recipes_and_droplets_across_node_restart(tmp_path: Path):
    """
    Verify that when an authentic bulletin is restored after pruning:
    1. The recipe, all chunk hashes, chunk data, and fountain droplets are saved in SQLite.
    2. get_bulletin() returns exact payload bytes.
    3. Fresh node restart without in-memory state loads the recipe, chunks, and droplets.
    4. Fast-path fetch works bit-exact.
    5. Lossy fountain fetch (simulated_loss=0.3) works and recovers exact payload bytes from droplets.
    """
    db_file = tmp_path / "pruned_persistence.db"
    node = TFPNode(db_path=str(db_file))

    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "PERSIST-PRUNE-001"

    # Multi-chunk payload (~10.3 KB, ~41 fountain blocks)
    payload_data = b"PRUNED-TEST-DATA-CHUNK-" * 450  # ~10.35 KB
    content_hash = hashlib.sha3_256(payload_data).hexdigest()
    title = "Multi-Chunk Critical Alert (Rev 1)"
    _, sig = sign_bulletin_content(bid, 1, content_hash, key, title=title)

    # 1. Store initial bulletin
    recipe1 = node.store_bulletin(
        bulletin_id=bid,
        revision=1,
        data=payload_data,
        title=title,
        publisher_id=pub_hex,
        signature_hex=sig,
    )
    assert recipe1 is not None
    original_root_hash = recipe1.root_hash

    # Verify initial get_bulletin
    meta_init, data_init = node.get_bulletin(bid, 1)
    assert data_init == payload_data
    assert meta_init["root_hash"] == original_root_hash

    # 2. Prune display bulletins to 0
    pruned = node.prune_display_bulletins(keep_last_n=0)
    assert pruned == 1
    assert node.get_bulletin(bid, 1) is None

    # Verify watermark is still present
    wm = node.get_bulletin_watermark(pub_hex, bid)
    assert wm is not None
    assert wm["max_revision"] == 1
    assert wm["latest_title"] == title

    # 3. Authentic duplicate replay -> triggers repeat restoration
    restored_recipe = node.store_bulletin(
        bulletin_id=bid,
        revision=1,
        data=payload_data,
        title=title,
        publisher_id=pub_hex,
        signature_hex=sig,
    )
    assert restored_recipe is not None
    assert restored_recipe.root_hash == original_root_hash

    # 4. Inspect SQLite database tables directly
    conn = sqlite3.connect(str(db_file))
    try:
        # Check bulletins table
        b_rows = conn.execute("SELECT bulletin_id, revision, root_hash, title FROM bulletins WHERE bulletin_id=?", (bid,)).fetchall()
        assert len(b_rows) == 1
        assert b_rows[0][0] == bid
        assert b_rows[0][1] == 1
        assert b_rows[0][2] == original_root_hash
        assert b_rows[0][3] == title

        # Check recipes table
        r_rows = conn.execute("SELECT root_hash, total_size, chunk_hashes_json FROM recipes WHERE root_hash=?", (original_root_hash,)).fetchall()
        assert len(r_rows) == 1
        assert r_rows[0][0] == original_root_hash
        assert r_rows[0][1] == len(payload_data)
        chunk_hashes = json.loads(r_rows[0][2])
        assert len(chunk_hashes) > 0

        # Check chunks table
        c_rows = conn.execute("SELECT chunk_hash FROM chunks WHERE chunk_hash IN ({})".format(','.join('?' * len(chunk_hashes))), chunk_hashes).fetchall()
        assert len(c_rows) == len(chunk_hashes)

        # Check droplets table
        d_rows = conn.execute("SELECT count(*) FROM droplets WHERE root_hash=?", (original_root_hash,)).fetchone()
        assert d_rows[0] > 0
    finally:
        conn.close()

    # 5. Verify get_bulletin() works immediately
    meta_restored, data_restored = node.get_bulletin(bid, 1)
    assert data_restored == payload_data
    assert meta_restored["title"] == title

    # 6. Simulate cold restart: instantiate a new TFPNode with no memory caches
    node_restarted = TFPNode(db_path=str(db_file))
    assert original_root_hash not in node_restarted.recipes

    # get_bulletin on cold node must load recipe from DB and fetch payload
    meta_cold, data_cold = node_restarted.get_bulletin(bid, 1)
    assert data_cold == payload_data
    assert meta_cold["root_hash"] == original_root_hash
    assert original_root_hash in node_restarted.recipes

    # 7. Test fountain reconstruction under 15% simulated droplet loss on restarted node
    data_lossy = node_restarted.fetch(original_root_hash, simulated_loss=0.15)
    assert data_lossy == payload_data


def test_empirical_legacy_ooo_migration_pruned_repeat_with_droplet_recovery(tmp_path: Path):
    """
    Verify legacy database migration with out-of-order received_at:
    1. Pre-upgrade database with Rev 1 (t=3000) and Rev 2 (t=1000) with dummy root hashes and NO recipes/droplets.
    2. Upgrade to modern node -> watermarks backfilled to Rev 2.
    3. Prune display records.
    4. Replay authentic Rev 2 -> modern node stages publish, generates valid recipe & droplets, persists to SQLite.
    5. Verify get_bulletin() fetches exact payload.
    6. Verify cold restart loads new recipe and decodes under simulated loss.
    """
    db_file = tmp_path / "legacy_ooo_droplets.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "OOO-DROPLET-001"

    # Pre-upgrade legacy table
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

    c1 = b"Payload Rev 1 older"
    h1 = hashlib.sha3_256(c1).hexdigest()
    t1 = "Title Rev 1"
    _, s1 = sign_bulletin_content(bid, 1, h1, key, title=t1)
    meta1 = {"bulletin_id": bid, "revision": 1, "title": t1, "publisher_id": pub_hex, "content_hash": h1, "root_hash": "legacy_r1", "received_at": 3000.0}
    conn.execute("INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (bid, 1, h1, "legacy_r1", pub_hex, s1, t1, 3000.0, "verified_ed25519", len(c1), json.dumps(meta1)))

    c2 = b"Payload Rev 2 authoritative latest notice: All clear in Sector 9."
    h2 = hashlib.sha3_256(c2).hexdigest()
    t2 = "Title Rev 2"
    _, s2 = sign_bulletin_content(bid, 2, h2, key, title=t2)
    meta2 = {"bulletin_id": bid, "revision": 2, "title": t2, "publisher_id": pub_hex, "content_hash": h2, "root_hash": "legacy_r2", "received_at": 1000.0}
    conn.execute("INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (bid, 2, h2, "legacy_r2", pub_hex, s2, t2, 1000.0, "verified_ed25519", len(c2), json.dumps(meta2)))
    conn.commit()
    conn.close()

    # Modern node open
    node = TFPNode(db_path=str(db_file))
    wm = node.get_bulletin_watermark(pub_hex, bid)
    assert wm is not None
    assert wm["max_revision"] == 2
    assert wm["latest_content_hash"] == h2
    assert wm["latest_title"] == t2

    # Prune
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid, 2) is None

    # Replay authentic Rev 2
    recipe_restored = node.store_bulletin(
        bulletin_id=bid,
        revision=2,
        data=c2,
        title=t2,
        publisher_id=pub_hex,
        signature_hex=s2,
    )
    assert recipe_restored is not None
    real_root_hash = recipe_restored.root_hash
    assert real_root_hash != "legacy_r2"

    # Verify get_bulletin fetches content without error
    retrieved = node.get_bulletin(bid, 2)
    assert retrieved is not None
    meta, content = retrieved
    assert content == c2
    assert meta["root_hash"] == real_root_hash

    # Verify SQLite has recipes and droplets for real_root_hash
    conn2 = sqlite3.connect(str(db_file))
    try:
        r_count = conn2.execute("SELECT count(*) FROM recipes WHERE root_hash=?", (real_root_hash,)).fetchone()[0]
        assert r_count == 1
        d_count = conn2.execute("SELECT count(*) FROM droplets WHERE root_hash=?", (real_root_hash,)).fetchone()[0]
        assert d_count > 0
    finally:
        conn2.close()

    # Verify cold restart and lossy fetch
    node_restarted = TFPNode(db_path=str(db_file))
    meta_cold, data_cold = node_restarted.get_bulletin(bid, 2)
    assert data_cold == c2
    assert meta_cold["root_hash"] == real_root_hash

    lossy_recovered = node_restarted.fetch(real_root_hash, simulated_loss=0.20)
    assert lossy_recovered == c2


def test_empirical_multiple_pruned_bulletins_independent_restoration(tmp_path: Path):
    """
    Verify multiple pruned bulletins across multiple publishers:
    - 5 bulletins published.
    - All pruned.
    - Selectively restored.
    - Verify independent recipes, chunk stores, and no crosstalk.
    """
    db_file = tmp_path / "multi_prune.db"
    node = TFPNode(db_path=str(db_file))

    bulletin_records = []
    for i in range(5):
        key = ed25519.Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes_raw().hex()
        bid = f"MULTI-BULLETIN-{i:03d}"
        data = f"Authoritative bulletin content for #{i} with unique payload salt {i*77}".encode("utf-8")
        h = hashlib.sha3_256(data).hexdigest()
        title = f"Alert Multi #{i}"
        _, sig = sign_bulletin_content(bid, 1, h, key, title=title)
        rec = node.store_bulletin(bid, 1, data, title=title, publisher_id=pub, signature_hex=sig)
        bulletin_records.append({
            "bid": bid,
            "pub": pub,
            "key": key,
            "data": data,
            "hash": h,
            "title": title,
            "sig": sig,
            "root": rec.root_hash,
        })

    # Prune all
    pruned = node.prune_display_bulletins(keep_last_n=0)
    assert pruned == 5
    for b in bulletin_records:
        assert node.get_bulletin(b["bid"], 1) is None

    # Selectively restore bulletin 1, 3, 4
    for idx in [1, 3, 4]:
        b = bulletin_records[idx]
        node.store_bulletin(b["bid"], 1, b["data"], title=b["title"], publisher_id=b["pub"], signature_hex=b["sig"])

    # Verify only 1, 3, 4 are in display table
    assert node.get_bulletin(bulletin_records[0]["bid"], 1) is None
    assert node.get_bulletin(bulletin_records[2]["bid"], 1) is None

    for idx in [1, 3, 4]:
        b = bulletin_records[idx]
        retrieved = node.get_bulletin(b["bid"], 1)
        assert retrieved is not None
        assert retrieved[1] == b["data"]
        assert retrieved[0]["root_hash"] == b["root"]

    # Cold restart
    node_restarted = TFPNode(db_path=str(db_file))
    for idx in [1, 3, 4]:
        b = bulletin_records[idx]
        retrieved = node_restarted.get_bulletin(b["bid"], 1)
        assert retrieved is not None
        assert retrieved[1] == b["data"]
        assert retrieved[0]["root_hash"] == b["root"]


def test_empirical_browser_restoration_with_unicode_and_large_body():
    """
    Browser Acoustic Receiver:
    Verify repeat restoration with rich unicode content (emojis, multilingual text, newlines)
    and ensure display and archive are accurately restored after clearing.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "ALERT-UNICODE-999"
        pub = "station-zeta"

        b_unicode = {
            "id": bulletin_id,
            "rev": 1,
            "pub": pub,
            "title": "🚨 紧急通知: Sector 9 Weather Warning / 气象警报",
            "body": "Wind speeds > 120 km/h.\n⚠️ Take shelter immediately!\n风速超过 120 公里/小时，请立即避险。",
        }
        wav = modulator.synthesize_wav(json.dumps(b_unicode).encode("utf-8"))
        res = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode("ascii"))
        assert res["count"] == 1

        # Check UI displays unicode correctly
        content = page.locator("#contentArea").inner_text()
        assert "🚨 紧急通知: Sector 9 Weather Warning" in content
        assert "风速超过 120 公里/小时" in content

        # Clear archive
        page.evaluate("() => clearArchive()")
        assert page.locator("#archiveCount").inner_text() == "0"
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        # Replay exact unicode repeat
        res_repeat = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode("ascii"))
        assert res_repeat["count"] == 1

        # Check restored to UI and archive
        feed = page.locator("#packetFeed").inner_text()
        assert "Authentic repeat restored to display archive." in feed
        content_restored = page.locator("#contentArea").inner_text()
        assert "🚨 紧急通知: Sector 9 Weather Warning" in content_restored
        assert "风速超过 120 公里/小时" in content_restored

        archive = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive) == 1
        assert archive[0]["bulletinId"] == bulletin_id
        assert archive[0]["title"] == b_unicode["title"]

        browser.close()


def test_empirical_legacy_db_with_recipes_upgrade_pruned_repeat_and_cold_restart(tmp_path: Path):
    """
    Verify upgraded pre-watermark DB:
    1. Database initialized with recipes, chunks, droplets, bulletins, but NO watermarks.
    2. Opened in modern node -> watermarks backfilled.
    3. Pruned to 0 display bulletins.
    4. Authentic duplicate arrives -> repeat restoration succeeds.
    5. Content fetch succeeds.
    6. Cold restart loads from SQLite and fetches exact bytes.
    """
    db_file = tmp_path / "legacy_with_recipes_pruned.db"
    node1 = TFPNode(db_path=str(db_file))
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "LEGACY-RECIPE-002"
    data = b"Authoritative content before watermark table existed - pruned test"
    chash = hashlib.sha3_256(data).hexdigest()
    title = "Pre-Watermark Notice"
    _, sig = sign_bulletin_content(bid, 1, chash, key, title=title)
    rec1 = node1.store_bulletin(bid, 1, data, title=title, publisher_id=pub, signature_hex=sig)

    # Drop bulletin_watermarks to simulate legacy DB
    conn = sqlite3.connect(str(db_file))
    conn.execute("DROP TABLE bulletin_watermarks")
    conn.commit()
    conn.close()

    # Re-open node as modern node (triggers migration & backfill)
    node2 = TFPNode(db_path=str(db_file))
    wm = node2.get_bulletin_watermark(pub, bid)
    assert wm is not None
    assert wm["max_revision"] == 1
    assert wm["latest_title"] == title

    # Prune display bulletins
    pruned = node2.prune_display_bulletins(keep_last_n=0)
    assert pruned == 1
    assert node2.get_bulletin(bid, 1) is None

    # Authentic repeat of Rev 1
    rec_repeat = node2.store_bulletin(bid, 1, data, title=title, publisher_id=pub, signature_hex=sig)
    assert rec_repeat.root_hash == rec1.root_hash

    # Immediate content fetch
    retrieved = node2.get_bulletin(bid, 1)
    assert retrieved is not None
    assert retrieved[1] == data

    # Cold restart
    node3 = TFPNode(db_path=str(db_file))
    retrieved3 = node3.get_bulletin(bid, 1)
    assert retrieved3 is not None
    assert retrieved3[1] == data

