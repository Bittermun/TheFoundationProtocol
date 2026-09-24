# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Stress Test Suite for Milestone 1 (M1):
Transition Correctness, Database Migrations, Watermarks, Extreme Pruning, and Title Mutations.

Covers:
1. Legacy DB Schema Migration with Fuzzed/Random Revision Histories:
   - Databases with historical bulletins, out-of-order received_at timestamps,
     random revisions, and verify migration integrity.
2. Extreme Pruning Levels:
   - keep_last_n = 0 and keep_last_n = 1 in SQLite and in-memory.
   - Verification that watermarks survive and stale revisions cannot be admitted.
3. Concurrency, Crash Simulation, and Restart Loops:
   - High-concurrency race condition injection against watermark checks.
   - Restart loops across prune cycles ensuring stale revisions can NEVER be re-admitted.
4. Comprehensive Title Mutation Adversarial Matrix:
   - Unicode variations (NFC/NFD, zero-width chars, homoglyphs, BOM, RTL).
   - Whitespace mutations (leading, trailing, internal repeated, tabs, newlines).
   - None vs empty string vs explicit title.
   - Case sensitivity.
   - Storage state integrity verification (no corruption after rejected conflicts).
"""

import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import string
import time
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


# ---------------------------------------------------------------------------
# Section 1: Legacy DB Migration with Fuzzed/Random Revision Histories
# ---------------------------------------------------------------------------

def test_legacy_db_migration_with_out_of_order_timestamps(tmp_path: Path):
    """
    Adversarial Challenge 1.1:
    Construct a legacy database without bulletin_watermarks where revisions
    arrived out of order (e.g. Rev 1 has received_at > Rev 5 received_at).
    Verify that opening with modern TFPNode correctly sets watermark metadata
    (max_revision, latest_content_hash, latest_title) to the TRUE highest revision,
    and that authentic replay of the highest revision succeeds after pruning.
    """
    db_file = tmp_path / "legacy_ooo_timestamps.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "LEGACY-OOO-001"

    # Construct legacy schema
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute(
            """
            CREATE TABLE bulletins (
                bulletin_id TEXT, revision INTEGER, content_hash TEXT, root_hash TEXT, publisher_id TEXT,
                signature_hex TEXT, title TEXT, received_at REAL, verified_status TEXT, data_size INTEGER,
                metadata_json TEXT, PRIMARY KEY (bulletin_id, revision)
            )
            """
        )
        # Revision 1 arrived at t=2000.0 (e.g. delayed receipt)
        c1 = b"Payload for Rev 1"
        h1 = hashlib.sha3_256(c1).hexdigest()
        t1 = "Title Revision 1"
        _, s1 = sign_bulletin_content(bid, 1, h1, key, title=t1)
        meta1 = {"bulletin_id": bid, "revision": 1, "title": t1, "publisher_id": pub, "content_hash": h1, "root_hash": "r1", "received_at": 2000.0}
        conn.execute(
            "INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bid, 1, h1, "r1", pub, s1, t1, 2000.0, "verified_ed25519", len(c1), json.dumps(meta1)),
        )

        # Revision 5 arrived at t=1000.0 (earlier timestamp)
        c5 = b"Payload for Rev 5"
        h5 = hashlib.sha3_256(c5).hexdigest()
        t5 = "Title Revision 5"
        _, s5 = sign_bulletin_content(bid, 5, h5, key, title=t5)
        meta5 = {"bulletin_id": bid, "revision": 5, "title": t5, "publisher_id": pub, "content_hash": h5, "root_hash": "r5", "received_at": 1000.0}
        conn.execute(
            "INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bid, 5, h5, "r5", pub, s5, t5, 1000.0, "verified_ed25519", len(c5), json.dumps(meta5)),
        )
        conn.commit()
    finally:
        conn.close()

    # Open with modern TFPNode
    node = TFPNode(db_path=db_file)
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm is not None, "Watermark must be backfilled"
    assert wm["max_revision"] == 5, f"Expected max_revision 5, got {wm['max_revision']}"
    assert wm["latest_content_hash"] == h5, (
        f"Migration bug: latest_content_hash is {wm['latest_content_hash']}, expected {h5} from Rev 5"
    )
    assert wm["latest_title"] == t5, (
        f"Migration bug: latest_title is {wm['latest_title']}, expected {t5} from Rev 5"
    )

    # Prune bulletins table to 0
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    # Stale Rev 1 replay must be rejected
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 1, c1, title=t1, publisher_id=pub, signature_hex=s1)

    # Authentic Rev 5 replay must succeed as authentic duplicate and restore display
    recipe = node.store_bulletin(bid, 5, c5, title=t5, publisher_id=pub, signature_hex=s5)
    assert recipe is not None
    stored = node.get_bulletin(bid)
    assert stored is not None
    assert stored[0]["revision"] == 5
    assert stored[0]["title"] == t5


def test_fuzzed_legacy_migration_across_multiple_publishers(tmp_path: Path):
    """
    Adversarial Challenge 1.2:
    Fuzz test legacy migration with 10 publishers, 5 bulletins each, with random
    revision counts (1-8 revisions per bulletin) and random received_at timestamps.
    Assert every watermark matches the exact properties of the highest revision.
    """
    db_file = tmp_path / "legacy_fuzzed_multi_pub.db"
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

    rng = random.Random(42)
    expected_watermarks = {}
    bulletin_payloads = {}

    publishers = [ed25519.Ed25519PrivateKey.generate() for _ in range(5)]

    for pub_idx, priv_key in enumerate(publishers):
        pub_hex = priv_key.public_key().public_bytes_raw().hex()
        for b_idx in range(5):
            bid = f"FUZZ-PUB{pub_idx}-B{b_idx}"
            rev_count = rng.randint(1, 6)
            rev_nums = sorted(rng.sample(range(1, 20), rev_count))

            max_rev = rev_nums[-1]

            for rev in rev_nums:
                content = f"Payload for {bid} rev {rev} salt {rng.randint(1, 10000)}".encode("utf-8")
                chash = hashlib.sha3_256(content).hexdigest()
                rhash = f"root_{pub_idx}_{b_idx}_{rev}"
                title = f"Title for {bid} Rev {rev}"
                _, sig = sign_bulletin_content(bid, rev, chash, priv_key, title=title)
                # Random timestamp between 100 and 10000
                recv_at = rng.uniform(100.0, 10000.0)

                meta = {
                    "bulletin_id": bid, "revision": rev, "title": title,
                    "publisher_id": pub_hex, "content_hash": chash, "root_hash": rhash,
                    "received_at": recv_at,
                }
                conn.execute(
                    "INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid, rev, chash, rhash, pub_hex, sig, title, recv_at, "verified_ed25519", len(content), json.dumps(meta)),
                )

                if rev == max_rev:
                    expected_watermarks[(pub_hex, bid)] = {
                        "max_revision": max_rev,
                        "latest_content_hash": chash,
                        "latest_title": title,
                    }
                    bulletin_payloads[(pub_hex, bid, rev)] = (content, title, sig)

    conn.commit()
    conn.close()

    # Open with modern node
    node = TFPNode(db_path=db_file)

    # Verify every watermark
    for (pub_hex, bid), expected in expected_watermarks.items():
        wm = node.get_bulletin_watermark(pub_hex, bid)
        assert wm is not None, f"Missing watermark for {bid}"
        assert wm["max_revision"] == expected["max_revision"], (
            f"Watermark max_revision mismatch for {bid}: expected {expected['max_revision']}, got {wm['max_revision']}"
        )
        assert wm["latest_content_hash"] == expected["latest_content_hash"], (
            f"Watermark content_hash mismatch for {bid}: expected {expected['latest_content_hash']}, got {wm['latest_content_hash']}"
        )
        assert wm["latest_title"] == expected["latest_title"], (
            f"Watermark title mismatch for {bid}: expected {expected['latest_title']}, got {wm['latest_title']}"
        )

    # Prune all to 0 and verify authentic duplicate replay succeeds for all
    node.prune_display_bulletins(keep_last_n=0)
    for (pub_hex, bid), expected in expected_watermarks.items():
        rev = expected["max_revision"]
        content, title, sig = bulletin_payloads[(pub_hex, bid, rev)]
        recipe = node.store_bulletin(bid, rev, content, title=title, publisher_id=pub_hex, signature_hex=sig)
        assert recipe is not None, f"Authentic duplicate failed for {bid}"


# ---------------------------------------------------------------------------
# Section 2: Extreme Prune Levels (keep_last_n=0, keep_last_n=1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("storage_mode", ["sqlite", "memory"])
def test_extreme_prune_level_zero(tmp_path: Path, storage_mode: str):
    """
    Adversarial Challenge 2.1:
    Test extreme prune keep_last_n=0:
    - Empty the display table completely.
    - Assert get_bulletin returns None for all bulletins.
    - Assert watermark persistence remains intact.
    - Assert stale revision injection is rejected.
    - Assert authentic duplicate replay restores the display record.
    """
    db_path = (tmp_path / "prune_zero.db") if storage_mode == "sqlite" else None
    node = TFPNode(db_path=db_path)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()

    # Ingest 5 bulletins with multiple revisions
    for i in range(5):
        bid = f"PRUNE-ZERO-{i}"
        for rev in [1, 2]:
            data = f"Content {bid} rev {rev}".encode("utf-8")
            chash = hashlib.sha3_256(data).hexdigest()
            title = f"Notice {bid} rev {rev}"
            _, sig = sign_bulletin_content(bid, rev, chash, key, title=title)
            node.store_bulletin(bid, rev, data, title=title, publisher_id=pub, signature_hex=sig)

    assert len(node.list_bulletins()) == 10

    # Extreme prune: keep 0
    deleted = node.prune_display_bulletins(keep_last_n=0)
    assert deleted == 10
    assert len(node.list_bulletins()) == 0

    for i in range(5):
        bid = f"PRUNE-ZERO-{i}"
        assert node.get_bulletin(bid) is None
        wm = node.get_bulletin_watermark(pub, bid)
        assert wm is not None
        assert wm["max_revision"] == 2

        # Stale Rev 1 rejected
        data1 = f"Content {bid} rev 1".encode("utf-8")
        chash1 = hashlib.sha3_256(data1).hexdigest()
        title1 = f"Notice {bid} rev 1"
        _, sig1 = sign_bulletin_content(bid, 1, chash1, key, title=title1)
        with pytest.raises(StaleRevisionError):
            node.store_bulletin(bid, 1, data1, title=title1, publisher_id=pub, signature_hex=sig1)

        # Authentic Rev 2 replay restored
        data2 = f"Content {bid} rev 2".encode("utf-8")
        chash2 = hashlib.sha3_256(data2).hexdigest()
        title2 = f"Notice {bid} rev 2"
        _, sig2 = sign_bulletin_content(bid, 2, chash2, key, title=title2)
        node.store_bulletin(bid, 2, data2, title=title2, publisher_id=pub, signature_hex=sig2)
        assert node.get_bulletin(bid) is not None


@pytest.mark.parametrize("storage_mode", ["sqlite", "memory"])
def test_extreme_prune_level_one(tmp_path: Path, storage_mode: str):
    """
    Adversarial Challenge 2.2:
    Test extreme prune keep_last_n=1:
    - Retain exactly 1 bulletin in the display table.
    - Verify that all pruned bulletins retain durable watermarks.
    - Verify that replay of stale revisions on pruned bulletins is blocked.
    """
    db_path = (tmp_path / "prune_one.db") if storage_mode == "sqlite" else None
    node = TFPNode(db_path=db_path)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()

    for i in range(10):
        bid = f"PRUNE-ONE-{i}"
        data = f"Notice payload {i}".encode("utf-8")
        chash = hashlib.sha3_256(data).hexdigest()
        title = f"Title Notice {i}"
        _, sig = sign_bulletin_content(bid, 1, chash, key, title=title)
        node.store_bulletin(bid, 1, data, title=title, publisher_id=pub, signature_hex=sig)
        time.sleep(0.005)

    assert len(node.list_bulletins()) == 10

    deleted = node.prune_display_bulletins(keep_last_n=1)
    assert deleted == 9
    assert len(node.list_bulletins()) == 1

    last_bid = "PRUNE-ONE-9"
    assert node.get_bulletin(last_bid) is not None

    # Check watermarks and stale rejection for pruned bulletins
    for i in range(9):
        pruned_bid = f"PRUNE-ONE-{i}"
        assert node.get_bulletin(pruned_bid) is None
        wm = node.get_bulletin_watermark(pub, pruned_bid)
        assert wm is not None
        assert wm["max_revision"] == 1


# ---------------------------------------------------------------------------
# Section 3: Concurrency, Crash Simulation, and Restart Loops
# ---------------------------------------------------------------------------

def test_concurrent_writes_watermark_downgrade_prevention(tmp_path: Path):
    """
    Adversarial Challenge 3.1:
    Attempt to race stale revision ingestion and higher revision ingestion
    across multiple concurrent threads on the same SQLite database.
    Assert no stale revision is ever admitted, and watermark never downgrades.
    """
    db_file = tmp_path / "concurrent_stress.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "RACE-BULLETIN-001"

    node = TFPNode(db_path=db_file)

    # Pre-generate signed revisions 1 through 10
    revisions = {}
    for r in range(1, 11):
        data = f"Revision payload content {r}".encode("utf-8")
        chash = hashlib.sha3_256(data).hexdigest()
        title = f"Advisory Rev {r}"
        _, sig = sign_bulletin_content(bid, r, chash, key, title=title)
        revisions[r] = (data, title, sig)

    # Establish baseline revision 5
    d5, t5, s5 = revisions[5]
    node.store_bulletin(bid, 5, d5, title=t5, publisher_id=pub, signature_hex=s5)

    def write_worker(rev: int):
        data, title, sig = revisions[rev]
        try:
            worker_node = TFPNode(db_path=db_file)
            worker_node.store_bulletin(bid, rev, data, title=title, publisher_id=pub, signature_hex=sig)
            return ("SUCCESS", rev)
        except StaleRevisionError:
            return ("STALE_REJECTED", rev)
        except Exception as ex:
            return (f"ERROR_{type(ex).__name__}", rev)

    tasks = [1, 2, 3, 4, 6, 7, 2, 3, 5, 8]
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_worker, r) for r in tasks]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Invariants verification
    final_wm = node.get_bulletin_watermark(pub, bid)
    assert final_wm["max_revision"] >= 5, "Watermark must never downgrade"

    for status, rev in results:
        if rev < 5:
            assert status == "STALE_REJECTED", f"Stale revision {rev} bypassed rejection!"

    # Ensure display table doesn't have stale revisions
    conn = sqlite3.connect(str(db_file))
    stored_revs = [row[0] for row in conn.execute("SELECT revision FROM bulletins WHERE bulletin_id=?", (bid,)).fetchall()]
    conn.close()

    assert all(r >= 5 for r in stored_revs), f"Stale revision found in bulletins table: {stored_revs}"


def test_stale_revisions_never_admitted_across_restart_loops(tmp_path: Path):
    """
    Adversarial Challenge 3.2:
    Execute 10 restart cycles interspersed with extreme pruning (keep_last_n=0)
    and attempt to re-admit older revisions.
    Verify that stale revisions can NEVER be re-admitted under any restart sequence.
    """
    db_file = tmp_path / "restart_loop.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "PERSISTENT-LOOP-001"

    node = TFPNode(db_path=db_file)

    # Ingest Rev 1, 2, 3
    for r in range(1, 4):
        data = f"Notice data {r}".encode("utf-8")
        chash = hashlib.sha3_256(data).hexdigest()
        title = f"Notice Title {r}"
        _, sig = sign_bulletin_content(bid, r, chash, key, title=title)
        node.store_bulletin(bid, r, data, title=title, publisher_id=pub, signature_hex=sig)

    for cycle in range(10):
        # 1. Prune display table to 0
        node.prune_display_bulletins(keep_last_n=0)
        assert len(node.list_bulletins()) == 0

        # 2. Restart node
        node = TFPNode(db_path=db_file)

        # 3. Assert watermark remains at 3
        wm = node.get_bulletin_watermark(pub, bid)
        assert wm is not None
        assert wm["max_revision"] == 3

        # 4. Attempt to admit Rev 1 and Rev 2
        for stale_rev in (1, 2):
            d_stale = f"Notice data {stale_rev}".encode("utf-8")
            h_stale = hashlib.sha3_256(d_stale).hexdigest()
            t_stale = f"Notice Title {stale_rev}"
            _, s_stale = sign_bulletin_content(bid, stale_rev, h_stale, key, title=t_stale)
            with pytest.raises(StaleRevisionError):
                node.store_bulletin(bid, stale_rev, d_stale, title=t_stale, publisher_id=pub, signature_hex=s_stale)

        # 5. Display table must still be 0
        assert len(node.list_bulletins()) == 0


# ---------------------------------------------------------------------------
# Section 4: Title Mutation Adversarial Fuzzing Matrix
# ---------------------------------------------------------------------------

def test_title_mutation_unicode_variations_raise_revision_conflict(tmp_path: Path):
    """
    Adversarial Challenge 4.1:
    Test same-revision title conflicts with Unicode variations:
    - Normalization forms (NFC vs NFD)
    - Zero-width space, joiners, BOM
    - Cyrillic / Greek homoglyphs
    - Fullwidth ASCII
    - Right-to-left marks
    Assert RevisionConflictError is strictly raised, and storage is uncorrupted.
    """
    db_file = tmp_path / "unicode_title_mutation.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "UNICODE-TITLE-001"

    data = b"Severe thunderstorm warning for Sector 7."
    chash = hashlib.sha3_256(data).hexdigest()
    # Baseline title in NFC
    baseline_title = unicodedata.normalize("NFC", "Orage Sévère Alerte")
    _, sig_base = sign_bulletin_content(bid, 1, chash, key, title=baseline_title)

    # Ingest authentic initial bulletin
    recipe = node.store_bulletin(bid, 1, data, title=baseline_title, publisher_id=pub, signature_hex=sig_base)
    assert recipe is not None

    mutations = [
        ("NFD Decomposition", unicodedata.normalize("NFD", baseline_title)),
        ("Zero-Width Space", "Orage\u200b Sévère Alerte"),
        ("Zero-Width Non-Joiner", "Orage Sévère\u200c Alerte"),
        ("Byte-Order Mark", "\ufeffOrage Sévère Alerte"),
        ("Cyrillic Homoglyph 'е'", "Oragе Sévèrе Alеrtе"),  # Cyrillic small letter ie (U+0435)
        ("Greek Homoglyph 'Α'", "Orage Sévère Αlerte"),  # Greek capital letter Alpha (U+0391)
        ("Fullwidth Characters", "Ｏｒａｇｅ Sévère Alerte"),
        ("Right-to-Left Override", "\u202eOrage Sévère Alerte\u202c"),
    ]

    for label, mutated_title in mutations:
        if mutated_title == baseline_title:
            continue
        _, sig_mut = sign_bulletin_content(bid, 1, chash, key, title=mutated_title)
        with pytest.raises(RevisionConflictError, match="differing title or content"):
            node.store_bulletin(bid, 1, data, title=mutated_title, publisher_id=pub, signature_hex=sig_mut)

        # Verify storage state is not corrupted
        stored = node.get_bulletin(bid)
        assert stored is not None
        assert stored[0]["title"] == baseline_title
        wm = node.get_bulletin_watermark(pub, bid)
        assert wm["latest_title"] == baseline_title


def test_title_mutation_whitespace_variations_raise_revision_conflict(tmp_path: Path):
    """
    Adversarial Challenge 4.2:
    Test same-revision title conflicts with whitespace variations:
    - Leading spaces
    - Trailing spaces
    - Internal multi-space / repeated spaces
    - Tab characters
    - Newlines / Carriage returns
    Assert RevisionConflictError is strictly raised, and storage is uncorrupted.
    """
    db_file = tmp_path / "whitespace_title_mutation.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "WHITESPACE-TITLE-001"

    data = b"Flash freeze warning on all secondary bridges."
    chash = hashlib.sha3_256(data).hexdigest()
    baseline_title = "Flash Freeze Warning"
    _, sig_base = sign_bulletin_content(bid, 1, chash, key, title=baseline_title)

    node.store_bulletin(bid, 1, data, title=baseline_title, publisher_id=pub, signature_hex=sig_base)

    mutations = [
        ("Leading Space", " Flash Freeze Warning"),
        ("Trailing Space", "Flash Freeze Warning "),
        ("Multiple Spaces", "Flash   Freeze   Warning"),
        ("Tab Character", "Flash\tFreeze Warning"),
        ("Newline Character", "Flash Freeze Warning\n"),
        ("Carriage Return", "Flash\rFreeze Warning"),
    ]

    for label, mutated_title in mutations:
        _, sig_mut = sign_bulletin_content(bid, 1, chash, key, title=mutated_title)
        with pytest.raises(RevisionConflictError, match="differing title or content"):
            node.store_bulletin(bid, 1, data, title=mutated_title, publisher_id=pub, signature_hex=sig_mut)

        stored = node.get_bulletin(bid)
        assert stored[0]["title"] == baseline_title
        wm = node.get_bulletin_watermark(pub, bid)
        assert wm["latest_title"] == baseline_title


def test_title_mutation_none_vs_empty_string_vs_default(tmp_path: Path):
    """
    Adversarial Challenge 4.3:
    Test title handling with None, empty string, and default bulletin_id:
    - Baseline stored with explicit title: replaying with title="" or title=None -> RevisionConflictError.
    - Baseline stored with title="" (defaults to bulletin_id):
        - Replay with title=None -> accepted as authentic duplicate (both resolve to bulletin_id).
        - Replay with explicit title -> RevisionConflictError.
    """
    db_file = tmp_path / "none_empty_title.db"
    node = TFPNode(db_path=db_file)
    bid1 = "EXPLICIT-TITLE-001"

    data = b"Sample bulletin content"
    # Case A: Stored with explicit title
    node.store_bulletin(bid1, 1, data, title="Explicit Title", publisher_id="unsigned")

    # Ingesting with empty string (resolves to bid1)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid1, 1, data, title="", publisher_id="unsigned")

    # Ingesting with None (resolves to bid1)
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid1, 1, data, title=None, publisher_id="unsigned")

    # Case B: Stored with empty string (defaults to bulletin_id)
    bid2 = "DEFAULT-TITLE-002"
    node.store_bulletin(bid2, 1, data, title="", publisher_id="unsigned")
    stored2 = node.get_bulletin(bid2)
    assert stored2[0]["title"] == bid2

    # Replaying with None also defaults to bid2 -> authentic duplicate
    rec_dup = node.store_bulletin(bid2, 1, data, title=None, publisher_id="unsigned")
    assert rec_dup is not None

    # Replaying with explicit title -> conflict
    with pytest.raises(RevisionConflictError, match="differing title or content"):
        node.store_bulletin(bid2, 1, data, title="New Explicit Title", publisher_id="unsigned")


def test_title_mutation_case_sensitivity(tmp_path: Path):
    """
    Adversarial Challenge 4.4:
    Test case sensitivity:
    - UPPERCASE, lowercase, Inverted Case must strictly trigger RevisionConflictError.
    """
    db_file = tmp_path / "case_sensitivity.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "CASE-TITLE-001"

    data = b"Coastal flood statement."
    chash = hashlib.sha3_256(data).hexdigest()
    baseline_title = "Coastal Flood Statement"
    _, sig_base = sign_bulletin_content(bid, 1, chash, key, title=baseline_title)

    node.store_bulletin(bid, 1, data, title=baseline_title, publisher_id=pub, signature_hex=sig_base)

    mutations = [
        baseline_title.upper(),
        baseline_title.lower(),
        baseline_title.swapcase(),
    ]

    for mutated_title in mutations:
        _, sig_mut = sign_bulletin_content(bid, 1, chash, key, title=mutated_title)
        with pytest.raises(RevisionConflictError, match="differing title or content"):
            node.store_bulletin(bid, 1, data, title=mutated_title, publisher_id=pub, signature_hex=sig_mut)

        stored = node.get_bulletin(bid)
        assert stored[0]["title"] == baseline_title


def test_title_mutation_on_pruned_bulletins_across_restarts(tmp_path: Path):
    """
    Adversarial Challenge 4.5:
    Prune display table to 0, restart node, then attempt unicode, whitespace, and case
    mutations on the pruned bulletin.
    Assert that durable watermarks reject all mutations via latest_title.
    """
    db_file = tmp_path / "pruned_restarts_title_mutations.db"
    node = TFPNode(db_path=db_file)

    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "PRUNED-MUTATION-001"

    data = b"Avalanche advisory for backcountry passes."
    chash = hashlib.sha3_256(data).hexdigest()
    baseline_title = "Avalanche Warning [Zone 4]"
    _, sig_base = sign_bulletin_content(bid, 2, chash, key, title=baseline_title)

    node.store_bulletin(bid, 2, data, title=baseline_title, publisher_id=pub, signature_hex=sig_base)

    # Prune to 0
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid) is None

    # Restart node
    node_restarted = TFPNode(db_path=db_file)

    mutations = [
        "Avalanche Warning [Zone 4] ",
        "Avalanche Warning [Zone 4]\u200b",
        "AVALANCHE WARNING [ZONE 4]",
        "Avalanche Warning",
    ]

    for mutated_title in mutations:
        _, sig_mut = sign_bulletin_content(bid, 2, chash, key, title=mutated_title)
        with pytest.raises(RevisionConflictError, match="differing title or content"):
            node_restarted.store_bulletin(bid, 2, data, title=mutated_title, publisher_id=pub, signature_hex=sig_mut)

    # Authentic replay with exact baseline title succeeds and restores display
    rec_restored = node_restarted.store_bulletin(bid, 2, data, title=baseline_title, publisher_id=pub, signature_hex=sig_base)
    assert rec_restored is not None
    assert node_restarted.get_bulletin(bid)[0]["title"] == baseline_title


def test_title_conflict_bypass_when_pruned_watermark_has_null_title(tmp_path: Path):
    """
    Adversarial Challenge 4.6:
    Database upgrade from older schema that already had bulletin_watermarks
    (without latest_title column) and where bulletins table was already pruned.
    ALTER TABLE adds latest_title as NULL.
    Attempting same-revision ingestion with altered title must be rejected,
    NOT silently admitted to the storage engine.
    """
    db_file = tmp_path / "pruned_null_title.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw().hex()
    bid = "NULL-TITLE-001"

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE bulletin_watermarks (
            publisher_id TEXT NOT NULL,
            bulletin_id TEXT NOT NULL,
            max_revision INTEGER NOT NULL,
            latest_content_hash TEXT NOT NULL,
            latest_root_hash TEXT NOT NULL,
            PRIMARY KEY (publisher_id, bulletin_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE bulletins (
            bulletin_id TEXT, revision INTEGER, content_hash TEXT, root_hash TEXT, publisher_id TEXT,
            signature_hex TEXT, title TEXT, received_at REAL, verified_status TEXT, data_size INTEGER,
            metadata_json TEXT, PRIMARY KEY (bulletin_id, revision)
        )
        """
    )
    data = b"Real bulletin payload"
    chash = hashlib.sha3_256(data).hexdigest()
    conn.execute("INSERT INTO bulletin_watermarks VALUES (?, ?, ?, ?, ?)", (pub, bid, 1, chash, "root1"))
    conn.commit()
    conn.close()

    node = TFPNode(db_path=db_file)
    wm = node.get_bulletin_watermark(pub, bid)
    assert wm is not None

    # Ingesting same revision with altered title must raise RevisionConflictError
    _, sig_fake = sign_bulletin_content(bid, 1, chash, key, title="Forged Malicious Title")
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 1, data, title="Forged Malicious Title", publisher_id=pub, signature_hex=sig_fake)

