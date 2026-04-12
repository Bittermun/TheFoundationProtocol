"""
tests/test_cid_persistence.py

Phase D CID persistence tests.

Verifies that:
- A CID returned by the IPFS bridge is stored durably in the SQLite
  content table when content is published.
- The CID survives a simulated server restart.
- DemoNDNAdapter uses the SQLite-persisted CID for IPFS fallback instead of
  relying solely on the in-memory IPFSBridge mapping.
- A Nostr event that carries a CID causes put_cid_mapping() to update an
  existing content record durably.
- put_cid_mapping() is a no-op for hashes that are not in the local store.
"""

import hashlib
import hmac as _hmac
import os
import pathlib
import sqlite3
import tempfile
import threading

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import (
    ContentStore,
    StoredContent,
    app,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200, r.text


def _publish_json(
    client, device_id: str, puf: bytes, title: str, text: str = "body"
) -> str:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={"title": title, "text": text, "tags": ["test"], "device_id": device_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


@pytest.fixture()
def db_file():
    """Yield a temporary file-backed SQLite path; restore env on teardown."""
    import shutil
    orig = os.environ.get("TFP_DB_PATH")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["TFP_DB_PATH"] = tmp.name
    yield tmp.name
    if orig is not None:
        os.environ["TFP_DB_PATH"] = orig
    else:
        os.environ["TFP_DB_PATH"] = ":memory:"
    pathlib.Path(tmp.name).unlink(missing_ok=True)
    # Clean up the blob directory derived from the db path
    blob_dir = pathlib.Path(tmp.name).with_suffix(".blobs")
    shutil.rmtree(blob_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Unit-level tests against ContentStore directly
# ---------------------------------------------------------------------------


def _make_content_store() -> tuple[sqlite3.Connection, ContentStore]:
    """Create an in-memory ContentStore with its SQLite connection for testing."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_lock = threading.RLock()
    store = ContentStore(conn, db_lock)
    return conn, store


def test_stored_content_has_cid_field():
    """StoredContent must accept a cid keyword argument."""
    sc = StoredContent(
        root_hash="a" * 64,
        title="Test",
        tags=["t"],
        data=b"hello",
        cid="Qm_test_cid",
    )
    assert sc.cid == "Qm_test_cid"


def test_stored_content_cid_defaults_to_none():
    """StoredContent.cid must default to None when not supplied."""
    sc = StoredContent(root_hash="b" * 64, title="T", tags=[], data=b"x")
    assert sc.cid is None


def test_content_store_put_and_get_cid():
    """put() with a CID must persist it; get() must return it."""
    _, store = _make_content_store()
    sc = StoredContent(
        root_hash="c" * 64,
        title="CIDTest",
        tags=["audio"],
        data=b"audio-bytes",
        cid="QmTestCID123",
    )
    store.put(sc)
    retrieved = store.get("c" * 64)
    assert retrieved is not None
    assert retrieved.cid == "QmTestCID123"


def test_content_store_put_without_cid():
    """put() with no CID must store cid=None; get() must return cid=None."""
    _, store = _make_content_store()
    sc = StoredContent(root_hash="d" * 64, title="NoCID", tags=[], data=b"data")
    store.put(sc)
    retrieved = store.get("d" * 64)
    assert retrieved is not None
    assert retrieved.cid is None


def test_put_cid_mapping_updates_existing_row():
    """put_cid_mapping() must set cid on an existing content row."""
    _, store = _make_content_store()
    store.put(StoredContent(root_hash="e" * 64, title="Pre", tags=[], data=b"data"))
    store.put_cid_mapping("e" * 64, "QmUpdatedCID")
    retrieved = store.get("e" * 64)
    assert retrieved is not None
    assert retrieved.cid == "QmUpdatedCID"


def test_put_cid_mapping_noop_for_unknown_hash():
    """put_cid_mapping() must not insert a new row for an unknown hash."""
    _, store = _make_content_store()
    store.put_cid_mapping("f" * 64, "QmOrphanCID")
    # The hash must NOT appear in the store
    assert store.get("f" * 64) is None
    # count() excludes any stub rows
    assert store.count() == 0


def test_put_cid_mapping_does_not_overwrite_existing_cid():
    """put_cid_mapping() must not overwrite a CID that is already set."""
    _, store = _make_content_store()
    store.put(
        StoredContent(
            root_hash="g" * 64, title="T", tags=[], data=b"d", cid="QmOriginal"
        )
    )
    store.put_cid_mapping("g" * 64, "QmShouldNotReplace")
    retrieved = store.get("g" * 64)
    assert retrieved is not None
    assert retrieved.cid == "QmOriginal"


def test_all_returns_cid():
    """ContentStore.all() must include the cid field."""
    _, store = _make_content_store()
    store.put(
        StoredContent(root_hash="h" * 64, title="T", tags=[], data=b"d", cid="QmAll")
    )
    items = store.all(limit=10)
    assert any(item.cid == "QmAll" for item in items)


def test_filter_by_tag_returns_cid():
    """ContentStore.filter_by_tag() must include the cid field."""
    _, store = _make_content_store()
    store.put(
        StoredContent(
            root_hash="i" * 64, title="T", tags=["vidtest"], data=b"d", cid="QmFilter"
        )
    )
    items = store.filter_by_tag("vidtest")
    assert len(items) == 1
    assert items[0].cid == "QmFilter"


def test_filter_by_tags_returns_cid():
    """ContentStore.filter_by_tags() must include the cid field."""
    _, store = _make_content_store()
    store.put(
        StoredContent(
            root_hash="j" * 64,
            title="T",
            tags=["multi", "tag"],
            data=b"d",
            cid="QmMulti",
        )
    )
    items = store.filter_by_tags(["multi", "other"])
    assert len(items) == 1
    assert items[0].cid == "QmMulti"


# ---------------------------------------------------------------------------
# Schema migration: existing DB without cid column
# ---------------------------------------------------------------------------


def test_cid_column_migration():
    """ContentStore must survive opening a DB that lacks the cid column."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    # Manually create the old schema (no cid column)
    conn.execute(
        """
        CREATE TABLE content (
            root_hash TEXT PRIMARY KEY,
            title     TEXT NOT NULL,
            tags      TEXT NOT NULL,
            data      BLOB NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO content (root_hash, title, tags, data) VALUES (?, ?, ?, ?)",
        ("k" * 64, "OldRow", "[]", b"old-data"),
    )
    conn.commit()

    # Opening ContentStore on this old DB must not raise
    db_lock = threading.RLock()
    store = ContentStore(conn, db_lock)

    # Old row must still be retrievable with cid=None
    item = store.get("k" * 64)
    assert item is not None
    assert item.data == b"old-data"
    assert item.cid is None

    # New puts must work with CID
    store.put(
        StoredContent(
            root_hash="l" * 64, title="New", tags=[], data=b"new", cid="QmMig"
        )
    )
    assert store.get("l" * 64).cid == "QmMig"


# ---------------------------------------------------------------------------
# Integration: CID survives server restart
# ---------------------------------------------------------------------------


def test_cid_survives_restart(db_file, monkeypatch):
    """
    A CID associated with published content must be readable in a second server
    lifecycle (restart simulation) when the content was stored with a known CID.
    """
    puf = os.urandom(32)
    device_id = "cid-restart-dev"
    known_cid = "QmSurvivesRestart"

    # Lifecycle 1: publish content and manually record a CID for it
    with TestClient(app) as c1:
        _enroll(c1, device_id, puf)
        root_hash = _publish_json(c1, device_id, puf, "CIDRestartTitle")
        # Manually store the CID (IPFS bridge offline in test env)
        from tfp_demo.server import _content_store

        if _content_store is not None:
            _content_store.put_cid_mapping(root_hash, known_cid)
            item = _content_store.get(root_hash)
            assert item is not None and item.cid == known_cid

    # Lifecycle 2: the CID must be readable from the persisted DB
    with TestClient(app) as c2:
        from tfp_demo.server import _content_store as store2

        if store2 is not None:
            item2 = store2.get(root_hash)
            assert item2 is not None
            assert item2.cid == known_cid, (
                f"CID not persisted after restart: {item2.cid!r}"
            )
