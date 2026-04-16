# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import collections
import hashlib
import hmac as _hmac
import json
import logging
import os
import re
import sqlite3
import threading

import time

from tfp_demo.database import Database, get_database_from_env
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from tfp_client.lib.bridges.ipfs_bridge import IPFSBridge
from pydantic import BaseModel, Field, ValidationError
from tfp_demo.config_validation import validate_runtime_config
from tfp_broadcaster.broadcaster import Broadcaster
from tfp_client.lib.bridges.nostr_subscriber import NostrSubscriber
from tfp_client.lib.bridges.nostr_bridge import (
    NostrBridge,
    TFP_CONTENT_KIND,
    TFP_SEARCH_INDEX_KIND,
    TFP_CONTENT_ANNOUNCE_KIND,
    _schnorr_verify,
)
from tfp_client.lib.compute.credit_formula import CreditFormula
from tfp_client.lib.compute.task_executor import (
    TaskSpec,
    generate_content_verify_task,
    generate_hash_preimage_task,
    generate_matrix_verify_task,
)
from tfp_client.lib.compute.verify_habp import (
    HABPVerifier,
    generate_execution_proof,
)
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import MAX_SUPPLY, CreditLedger, Receipt
from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter
from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree
from tfp_client.lib.metadata.tag_index import TagOverlayIndex
from tfp_client.lib.ndn.adapter import Data, NDNAdapter
from tfp_client.lib.reconstruction.template_assembler import (
    Recipe,
    TemplateAssembler,
)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "pib.db"

# Database instance (initialized in lifespan)
_db: Optional[Database] = None

# Track ongoing chunked uploads: upload_id -> {chunks: {index: bytes}, total_chunks: int, created_at: float}
_ongoing_uploads: Dict[str, Dict] = {}
_uploads_lock = threading.Lock()
_UPLOAD_CLEANUP_INTERVAL_SECONDS = 3600  # Clean up uploads older than 1 hour
_UPLOAD_MAX_AGE_SECONDS = 3600  # Maximum age for an upload session
_last_cleanup_time = 0.0  # Track last cleanup time

# Configure logging explicitly for security monitoring
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@dataclass
class StoredContent:
    root_hash: str
    title: str
    tags: List[str]
    data: Optional[bytes] = (
        None  # populated by ContentStore.get(); None for metadata-only
    )
    cid: Optional[str] = None  # IPFS CID when available; None until pinned
    blob_path: Optional[str] = None  # BlobStore key; None for seed-only items
    size_bytes: int = 0
    recipe_json: Optional[str] = None  # Recipe JSON when chunking was used


# ---------------------------------------------------------------------------
# Blob store — filesystem/in-memory separation of raw blob data from metadata
# ---------------------------------------------------------------------------


_SAFE_HASH_RE = re.compile(r"^[a-zA-Z0-9_-]{1,256}$")


def _validate_hash_component(value: str) -> str:
    """Reject path-traversal payloads in hash-derived filesystem keys.

    Allows alphanumeric characters, hyphens, and underscores.  Blocks
    slashes, dots, spaces, and other characters that could be used for
    directory traversal or filesystem abuse.
    """
    if not _SAFE_HASH_RE.match(value):
        raise ValueError(
            f"invalid hash component (must be 1-256 alphanumeric/hyphen/underscore chars): {value!r}"
        )
    return value


class BlobStore:
    """
    Manages raw content blobs separately from the SQLite metadata tables.

    Two modes:
    - ``blob_dir=None``: in-memory dict; suitable for :memory: test DBs.
      Data is lost on restart but all tests pass without disk access.
    - ``blob_dir=Path``: filesystem; data survives restarts.
      Each blob is a file at ``<blob_dir>/<root_hash>``.
      Each shard is at ``<blob_dir>/<root_hash>/shards/shard_{N:04d}``.

    The key returned by :meth:`put` is opaque — store it as ``blob_path``
    in SQLite and pass it back to :meth:`get` / :meth:`open_stream`.
    """

    def __init__(self, blob_dir: Optional[Path]) -> None:
        self._dir = blob_dir
        self._mem: Dict[str, bytes] = {}

    def put(self, root_hash: str, data: bytes) -> str:
        """Write blob data; return the opaque key for later retrieval."""
        _validate_hash_component(root_hash)
        if self._dir is not None:
            path = self._dir / root_hash
            path.write_bytes(data)
            return str(path)
        self._mem[root_hash] = data
        return root_hash

    def get(self, key: str) -> Optional[bytes]:
        """Read blob by key; return None if not found."""
        if self._dir is not None:
            p = Path(key).resolve()
            if not str(p).startswith(str(self._dir.resolve())):
                log.warning("BlobStore.get: path traversal blocked: %s", key)
                return None
            return p.read_bytes() if p.exists() else None
        return self._mem.get(key)

    def exists(self, key: str) -> bool:
        if self._dir is not None:
            p = Path(key).resolve()
            if not str(p).startswith(str(self._dir.resolve())):
                return False
            return p.exists()
        return key in self._mem

    def get_size(self, key: str) -> int:
        """Return byte size of the stored blob; 0 if not found."""
        if self._dir is not None:
            p = Path(key).resolve()
            if not str(p).startswith(str(self._dir.resolve())):
                return 0
            return p.stat().st_size if p.exists() else 0
        return len(self._mem.get(key, b""))

    def open_stream(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        """Yield blob bytes in *chunk_size* chunks (O(1) memory in filesystem mode)."""
        if self._dir is not None:
            p = Path(key).resolve()
            if not str(p).startswith(str(self._dir.resolve())):
                return
            if p.exists():
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
        else:
            data = self._mem.get(key, b"")
            for i in range(0, len(data), chunk_size):
                yield data[i : i + chunk_size]

    def put_shard(self, root_hash: str, shard_idx: int, data: bytes) -> str:
        """Write a shard; return its opaque key."""
        _validate_hash_component(root_hash)
        shard_name = f"shard_{shard_idx:04d}"
        if self._dir is not None:
            shard_dir = self._dir / f"{root_hash}.shards"
            shard_dir.mkdir(parents=True, exist_ok=True)
            path = shard_dir / shard_name
            path.write_bytes(data)
            return str(path)
        key = f"{root_hash}/shards/{shard_name}"
        self._mem[key] = data
        return key

    def get_shard(self, root_hash: str, shard_idx: int) -> Optional[bytes]:
        """Read shard by root_hash and index; return None if not found."""
        _validate_hash_component(root_hash)
        shard_name = f"shard_{shard_idx:04d}"
        if self._dir is not None:
            path = self._dir / f"{root_hash}.shards" / shard_name
            return path.read_bytes() if path.exists() else None
        key = f"{root_hash}/shards/{shard_name}"
        return self._mem.get(key)

    def shard_count(self, root_hash: str) -> int:
        """Return the number of shards stored for *root_hash*."""
        _validate_hash_component(root_hash)
        if self._dir is not None:
            shard_dir = self._dir / f"{root_hash}.shards"
            if not shard_dir.exists():
                return 0
            return sum(1 for f in shard_dir.iterdir() if f.name.startswith("shard_"))
        prefix = f"{root_hash}/shards/shard_"
        return sum(1 for k in self._mem if k.startswith(prefix))


# ---------------------------------------------------------------------------
# Content store (SQLite-backed metadata + BlobStore for blobs)
# ---------------------------------------------------------------------------


class ContentStore:
    """
    Persistent content store: SQLite for metadata, BlobStore for raw blobs.

    Schema (new):  root_hash, title, tags, blob_path, cid, size_bytes, recipe_json
    The ``blob_path`` column holds the opaque key returned by BlobStore.put().

    Migration: if an existing DB has the old ``data BLOB NOT NULL`` schema, the
    migration method is called automatically on construction.  All existing blob
    data is moved to the provided (or default in-memory) BlobStore.

    The in-memory ``_tag_index`` maps tag → set[root_hash] for O(1) tag lookups
    on the hot ``filter_by_tag`` path.  It is rebuilt from the DB on construction
    and kept in sync on every ``put``.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        db_lock: threading.RLock,
        blob_store: Optional[BlobStore] = None,
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        # Default to in-memory BlobStore so tests work without a filesystem.
        self._blob_store: BlobStore = (
            blob_store if blob_store is not None else BlobStore(None)
        )
        self._tag_index: Dict[str, set] = {}
        self._init_schema()
        self._rebuild_tag_index()

    # ------------------------------------------------------------------
    # Schema init + migration
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._db_lock:
            existing = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content'"
            ).fetchone()

            if existing:
                cols = {
                    row[1]
                    for row in self._conn.execute(
                        "PRAGMA table_info(content)"
                    ).fetchall()
                }
                if "blob_path" not in cols:
                    # Legacy schema: has 'data BLOB' — migrate to BlobStore schema.
                    self._migrate_from_blob_schema(cols)
                else:
                    # New schema already present; add any columns added after initial migration.
                    for col_name, col_def in [
                        ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
                        ("recipe_json", "TEXT"),
                    ]:
                        if col_name not in cols:
                            self._conn.execute(
                                f"ALTER TABLE content ADD COLUMN {col_name} {col_def}"
                            )
                    self._conn.commit()
            else:
                # Fresh DB: create new schema directly.
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS content (
                        root_hash   TEXT PRIMARY KEY,
                        title       TEXT NOT NULL,
                        tags        TEXT NOT NULL,
                        blob_path   TEXT,
                        cid         TEXT,
                        size_bytes  INTEGER NOT NULL DEFAULT 0,
                        recipe_json TEXT
                    )
                    """
                )
                self._conn.commit()

    def _migrate_from_blob_schema(self, existing_cols: set) -> None:
        """
        Migrate the old ``content`` table (data BLOB NOT NULL) to the new
        schema (blob_path TEXT + size_bytes + recipe_json).

        Each existing BLOB is written to ``_blob_store`` so that subsequent
        ``get()`` calls can retrieve the data transparently.
        """
        log.info("ContentStore: migrating legacy BLOB schema → BlobStore schema")
        has_cid = "cid" in existing_cols
        if has_cid:
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, data, cid FROM content"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, data FROM content"
            ).fetchall()

        # Build new table while old one still exists.
        self._conn.execute(
            """
            CREATE TABLE content_new (
                root_hash   TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                tags        TEXT NOT NULL,
                blob_path   TEXT,
                cid         TEXT,
                size_bytes  INTEGER NOT NULL DEFAULT 0,
                recipe_json TEXT
            )
            """
        )
        for row in rows:
            root_hash, title, tags = row[0], row[1], row[2]
            raw_data = row[3]
            data = bytes(raw_data) if raw_data is not None else b""
            cid = row[4] if has_cid else None
            blob_path: Optional[str] = None
            if data:
                blob_path = self._blob_store.put(root_hash, data)
            self._conn.execute(
                "INSERT INTO content_new"
                " (root_hash, title, tags, blob_path, cid, size_bytes)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (root_hash, title, tags, blob_path, cid, len(data)),
            )

        # executescript issues an implicit COMMIT before running each statement.
        self._conn.executescript(
            "DROP TABLE content; ALTER TABLE content_new RENAME TO content;"
        )
        self._conn.commit()
        log.info(
            "ContentStore: migration complete (%d rows moved to BlobStore)", len(rows)
        )

    # ------------------------------------------------------------------
    # Tag index
    # ------------------------------------------------------------------

    def _rebuild_tag_index(self) -> None:
        """Rebuild the in-memory tag index from current DB rows."""
        self._tag_index.clear()
        rows = self._conn.execute("SELECT root_hash, tags FROM content").fetchall()
        for root_hash, tags_json in rows:
            for tag in json.loads(tags_json):
                self._tag_index.setdefault(tag, set()).add(root_hash)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def put(self, item: StoredContent) -> None:
        """Persist *item*; raw blob is written to BlobStore, metadata to SQLite."""
        blob_path: Optional[str] = item.blob_path
        size_bytes: int = item.size_bytes

        if item.data:
            # Write blob to BlobStore if not already stored (idempotent).
            blob_path = self._blob_store.put(item.root_hash, item.data)
            size_bytes = len(item.data)

        with self._db_lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO content
                    (root_hash, title, tags, blob_path, cid, size_bytes, recipe_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.root_hash,
                    item.title,
                    json.dumps(item.tags),
                    blob_path,
                    item.cid,
                    size_bytes,
                    item.recipe_json,
                ),
            )
            self._conn.commit()
            for tag in item.tags:
                self._tag_index.setdefault(tag, set()).add(item.root_hash)

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    def _row_to_stored_content(
        self, row: tuple, include_data: bool = False
    ) -> StoredContent:
        """Convert a DB row tuple to StoredContent."""
        blob_path = row[3]
        data: Optional[bytes] = None
        if include_data and blob_path:
            data = self._blob_store.get(blob_path)
        return StoredContent(
            root_hash=row[0],
            title=row[1],
            tags=json.loads(row[2]),
            data=data,
            blob_path=blob_path,
            cid=row[4],
            size_bytes=row[5] or 0,
            recipe_json=row[6] if len(row) > 6 else None,
        )

    def get(self, root_hash: str) -> Optional[StoredContent]:
        """Return StoredContent with blob data loaded from BlobStore."""
        with self._db_lock:
            row = self._conn.execute(
                "SELECT root_hash, title, tags, blob_path, cid, size_bytes, recipe_json"
                " FROM content WHERE root_hash = ?",
                (root_hash,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_stored_content(row, include_data=True)

    def get_blob_path(self, root_hash: str) -> Optional[str]:
        """Return the BlobStore key for *root_hash* without loading the blob."""
        with self._db_lock:
            row = self._conn.execute(
                "SELECT blob_path FROM content WHERE root_hash = ?", (root_hash,)
            ).fetchone()
            return row[0] if row else None

    def all(self, limit: int = 100, offset: int = 0) -> List[StoredContent]:
        """Return metadata-only items (data=None) in reverse-insertion order."""
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, blob_path, cid, size_bytes, recipe_json"
                " FROM content ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._row_to_stored_content(r) for r in rows]

    def filter_by_tag(
        self, tag: str, limit: int = 100, offset: int = 0
    ) -> List[StoredContent]:
        """Return metadata-only items matching *tag*."""
        with self._db_lock:
            hashes = self._tag_index.get(tag, set())
            if not hashes:
                return []
            # Use parameterized query - hashes are indexed values from tag_index
            placeholders = ",".join("?" * len(hashes))
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, blob_path, cid, size_bytes, recipe_json"
                f" FROM content WHERE root_hash IN ({placeholders})"  # nosec B608 - parameterized query, hashes validated as set membership from tag_index
                " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*list(hashes), limit, offset],
            ).fetchall()
            return [self._row_to_stored_content(r) for r in rows]

    def count_tag(self, tag: str) -> int:
        """Return the number of items matching tag."""
        with self._db_lock:
            return len(self._tag_index.get(tag, set()))

    def filter_by_tags(
        self, tags: List[str], limit: int = 100, offset: int = 0
    ) -> List[StoredContent]:
        """
        Return metadata-only items matching ANY of the given tags (union semantics).

        Uses the in-memory tag index to collect root hashes, then does a
        single bulk IN-query — O(n_matches), not O(N_total).
        """
        with self._db_lock:
            hashes: set = set()
            for tag in tags:
                hashes |= self._tag_index.get(tag, set())
            if not hashes:
                return []
            # Use parameterized query - hashes are indexed values from tag_index
            placeholders = ",".join("?" * len(hashes))
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, blob_path, cid, size_bytes, recipe_json"
                f" FROM content WHERE root_hash IN ({placeholders})"  # nosec B608 - parameterized query, hashes validated as set membership from tag_index
                " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*list(hashes), limit, offset],
            ).fetchall()
            return [self._row_to_stored_content(r) for r in rows]

    def count_tags(self, tags: List[str]) -> int:
        """Return total items matching ANY of the given tags."""
        with self._db_lock:
            hashes: set = set()
            for tag in tags:
                hashes |= self._tag_index.get(tag, set())
            return len(hashes)

    def put_cid_mapping(self, root_hash: str, cid: str) -> None:
        """
        Durably associate *cid* with an existing content record.

        Only updates rows that already exist and have no CID yet.  Safe to call
        from Nostr event handlers without risking stub rows with missing blobs.
        """
        with self._db_lock:
            self._conn.execute(
                "UPDATE content SET cid = ? WHERE root_hash = ? AND (cid IS NULL OR cid = '')",
                (cid, root_hash),
            )
            self._conn.commit()

    def contains(self, root_hash: str) -> bool:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT 1 FROM content WHERE root_hash = ?", (root_hash,)
            ).fetchone()
            return row is not None

    def count(self) -> int:
        with self._db_lock:
            return self._conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]


# ---------------------------------------------------------------------------
# Device registry (SQLite-backed)
# ---------------------------------------------------------------------------


class DeviceRegistry:
    """Stores enrolled device PUF entropy for request-signing verification."""

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id   TEXT PRIMARY KEY,
                    puf_entropy BLOB NOT NULL,
                    enrolled_at REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def enroll(self, device_id: str, puf_entropy: bytes) -> None:
        with self._db_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO devices (device_id, puf_entropy, enrolled_at) "
                "VALUES (?, ?, ?)",
                (device_id, puf_entropy, time.time()),
            )
            self._conn.commit()

    def get_entropy(self, device_id: str) -> Optional[bytes]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT puf_entropy FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return bytes(row[0]) if row else None

    def is_enrolled(self, device_id: str) -> bool:
        return self.get_entropy(device_id) is not None

    def count(self) -> int:
        """Return the total number of enrolled devices."""
        with self._db_lock:
            return self._conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]


def _verify_device_sig(
    device_id: str,
    sig_hex: str,
    message: str,
    registry: DeviceRegistry,
) -> bool:
    """Verify HMAC-SHA-256(puf_entropy, message) == sig_hex (constant-time)."""
    puf_entropy = registry.get_entropy(device_id)
    if puf_entropy is None:
        return False
    expected = _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, sig_hex)


# ---------------------------------------------------------------------------
# Earn log — prevents credit replay (duplicate task_id per device)
# ---------------------------------------------------------------------------


class EarnLog:
    """
    SQLite-backed deduplication log for ``/api/earn`` calls.

    Each (device_id, task_id) pair is stored exactly once.  A second attempt
    to record the same pair returns ``False`` so the caller can reject it with
    HTTP 409 rather than silently minting extra credits.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            # Enable foreign key enforcement for referential integrity
            self._conn.execute("PRAGMA foreign_keys = ON")
            # Check if devices table exists before adding FK constraint
            # (for test compatibility where EarnLog may be created without DeviceRegistry)
            devices_exists = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
            ).fetchone()
            fk_clause = (
                ", FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE"
                if devices_exists
                else ""
            )
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS earn_log (
                    device_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    earned_at REAL NOT NULL,
                    PRIMARY KEY (device_id, task_id)
                    {fk_clause}
                )
                """
            )
            self._conn.commit()

    def record(self, device_id: str, task_id: str) -> bool:
        """Attempt to record an earn event.  Returns True if new, False if duplicate."""
        with self._db_lock:
            try:
                self._conn.execute(
                    "INSERT INTO earn_log (device_id, task_id, earned_at) VALUES (?, ?, ?)",
                    (device_id, task_id, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError as exc:
                # Check if it's a UNIQUE constraint violation (duplicate key)
                if (
                    "UNIQUE constraint" in str(exc)
                    or "duplicate key" in str(exc).lower()
                ):
                    return False
                # Re-raise other IntegrityErrors (e.g., FK violations)
                raise


# ---------------------------------------------------------------------------
# Credit store — persists ledger state across server restarts
# ---------------------------------------------------------------------------


class CreditStore:
    """
    SQLite-backed persistence for per-device CreditLedger state.

    Stores the hash chain, current balance, and the unspent receipt hashes so
    the ledger can be fully reconstructed after a server restart.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            # Enable foreign key enforcement for referential integrity
            self._conn.execute("PRAGMA foreign_keys = ON")
            # Check if devices table exists before adding FK constraint
            # (for test compatibility where CreditStore may be created without DeviceRegistry)
            devices_exists = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
            ).fetchone()
            fk_clause = (
                ", FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE"
                if devices_exists
                else ""
            )
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    device_id             TEXT PRIMARY KEY,
                    balance               INTEGER NOT NULL DEFAULT 0,
                    chain_json            TEXT    NOT NULL DEFAULT '[]',
                    unspent_receipts_json TEXT    NOT NULL DEFAULT '[]'
                    {fk_clause}
                )
                """
            )
            self._conn.commit()

    def save(self, device_id: str, client: "TFPClient") -> None:
        """Persist the client's current ledger + unspent receipts."""
        chain_json = json.dumps([h.hex() for h in client.ledger.chain])
        balance = client.ledger.balance
        unspent_json = json.dumps([r.chain_hash.hex() for r in client._earned_receipts])
        with self._db_lock:
            self._conn.execute(
                """
                INSERT INTO credit_ledger (device_id, balance, chain_json, unspent_receipts_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    balance               = excluded.balance,
                    chain_json            = excluded.chain_json,
                    unspent_receipts_json = excluded.unspent_receipts_json
                """,
                (device_id, balance, chain_json, unspent_json),
            )
            self._conn.commit()

    def load(self, device_id: str) -> Optional["TFPClient"]:
        """
        Restore a TFPClient with a persisted ledger, or return None if no
        record exists for this device.
        """
        with self._db_lock:
            row = self._conn.execute(
                "SELECT balance, chain_json, unspent_receipts_json FROM credit_ledger WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            balance, chain_json, unspent_json = row
            chain = [bytes.fromhex(h) for h in json.loads(chain_json)]
            ledger = CreditLedger.from_snapshot(chain, balance)
            unspent_receipts = [
                Receipt(chain_hash=bytes.fromhex(h), credits=10)
                for h in json.loads(unspent_json)
            ]
            client = TFPClient(
                ndn=DemoNDNAdapter(
                    _content_store, blob_store=_blob_store, peer_fallback=_peer_fallback
                ),
                ledger=ledger,
            )
            client._earned_receipts = unspent_receipts
            return client


# ---------------------------------------------------------------------------
# Task store — SQLite-backed compute task registry
# ---------------------------------------------------------------------------


class TaskStore:
    """
    Persistent store for compute tasks, bids, and results.

    Tasks flow through these states:
      open → bidding → assigned → verifying → completed | failed
    """

    _GENERATORS = {
        "hash_preimage": generate_hash_preimage_task,
        "matrix_verify": generate_matrix_verify_task,
        "content_verify": generate_content_verify_task,
    }

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._habp = HABPVerifier(consensus_threshold=3, redundancy_factor=5)
        self._credit_formula = CreditFormula()
        # RLock so that submit_result() (outer) can call increment_total_minted() (inner)
        # without deadlocking on re-entry.
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            # Enable foreign key enforcement for referential integrity
            self._conn.execute("PRAGMA foreign_keys = ON")
            # Check if devices table exists before adding FK constraint
            # (for test compatibility where TaskStore may be created without DeviceRegistry)
            devices_exists = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
            ).fetchone()
            devices_fk = (
                ", FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE"
                if devices_exists
                else ""
            )
            self._conn.executescript(
                f"""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id      TEXT PRIMARY KEY,
                task_type    TEXT NOT NULL,
                difficulty   INT  NOT NULL,
                spec_json    TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'open',
                created_at   REAL NOT NULL,
                deadline     REAL NOT NULL,
                credit_reward INT NOT NULL DEFAULT 10
            );
            CREATE TABLE IF NOT EXISTS task_results (
                result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      TEXT NOT NULL,
                device_id    TEXT NOT NULL,
                output_hash  TEXT NOT NULL,
                exec_time_s  REAL NOT NULL,
                has_tee      INT  NOT NULL DEFAULT 0,
                submitted_at REAL NOT NULL,
                UNIQUE(task_id, device_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                {devices_fk}
            );
            CREATE TABLE IF NOT EXISTS supply_ledger (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                total_minted   INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO supply_ledger (id, total_minted) VALUES (1, 0);
            """
            )
        self._conn.commit()
        # Rebuild in-memory HABP state from persisted results for tasks still verifying
        self._rebuild_habp_from_db()

    def _rebuild_habp_from_db(self) -> None:
        """Replay persisted proofs into HABPVerifier so consensus survives restarts.

        Verifies that output_hash in DB matches the task spec's expected output hash
        before rebuilding to prevent DB corruption from poisoning HABP state.
        """
        rows = self._conn.execute(
            """
            SELECT r.task_id, r.device_id, r.output_hash, r.exec_time_s, r.has_tee, t.spec_json
            FROM task_results r
            JOIN tasks t ON t.task_id = r.task_id
            WHERE t.status IN ('verifying', 'open')
            ORDER BY r.submitted_at
            """
        ).fetchall()
        for task_id, device_id, output_hash, exec_time_s, has_tee, spec_json in rows:
            try:
                import json

                spec = json.loads(spec_json)
                expected_hash = spec.get("expected_output_hash")
                if expected_hash and output_hash != expected_hash:
                    log.warning(
                        "Skipping HABP rebuild for task=%s device=%s: output_hash mismatch "
                        "(DB=%s, expected=%s) - DB may be corrupted",
                        task_id[:16],
                        device_id[:16],
                        output_hash[:16],
                        expected_hash[:16],
                    )
                    continue
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning(
                    "Skipping HABP rebuild for task=%s device=%s: failed to parse spec: %s",
                    task_id[:16],
                    device_id[:16],
                    exc,
                )
                continue

            proof = generate_execution_proof(
                device_id=device_id,
                task_id=task_id,
                output_data=bytes.fromhex(output_hash)
                if len(output_hash) == 64
                else output_hash.encode(),
                execution_time=exec_time_s,
                has_tee=bool(has_tee),
            )
            proof.output_hash = output_hash
            self._habp.submit_proof(proof)
        if rows:
            log.info(
                "Rebuilt HABP state from %d persisted proofs across %d tasks",
                len(rows),
                len(set(r[0] for r in rows)),
            )

    # -- Supply tracking -------------------------------------------------------

    def get_total_minted(self) -> int:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT total_minted FROM supply_ledger WHERE id = 1"
            ).fetchone()
            return row[0] if row else 0

    def increment_total_minted(self, amount: int) -> int:
        """Atomically increment and return new total. Raises if cap exceeded.

        Uses atomic SQL UPDATE with condition check to prevent race condition
        where concurrent threads both pass the cap check before update.

        In multi-node deployments, also checks against gossiped total from other
        nodes with a buffer to prevent supply cap bypass across the network.
        """
        from tfp_client.lib.credit.ledger import SupplyCapError

        with self._db_lock:
            with self._lock:
                # Get gossiped total from other nodes (if available)
                # Use a buffer to account for network propagation delays
                gossiped_total = 0
                with _gossiped_supply_lock:
                    gossiped_total = _gossiped_supply_total

                # Effective cap is min of local cap and gossiped total + buffer
                # Buffer allows for concurrent mints across nodes (configurable)
                # When no gossip received (single-node), use full MAX_SUPPLY
                if gossiped_total > 0:
                    buffer = int(os.environ.get("TFP_SUPPLY_GOSSIP_BUFFER", "1000"))
                    effective_cap = min(MAX_SUPPLY, gossiped_total + buffer)
                else:
                    effective_cap = MAX_SUPPLY

                # Atomic UPDATE: only succeeds if new total won't exceed effective cap
                cursor = self._conn.execute(
                    "UPDATE supply_ledger "
                    "SET total_minted = total_minted + ? "
                    "WHERE id = 1 AND total_minted + ? <= ?",
                    (amount, amount, effective_cap),
                )
                if cursor.rowcount == 0:
                    # Update failed: cap would be exceeded
                    current = self.get_total_minted()
                    raise SupplyCapError(
                        f"Global supply cap reached: {current}/{MAX_SUPPLY} "
                        f"(effective cap: {effective_cap})"
                    )
                self._conn.commit()
                return self.get_total_minted()

    # -- Task lifecycle --------------------------------------------------------

    def create_task(self, task_type: str, difficulty: int, seed: bytes) -> TaskSpec:
        """Generate and persist a new compute task."""
        task_id = hashlib.sha3_256(
            seed + task_type.encode() + str(time.time()).encode()
        ).hexdigest()
        if task_type == "content_verify":
            spec = generate_content_verify_task(
                task_id=task_id, difficulty=difficulty, content=seed
            )
        else:
            gen = self._GENERATORS.get(task_type)
            if gen is None:
                raise ValueError(f"Unknown task_type: {task_type!r}")
            spec = gen(task_id=task_id, difficulty=difficulty, seed=seed)
        with self._db_lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO tasks
                  (task_id, task_type, difficulty, spec_json, status, created_at, deadline, credit_reward)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    spec.task_id,
                    spec.task_type.value,
                    spec.difficulty,
                    json.dumps(spec.to_dict()),
                    spec.created_at,
                    spec.deadline,
                    spec.credit_reward,
                ),
            )
            self._conn.commit()
        return spec

    def list_open_tasks(self, limit: int = 20) -> List[dict]:
        """Return open tasks suitable for device consumption (reaps expired first)."""
        self.reap_expired_tasks()
        now = time.time()
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT task_id, task_type, difficulty, credit_reward, deadline
                FROM tasks
                WHERE status = 'open' AND deadline > ?
                ORDER BY created_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            return [
                {
                    "task_id": r[0],
                    "task_type": r[1],
                    "difficulty": r[2],
                    "credit_reward": r[3],
                    "deadline": r[4],
                    "time_left_s": round(r[4] - now),
                }
                for r in rows
            ]

    def reap_expired_tasks(self) -> int:
        """
        Mark all open/verifying tasks past their deadline as failed.

        Returns the count of tasks reaped. Called automatically before listing
        open tasks so the pool never shows stale entries.
        """
        now = time.time()
        with self._db_lock:
            with self._lock:
                cur = self._conn.execute(
                    """
                    UPDATE tasks SET status = 'failed'
                    WHERE status IN ('open', 'verifying') AND deadline < ?
                    """,
                    (now,),
                )
                self._conn.commit()
                reaped = cur.rowcount
        if reaped:
            log.info("Reaped %d expired tasks", reaped)
        return reaped

    def get_spec(self, task_id: str) -> Optional[TaskSpec]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT spec_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            return TaskSpec.from_dict(json.loads(row[0]))

    def get_task_row(self, task_id: str) -> Optional[dict]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT task_id, task_type, difficulty, status, credit_reward, created_at, deadline "
                "FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "task_id": row[0],
                "task_type": row[1],
                "difficulty": row[2],
                "status": row[3],
                "credit_reward": row[4],
                "created_at": row[5],
                "deadline": row[6],
            }

    def submit_result(
        self,
        task_id: str,
        device_id: str,
        output_hash: str,
        exec_time_s: float,
        has_tee: bool = False,
    ) -> dict:
        """
        Accept a result submission.

        Returns a dict with keys: status, verified, credits_earned (0 if not yet verified),
        and consensus_needed (how many more proofs are required for consensus).

        The entire method runs under both locks to serialize concurrent
        submissions and prevent HABP proof accumulation (self-mint attack).
        """
        with self._db_lock:
            with self._lock:
                task_row = self.get_task_row(task_id)
                if task_row is None:
                    raise HTTPException(status_code=404, detail="task not found")
                if task_row["status"] in ("completed", "failed"):
                    raise HTTPException(
                        status_code=409, detail="task already finalised"
                    )
                if time.time() > task_row["deadline"]:
                    self._conn.execute(
                        "UPDATE tasks SET status = 'failed' WHERE task_id = ?",
                        (task_id,),
                    )
                    self._conn.commit()
                    raise HTTPException(status_code=410, detail="task deadline passed")

                # Record result — UNIQUE(task_id, device_id) prevents duplicate rows.
                # Check rowcount: if 0 the device already submitted for this task and
                # we must NOT add another HABP proof (would allow a single device to
                # accumulate enough proofs to reach consensus alone — self-mint attack).
                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO task_results
                      (task_id, device_id, output_hash, exec_time_s, has_tee, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        device_id,
                        output_hash,
                        exec_time_s,
                        int(has_tee),
                        time.time(),
                    ),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(
                        status_code=409,
                        detail="result already submitted for this device and task",
                    )
                self._conn.execute(
                    "UPDATE tasks SET status = 'verifying' WHERE task_id = ? AND status = 'open'",
                    (task_id,),
                )
                self._conn.commit()

                # Build HABP proof and attempt consensus
                proof = generate_execution_proof(
                    device_id=device_id,
                    task_id=task_id,
                    output_data=bytes.fromhex(output_hash)
                    if len(output_hash) == 64
                    else output_hash.encode(),
                    execution_time=exec_time_s,
                    has_tee=has_tee,
                )
                # Override the output_hash with what the device reported
                proof.output_hash = output_hash
                self._habp.submit_proof(proof)

                consensus = self._habp.verify_consensus(task_id)
                if consensus and consensus.verified:
                    # Mark completed and compute credits
                    calc = self._credit_formula.calculate_credits(
                        difficulty=task_row["difficulty"],
                        hardware_trust=consensus.credit_weight,
                        uptime_hours=24.0,
                        verification_confidence=consensus.confidence,
                        is_charging=False,
                    )
                    credits = calc.final_credits
                    self._conn.execute(
                        "UPDATE tasks SET status = 'completed' WHERE task_id = ?",
                        (task_id,),
                    )
                    self._conn.commit()
                    return {
                        "status": "verified",
                        "verified": True,
                        "credits_earned": credits,
                        "consensus_needed": 0,
                        "matching_devices": consensus.matching_devices,
                        "confidence": consensus.confidence,
                    }

                # Count current proofs
                proof_count = self._habp.get_proof_count(task_id)
                needed = max(0, 3 - proof_count)
                return {
                    "status": "pending_consensus",
                    "verified": False,
                    "credits_earned": 0,
                    "consensus_needed": needed,
                    "proofs_received": proof_count,
                }

    def stats(self) -> dict:
        """Return aggregate task statistics."""
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status"
            ).fetchall()
            counts = {r[0]: r[1] for r in rows}
            return {
                "open": counts.get("open", 0),
                "verifying": counts.get("verifying", 0),
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
                "total": sum(counts.values()),
                "total_minted": self.get_total_minted(),
                "supply_cap": MAX_SUPPLY,
                "supply_remaining": MAX_SUPPLY - self.get_total_minted(),
            }

    def device_leaderboard(self, limit: int = 50) -> List[dict]:
        """
        Return top contributing devices sorted by credits earned (balance).

        Joins the devices table with credit_ledger for balance and
        task_results for number of tasks contributed.
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT
                    d.device_id,
                    d.enrolled_at,
                    COALESCE(cl.balance, 0)          AS credits_balance,
                    COUNT(DISTINCT tr.task_id)        AS tasks_contributed,
                    MAX(tr.submitted_at)              AS last_active
                FROM devices d
                LEFT JOIN credit_ledger cl ON cl.device_id = d.device_id
                LEFT JOIN task_results   tr ON tr.device_id = d.device_id
                GROUP BY d.device_id
                ORDER BY credits_balance DESC, tasks_contributed DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "device_id": r[0],
                    "enrolled_at": r[1],
                    "credits_balance": r[2],
                    "tasks_contributed": r[3],
                    "last_active": r[4],
                }
                for r in rows
            ]

    def device_stats(self, device_id: str) -> Optional[dict]:
        """
        Return stats for a single device — O(1) direct query.
        Returns None if the device has never contributed a task.
        """
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT
                    d.device_id,
                    d.enrolled_at,
                    COALESCE(cl.balance, 0)          AS credits_balance,
                    COUNT(DISTINCT tr.task_id)        AS tasks_contributed,
                    MAX(tr.submitted_at)              AS last_active
                FROM devices d
                LEFT JOIN credit_ledger cl ON cl.device_id = d.device_id
                LEFT JOIN task_results   tr ON tr.device_id = d.device_id
                WHERE d.device_id = ?
                GROUP BY d.device_id
                """,
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "device_id": row[0],
                "enrolled_at": row[1],
                "credits_balance": row[2],
                "tasks_contributed": row[3],
                "last_active": row[4],
            }


# ---------------------------------------------------------------------------
# Prometheus metrics (in-process counters)
# ---------------------------------------------------------------------------


class _Metrics:
    """
    Lightweight in-process counters for Prometheus text exposition format.
    No external dependency — pure Python.  For production, swap to
    prometheus_client if desired.

    Counters are seeded from SQLite on startup so they survive server restarts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "tfp_tasks_created_total": 0,
            "tfp_tasks_completed_total": 0,
            "tfp_tasks_failed_total": 0,
            "tfp_results_submitted_total": 0,
            "tfp_credits_minted_total": 0,
            "tfp_credits_spent_total": 0,
            "tfp_content_published_total": 0,
            "tfp_content_served_total": 0,
            "tfp_devices_enrolled_total": 0,
            "tfp_earn_rate_limited_total": 0,
            "tfp_earn_replay_rejected_total": 0,
            "tfp_auth_failures_total": 0,
            "tfp_search_index_gossip_received_total": 0,
            "tfp_semantic_search_total": 0,
            "tfp_rag_reindex_total": 0,
            "tfp_rag_drift_detected_total": 0,
        }

    def seed_from_db(self, conn: sqlite3.Connection) -> None:
        """
        Seed durable counters from SQLite so they survive server restarts.

        Only counters that can be derived from persisted data are seeded;
        transient counters (rate_limited, replay_rejected, auth_failures)
        intentionally reset to 0 on restart.
        """
        try:
            tasks_row = conn.execute(
                "SELECT SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),"
                "       SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END),"
                "       COUNT(*) FROM tasks"
            ).fetchone()
            devices_row = conn.execute("SELECT COUNT(*) FROM devices").fetchone()
            supply_row = conn.execute(
                "SELECT total_minted FROM supply_ledger WHERE id = 1"
            ).fetchone()
            content_row = conn.execute("SELECT COUNT(*) FROM content").fetchone()
            results_row = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()
            with self._lock:
                self._counters["tfp_tasks_completed_total"] = tasks_row[0] or 0
                self._counters["tfp_tasks_failed_total"] = tasks_row[1] or 0
                self._counters["tfp_tasks_created_total"] = tasks_row[2] or 0
                self._counters["tfp_devices_enrolled_total"] = devices_row[0] or 0
                self._counters["tfp_credits_minted_total"] = (
                    supply_row[0] if supply_row else 0
                )
                self._counters["tfp_content_published_total"] = content_row[0] or 0
                self._counters["tfp_results_submitted_total"] = results_row[0] or 0
        except Exception as exc:
            log.warning("metrics.seed_from_db failed (non-fatal): %s", exc)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def to_prometheus_text(self) -> str:
        lines = []
        with self._lock:
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Rate limiter — sliding-window token bucket per device
# ---------------------------------------------------------------------------

_EARN_RATE_MAX = int(os.environ.get("TFP_EARN_RATE_MAX", "10"))
_EARN_RATE_WINDOW = int(os.environ.get("TFP_EARN_RATE_WINDOW", "60"))

# Per-device rate limit for task result submissions: default 30 per minute.
# Prevents a single device from spamming the HABP verifier.
_RESULT_RATE_MAX = int(os.environ.get("TFP_RESULT_RATE_MAX", "30"))
_RESULT_RATE_WINDOW = int(os.environ.get("TFP_RESULT_RATE_WINDOW", "60"))


_MAX_RATE_LIMITER_KEYS = 100_000


class _RateLimiter:
    """
    In-memory sliding-window rate limiter.

    Allows at most ``max_calls`` calls per ``window_seconds`` per key.
    Thread-safe by virtue of the GIL on CPython; each bucket is a deque of
    float timestamps that is pruned on every check.

    Bounded to ``_MAX_RATE_LIMITER_KEYS`` tracked keys to prevent memory
    exhaustion from an attacker sending requests with millions of unique keys.
    When the limit is reached, the oldest-accessed buckets are evicted.
    """

    def __init__(
        self, max_calls: int = _EARN_RATE_MAX, window_seconds: int = _EARN_RATE_WINDOW
    ) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: collections.OrderedDict[str, collections.deque] = (
            collections.OrderedDict()
        )

    def is_allowed(self, key: str) -> bool:
        """Return True and record the call, or False if the rate limit is exceeded."""
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            # Evict oldest buckets when at capacity
            while len(self._buckets) >= _MAX_RATE_LIMITER_KEYS:
                self._buckets.popitem(last=False)
            bucket = collections.deque()
            self._buckets[key] = bucket
        else:
            # Move to end (most recently accessed)
            self._buckets.move_to_end(key)
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str) -> None:
        """Clear the bucket for a key (useful in tests)."""
        self._buckets.pop(key, None)


class _RedisRateLimiterAdapter:
    """
    Wraps ``DistributedRateLimiter`` (Redis sliding-window) with the same
    ``is_allowed(key) -> bool`` / ``reset(key)`` interface as ``_RateLimiter``.

    Falls back silently to ``_RateLimiter`` behaviour on any import error or
    Redis connectivity problem (``fail_open=True`` is the default).
    """

    def __init__(
        self,
        redis_url: str,
        max_calls: int,
        window_seconds: int,
        endpoint_type: str,
    ) -> None:
        from tfp_client.lib.rate_limiter import DistributedRateLimiter

        self._endpoint_type = endpoint_type
        self._limiter = DistributedRateLimiter(
            redis_url=redis_url,
            default_limits={endpoint_type: (max_calls, window_seconds)},
            fail_open=True,
        )

    def is_allowed(self, key: str) -> bool:
        result = self._limiter.check_rate_limit(
            client_id=key, endpoint_type=self._endpoint_type
        )
        return result.allowed

    def reset(self, key: str) -> None:
        # Sliding-window Redis counters cannot be instantly reset without
        # deleting the key; that operation is not exposed here.  Acceptable
        # in production since windows expire naturally.
        pass

    def close(self) -> None:
        """Release Redis connection pool (call on shutdown)."""
        try:
            self._limiter.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    tags: List[str] = Field(default_factory=list)
    device_id: str = Field(min_length=1, max_length=120)


class DelegateProofRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    circuit: str = Field(min_length=1, max_length=120)
    private_claim_hex: str = Field(min_length=1)


class EarnRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=256)


class EnrollRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    puf_entropy_hex: str = Field(min_length=64, max_length=64)


class CreateTaskRequest(BaseModel):
    task_type: str = Field(default="hash_preimage")
    difficulty: int = Field(default=3, ge=1, le=10)
    seed_hex: str = Field(default="", max_length=128)


class SubmitResultRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    output_hash: str = Field(min_length=64, max_length=64)  # SHA3-256 hex
    exec_time_s: float = Field(ge=0.0)
    has_tee: bool = Field(default=False)


# ---------------------------------------------------------------------------
# App state (initialised in lifespan)
# ---------------------------------------------------------------------------

_content_store: Optional[ContentStore] = None
_device_registry: Optional[DeviceRegistry] = None
_earn_log: Optional[EarnLog] = None
_credit_store: Optional[CreditStore] = None
_task_store: Optional[TaskStore] = None
_earn_rate_limiter: _RateLimiter = _RateLimiter()
_result_rate_limiter: _RateLimiter = _RateLimiter()
_rag_rate_limiter: _RateLimiter = _RateLimiter(max_calls=20, window_seconds=60)
# Enrollment rate limiter: prevent abuse of the open /api/enroll endpoint.
# Default: 20 enrollments per 60 s per source IP.
_ENROLL_RATE_MAX = int(os.environ.get("TFP_ENROLL_RATE_MAX", "20"))
_ENROLL_RATE_WINDOW = int(os.environ.get("TFP_ENROLL_RATE_WINDOW", "60"))
_enroll_rate_limiter: _RateLimiter = _RateLimiter(
    max_calls=_ENROLL_RATE_MAX, window_seconds=_ENROLL_RATE_WINDOW
)
_tag_overlay: Optional[TagOverlayIndex] = None
_nostr_subscriber: Optional[NostrSubscriber] = None
_nostr_bridge: Optional[NostrBridge] = None
_ipfs_bridge: Optional[IPFSBridge] = None
_broadcaster = Broadcaster()
_clients: Dict[str, TFPClient] = {}
_metrics: _Metrics = _Metrics()
_demo_dir = Path(__file__).resolve().parent.parent / "demo"
_blob_store: Optional[BlobStore] = None
_peer_fallback: Optional["_PeerFallback"] = None  # class defined below
_hlt: Optional[HierarchicalLexiconTree] = None
_peer_secret: str = ""  # TFP_PEER_SECRET shared secret for /api/peer auth
_runtime_mode: str = "demo"  # TFP_MODE=demo|production
_trusted_nostr_pubkeys: frozenset[str] = frozenset()
_admin_device_ids: frozenset[str] = frozenset()
_rag_graph = None  # RAGGraph instance when TFP_ENABLE_RAG=1; Optional[Any]
_chunk_store = None  # ChunkStore for shard-pin reward tracking; Optional[Any]
_gossiped_supply_total: int = (
    0  # Maximum total minted seen from other nodes via Nostr gossip
)
_gossiped_supply_lock: threading.Lock = threading.Lock()

# Event-ID deduplication cache: prevents the same Nostr event from being
# processed more than once within the replay window (e.g., due to relay
# redelivery).  Bounded to 1000 entries; oldest are evicted automatically.
_seen_nostr_event_ids: collections.deque = collections.deque(maxlen=1000)
_seen_nostr_ids_lock: threading.Lock = threading.Lock()

# Readiness gate — set True once lifespan has completed all init steps.
# Exposed here so tests and the /health endpoint can read it directly.
_app_ready: bool = False
_startup_stage: str = "not_started"


# Helper functions for type-narrowed access to Optional globals
def _require_content_store() -> ContentStore:
    """Return content_store, raising 503 if not initialized."""
    if _content_store is None:
        raise HTTPException(status_code=503, detail="Content store not initialized")
    return _content_store


def _require_device_registry() -> DeviceRegistry:
    """Return device_registry, raising 503 if not initialized."""
    if _device_registry is None:
        raise HTTPException(status_code=503, detail="Device registry not initialized")
    return _device_registry


def _require_earn_log() -> EarnLog:
    """Return earn_log, raising 503 if not initialized."""
    if _earn_log is None:
        raise HTTPException(status_code=503, detail="Earn log not initialized")
    return _earn_log


def _require_credit_store() -> CreditStore:
    """Return credit_store, raising 503 if not initialized."""
    if _credit_store is None:
        raise HTTPException(status_code=503, detail="Credit store not initialized")
    return _credit_store


def _require_task_store() -> TaskStore:
    """Return task_store, raising 503 if not initialized."""
    if _task_store is None:
        raise HTTPException(status_code=503, detail="Task store not initialized")
    return _task_store


class DemoNDNAdapter(NDNAdapter):
    def __init__(
        self,
        store: ContentStore,
        ipfs_bridge: Optional[IPFSBridge] = None,
        blob_store: Optional[BlobStore] = None,
        peer_fallback: Optional["_PeerFallback"] = None,
    ):
        self._store = store
        self._ipfs = ipfs_bridge
        self._blob_store = blob_store
        self._peer_fallback = peer_fallback

    def express_interest(self, interest):
        name = interest.name

        # ── Shard interest: /tfp/content/{hash}/shard/{idx} ──────────────
        _shard_prefix = "/shard/"
        if _shard_prefix in name:
            parts = name.split("/")
            try:
                shard_idx = int(parts[-1])
                root_hash = parts[-3]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"malformed shard interest: {name}") from exc
            shard_data = (
                self._blob_store.get_shard(root_hash, shard_idx)
                if self._blob_store
                else None
            )
            if shard_data is not None:
                return Data(name=name, content=shard_data)
            raise ValueError(f"shard not found: {name}")

        # ── Normal content interest ──────────────────────────────────────
        root_hash = name.rsplit("/", 1)[-1]
        item = self._store.get(root_hash)
        if item and item.data:
            return Data(name=name, content=item.data)

        # Resolve CID: prefer durable SQLite record, fall back to in-memory bridge.
        # The SQLite record survives server restarts; the in-memory bridge is
        # populated from Nostr announcements in the current session only.
        cid = None
        if item and item.cid:
            cid = item.cid
        elif self._ipfs:
            cid = self._ipfs.get_cid_for_hash(root_hash)

        if cid and self._ipfs:
            log.info("NDN: Fallback to IPFS for %s (cid=%s)", root_hash, cid)
            data_bytes = self._ipfs.get(cid)
            if data_bytes:
                return Data(name=name, content=data_bytes)

        # ── Peer HTTP fallback ────────────────────────────────────────────
        if self._peer_fallback:
            data_bytes = self._peer_fallback.get(root_hash)
            if data_bytes:
                log.info("NDN: Peer fallback succeeded for %s", root_hash)
                return Data(name=name, content=data_bytes)

        raise ValueError(f"content not found for hash: {root_hash}")


# ---------------------------------------------------------------------------
# Peer HTTP fallback — try sibling nodes when local store misses
# ---------------------------------------------------------------------------


class _PeerFallback:
    """
    HTTP fallback: query configured peer nodes for content blobs.

    Peers are read from ``TFP_PEER_NODES`` (comma-separated URLs) in the
    environment.  Each peer is tried in order; the first successful response
    is returned.  All network errors are swallowed and logged at DEBUG level.

    The peer nodes must expose ``GET /api/peer/{root_hash}`` which returns raw
    bytes without requiring device auth or credits (internal mesh endpoint).
    """

    def __init__(self, peer_urls: List[str], peer_secret: str = "") -> None:
        self._peers = [u.rstrip("/") for u in peer_urls if u.strip()]
        self._secret = peer_secret

    def get(self, root_hash: str) -> Optional[bytes]:
        """Try each configured peer; return raw bytes on first hit, else None."""
        for peer_url in self._peers:
            url = f"{peer_url}/api/peer/{root_hash}"
            try:
                # Validate URL scheme - only allow http/https
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    log.warning("Skipping peer with non-http scheme: %s", url)
                    continue
                req = urllib.request.Request(url)
                if self._secret:
                    req.add_header("X-TFP-Peer-Secret", self._secret)
                with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - URL scheme validated as http/https only, peer URLs from trusted config
                    if resp.status == 200:
                        return resp.read()
            except Exception as exc:
                log.debug(
                    "Peer fallback failed for %s from %s: %s", root_hash, peer_url, exc
                )
        return None


def _make_ndn_adapter() -> NDNAdapter:
    """Return the real NDN adapter when TFP_REAL_ADAPTERS=1, else the demo store adapter."""
    if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
        from tfp_client.lib.ndn.ndn_real import RealNDNAdapter

        return RealNDNAdapter(blob_store=_blob_store)
    return DemoNDNAdapter(_content_store, _ipfs_bridge, _blob_store, _peer_fallback)


def _client_for(device_id: str) -> TFPClient:
    """Return (and cache) a TFPClient for *device_id*, restoring persisted state if available."""
    if device_id not in _clients:
        restored = _credit_store.load(device_id) if _credit_store else None
        if restored is not None:
            # Patch the NDN adapter to point at the current store instance
            restored.ndn = _make_ndn_adapter()
            _clients[device_id] = restored
        else:
            kwargs: dict = {"ndn": _make_ndn_adapter()}
            # Use DictLexiconAdapter for text/dictionary domains; it expands
            # well-known TFP/protocol abbreviations for richer semantic output.
            try:
                from tfp_client.lib.lexicon.dict_lexicon_adapter import (
                    DictLexiconAdapter,
                )

                kwargs["lexicon"] = DictLexiconAdapter()
            except Exception as _lex_exc:
                log.debug("DictLexiconAdapter unavailable, using stub: %s", _lex_exc)
            if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
                from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

                kwargs["raptorq"] = RealRaptorQAdapter()
                kwargs["zkp"] = RealZKPAdapter()
            _clients[device_id] = TFPClient(**kwargs)
    return _clients[device_id]


def _normalize_tags(tags: List[str]) -> List[str]:
    cleaned: List[str] = []
    for tag in tags:
        value = tag.strip().lower()
        if value:
            cleaned.append(value)
    return sorted(set(cleaned))


def _seed_sample() -> None:
    sample = (
        "Welcome to Scholo Radio demo. "
        "This sample content is seeded on startup so anyone can test retrieval in under 60 seconds."
    ).encode()
    result = _broadcaster.seed_content(
        sample, metadata={"title": "Welcome Sample"}, use_ldm=False
    )
    _content_store.put(
        StoredContent(
            root_hash=result["root_hash"],
            title="Welcome Sample",
            tags=["demo", "welcome", "audio"],
            data=sample,
        )
    )


def _preseed_tasks() -> None:
    """Pre-create a small pool of open tasks so devices can join immediately."""
    if _task_store is None:
        return
    _task_store.reap_expired_tasks()
    if _task_store.stats()["open"] >= 5:
        return  # Already have enough open tasks
    seeds = [
        ("hash_preimage", 2, b"tfp-seed-hp-1"),
        ("hash_preimage", 3, b"tfp-seed-hp-2"),
        ("matrix_verify", 2, b"tfp-seed-mv-1"),
        ("matrix_verify", 3, b"tfp-seed-mv-2"),
        ("content_verify", 2, b"tfp-seed-cv-1"),
    ]
    for task_type, difficulty, seed in seeds:
        try:
            _task_store.create_task(task_type, difficulty, seed)
        except Exception as exc:
            log.warning("preseed task %s failed: %s", task_type, exc)


def _verify_nostr_event(event_dict: dict) -> bool:
    """
    Verify a NIP-01 event: recompute the event ID from the canonical
    serialization and check the BIP-340 Schnorr signature.

    Returns False on any structural error or signature mismatch.
    Intentionally strict — invalid events are silently dropped.
    """
    try:
        pubkey = event_dict["pubkey"]
        created_at = event_dict["created_at"]
        kind = event_dict["kind"]
        tags = event_dict["tags"]
        content = event_dict["content"]
        event_id = event_dict["id"]
        sig = event_dict["sig"]

        # Recompute NIP-01 canonical event ID
        serialized = json.dumps(
            [0, pubkey, created_at, kind, tags, content],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        expected_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if expected_id != event_id:
            log.debug(
                "Nostr event ID mismatch: expected=%s, got=%s (kind=%d)",
                expected_id[:16],
                event_id[:16],
                kind,
            )
            return False

        sig_valid = _schnorr_verify(pubkey, event_id, sig)
        if not sig_valid:
            log.debug(
                "Nostr event signature verification failed: id=%s, kind=%d, pubkey=%s",
                event_id[:16],
                kind,
                pubkey[:16],
            )
        
        return sig_valid
    except (KeyError, ValueError, TypeError) as exc:
        log.debug("Nostr event validation error: %s", exc)
        return False


def _cleanup_stale_uploads() -> None:
    """
    Clean up stale upload sessions to prevent memory leaks.
    
    Removes uploads that have been inactive for more than UPLOAD_MAX_AGE_SECONDS.
    Should be called periodically (e.g., by a background task).
    """
    current_time = time.time()
    stale_ids = []
    
    with _uploads_lock:
        for upload_id, upload_data in list(_ongoing_uploads.items()):
            created_at = upload_data.get("created_at", 0)
            age = current_time - created_at
            if age > _UPLOAD_MAX_AGE_SECONDS:
                stale_ids.append(upload_id)
                del _ongoing_uploads[upload_id]
    
    if stale_ids:
        log.info(
            "Cleaned up %d stale upload sessions (older than %ds)",
            len(stale_ids),
            _UPLOAD_MAX_AGE_SECONDS,
        )


def _on_nostr_event(event_dict: dict) -> None:
    """Callback: ingest a remote TFP Nostr announcement into the tag overlay or HLT."""
    try:
        kind = event_dict.get("kind", 1)

        # ── Event-ID deduplication (within-window replay guard) ───────────
        event_id = str(event_dict.get("id", ""))
        if event_id:
            with _seen_nostr_ids_lock:
                if event_id in _seen_nostr_event_ids:
                    log.debug("Dropping duplicate Nostr event id=%s", event_id[:16])
                    return
                _seen_nostr_event_ids.append(event_id)

        # ── Trusted pubkey allowlist ───────────────────────────────────────
        event_pubkey = str(event_dict.get("pubkey", "")).lower()
        if _runtime_mode == "production" and not _trusted_nostr_pubkeys:
            log.debug(
                "Dropping Nostr event in production mode because "
                "TFP_NOSTR_TRUSTED_PUBKEYS is not configured."
            )
            return
        if _trusted_nostr_pubkeys and event_pubkey not in _trusted_nostr_pubkeys:
            log.debug(
                "Dropping Nostr event from untrusted pubkey %s (kind=%s)",
                event_pubkey[:16],
                kind,
            )
            return

        # ── Signature verification (drop forged/tampered events) ──────────
        if not _verify_nostr_event(event_dict):
            log.warning(
                "Dropped Nostr event with invalid id/sig: id=%s kind=%s",
                event_id[:16],
                kind,
            )
            return

        # ── Kind 30078: HLT Merkle-root gossip ────────────────────────────
        if kind == TFP_CONTENT_KIND:
            _handle_hlt_gossip_event(event_dict)
            return

        # ── Kind 30079: semantic search index summary ─────────────────────
        if kind == TFP_SEARCH_INDEX_KIND:
            _handle_search_index_event(event_dict)
            return

        # ── Kind 30081: supply ledger gossip for multi-node coordination ────
        if kind == 30081:
            _handle_supply_gossip_event(event_dict)
            return

        # ── Kind 30080: content-availability announcement ─────────────────
        if kind != TFP_CONTENT_ANNOUNCE_KIND:
            log.debug("Ignoring unknown Nostr event kind %d", kind)
            return

        if not _check_replay_window(event_dict):
            return

        payload = json.loads(event_dict.get("content", "{}"))
        content_hash_hex = payload.get("hash", "")
        tags = payload.get("tags", [])
        cid = payload.get("cid")

        if content_hash_hex and len(content_hash_hex) == 64:
            if cid and _ipfs_bridge:
                metadata = {
                    "title": payload.get("title", "Remote Content"),
                    "tags": tags,
                }
                _ipfs_bridge.record_mapping(content_hash_hex, cid, metadata=metadata)

            # Persist the CID durably so IPFS fallback survives server restarts.
            if cid and _content_store is not None:
                _content_store.put_cid_mapping(content_hash_hex, cid)

            content_hash_bytes = bytes.fromhex(content_hash_hex)
            domain = payload.get("domain", "general")
            _tag_overlay.add_entry(
                domain=domain,
                tags=tags if tags else ["nostr"],
                content_hash=content_hash_bytes,
                popularity=0.5,
            )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        log.warning("Failed to process Nostr event: %s", e)


# Maximum age (seconds) accepted for gossip events.  Events outside this
# window are silently dropped to prevent replay-based index/HLT poisoning.
_NOSTR_REPLAY_WINDOW_S: int = 300  # 5 minutes


def _check_replay_window(event_dict: dict) -> bool:
    """Return True if the event's ``created_at`` is within the replay window."""
    try:
        created_at = int(event_dict.get("created_at", 0))
        age = int(time.time()) - created_at
        if abs(age) > _NOSTR_REPLAY_WINDOW_S:
            log.debug(
                "Dropping Nostr event (kind=%s): age=%ds exceeds replay window=%ds.",
                event_dict.get("kind"),
                age,
                _NOSTR_REPLAY_WINDOW_S,
            )
            return False
        return True
    except (TypeError, ValueError):
        return False


def _handle_supply_gossip_event(event_dict: dict) -> None:
    """
    Handle a kind-30081 supply ledger gossip event.

    Updates the local gossiped supply total with the maximum value seen
    from other nodes to prevent supply cap bypass across the network.
    """
    global _gossiped_supply_total
    try:
        payload = json.loads(event_dict.get("content", "{}"))
        total_minted = payload.get("total_minted")
        # Validate: must be int within valid range [0, MAX_SUPPLY]
        if isinstance(total_minted, int) and 0 <= total_minted <= MAX_SUPPLY:
            # Additional validation: reject implausibly high values
            # Must be within reasonable buffer of our local total
            local_total = _task_store.get_total_minted() if _task_store else 0
            max_plausible = local_total + 10000  # Allow for network concurrency
            if total_minted > max_plausible:
                log.warning(
                    "Rejecting suspicious supply gossip: %d > local %d + buffer (from pubkey=%s)",
                    total_minted,
                    local_total,
                    event_dict.get("pubkey", "")[:16],
                )
                return
            with _gossiped_supply_lock:
                if total_minted > _gossiped_supply_total:
                    log.info(
                        "Updated gossiped supply total: %d -> %d (from pubkey=%s)",
                        _gossiped_supply_total,
                        total_minted,
                        event_dict.get("pubkey", "")[:16],
                    )
                    _gossiped_supply_total = total_minted
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        log.warning("Failed to parse supply gossip event: %s", exc)


def _handle_hlt_gossip_event(event_dict: dict) -> None:
    """
    Handle a NIP-78 kind-30078 HLT Merkle-root gossip event.

    If the event announces domains that are absent from our local HLT state,
    add them so that semantic drift is prevented across nodes.

    Wire format: ``{"merkle_root": <hex>, "domains": [{"domain": <name>,
    "version": <ver>, "content_hash": <hex>}, ...]}``
    """
    if _hlt is None:
        return
    try:
        if not _check_replay_window(event_dict):
            return
        payload = json.loads(event_dict.get("content", "{}"))
        # Collect domain tags from event tags array (for tag-based discovery)
        domain_tags = [
            t[1] for t in event_dict.get("tags", []) if len(t) >= 2 and t[0] == "t"
        ]
        domains = payload.get("domains", [])
        for entry in domains:
            if not isinstance(entry, dict):
                continue
            domain = entry.get("domain")
            version = entry.get("version", "v1.0.0")
            content_hash = entry.get("content_hash", "a" * 64)
            if domain and not _hlt.has_domain(domain):
                _hlt.add_domain(domain, version, content_hash, tags=domain_tags)
                log.info("HLT: added domain %r v%s from Nostr gossip", domain, version)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        log.warning("Failed to process HLT gossip event: %s", exc)


# _SEARCH_INDEX_REPLAY_WINDOW_S retained for backwards compatibility; the shared
# _NOSTR_REPLAY_WINDOW_S constant is now used by all three handlers.
_SEARCH_INDEX_REPLAY_WINDOW_S: int = _NOSTR_REPLAY_WINDOW_S


def _handle_search_index_event(event_dict: dict) -> None:
    """
    Handle a NIP-78 kind-30079 semantic search index summary gossip event.

    Verifies:
    1. ``created_at`` is within ``_NOSTR_REPLAY_WINDOW_S`` of now
       (replay-window guard prevents stale/replayed index poisoning).
    2. Required fields (``domain``, ``index_hash``, ``chunk_count``,
       ``schema_version``) are present and well-formed.

    On success, logs the peer index summary so the operator can detect
    nodes whose local RAG index has drifted from the network median.
    Increments ``tfp_rag_drift_detected_total`` when significant drift is found.
    """
    try:
        if not _check_replay_window(event_dict):
            return

        payload = json.loads(event_dict.get("content", "{}"))
        domain = payload.get("domain", "")
        index_hash = payload.get("index_hash", "")
        chunk_count = int(payload.get("chunk_count", 0))
        schema_version = str(payload.get("schema_version", "1"))
        pubkey = event_dict.get("pubkey", "")

        if not domain or not index_hash or len(index_hash) not in (64,):
            log.debug(
                "Ignoring malformed search-index gossip: domain=%r index_hash=%r",
                domain,
                index_hash,
            )
            return

        log.info(
            "Search-index gossip received: peer=%s… domain=%r chunks=%d "
            "hash=%s… schema_v=%s",
            pubkey[:16] if pubkey else "?",
            domain,
            chunk_count,
            index_hash[:16],
            schema_version,
        )
        _metrics.inc("tfp_search_index_gossip_received_total")

        # If we have a local RAG graph, compare index hashes to detect drift.
        if _rag_graph is not None:
            try:
                local_stats = _rag_graph.get_stats()
                local_chunks = local_stats.get("total_chunks", 0)
                if local_chunks == 0:
                    log.debug(
                        "Local RAG index is empty; peer has %d chunks for %r.",
                        chunk_count,
                        domain,
                    )
                elif abs(local_chunks - chunk_count) > max(10, local_chunks * 0.20):
                    log.warning(
                        "RAG index drift detected: local=%d chunks, peer=%d "
                        "chunks for domain=%r.  Consider triggering reindex.",
                        local_chunks,
                        chunk_count,
                        domain,
                    )
                    _metrics.inc("tfp_rag_drift_detected_total")
            except Exception as exc:
                log.debug("Could not compare RAG stats: %s", exc)

    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        log.warning("Failed to process search-index gossip event: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Phase A: per-stage startup observability + readiness gate.
    # Phase B: feature flags read at runtime so tests can use monkeypatch.setenv.
    global _content_store, _device_registry, _earn_log, _credit_store, _task_store
    global \
        _earn_rate_limiter, \
        _result_rate_limiter, \
        _rag_rate_limiter, \
        _enroll_rate_limiter, \
        _tag_overlay, \
        _nostr_subscriber
    global _nostr_bridge, _ipfs_bridge, _clients, _metrics, _app_ready, _startup_stage
    global _blob_store, _peer_fallback, _hlt, _peer_secret, _rag_graph, _chunk_store
    global _runtime_mode, _trusted_nostr_pubkeys, _admin_device_ids
    global _gossiped_supply_total

    _app_ready = False
    _startup_stage = "starting"
    log.info("TFP Server starting up... (stage=%s)", _startup_stage)

    # Read runtime mode + config at startup (not import-time) so tests can
    # override env vars with monkeypatch.setenv before TestClient starts.
    runtime_cfg = validate_runtime_config(
        os.environ,
        default_db_path=str(_DEFAULT_DB_PATH),
    )
    _runtime_mode = runtime_cfg.mode
    _trusted_nostr_pubkeys = runtime_cfg.nostr_trusted_pubkeys
    _admin_device_ids = runtime_cfg.admin_device_ids
    if _runtime_mode == "production" and not _trusted_nostr_pubkeys:
        log.warning(
            "Production mode started without TFP_NOSTR_TRUSTED_PUBKEYS; "
            "inbound Nostr gossip is deny-by-default until an allowlist is configured."
        )

    # Read feature flags at runtime (not module-import time).
    _enable_ipfs = os.environ.get("TFP_ENABLE_IPFS", "1").strip() != "0"
    _enable_nostr = runtime_cfg.enable_nostr
    _enable_maintenance = os.environ.get("TFP_ENABLE_MAINTENANCE", "1").strip() != "0"
    _enable_rag = os.environ.get("TFP_ENABLE_RAG", "0").strip() != "0"
    log.info(
        "Runtime mode=%s  Feature flags: IPFS=%s  Nostr=%s  Maintenance=%s  RAG=%s",
        _runtime_mode,
        _enable_ipfs,
        _enable_nostr,
        _enable_maintenance,
        _enable_rag,
    )

    try:
        # ── Stage: db_init ────────────────────────────────────────────────
        _startup_stage = "db_init"
        db_path = runtime_cfg.db_path

        # Initialize Database abstraction (SQLite or PostgreSQL)
        global _db
        _db = get_database_from_env()
        log.info(
            "Database initialized: %s (multi-worker: %s)",
            _db.db_type,
            _db.supports_multiple_workers,
        )

        # Warn if PostgreSQL is used - stores are SQLite-specific
        if _db.is_postgresql:
            log.warning(
                "⚠️ PostgreSQL connection established, but store classes use SQLite-specific SQL. "
                "Full PostgreSQL support requires store refactoring (sqlite_master, PRAGMA, INSERT OR REPLACE, rowid). "
                "Use SQLite for production deployments. "
                "See SECURITY.md L4 for details."
            )

        # For backward compatibility with stores (RLock for thread safety)
        _conn = _db.get_underlying_connection()
        _db_lock = threading.RLock()

        # ── BlobStore: filesystem for file-backed DB, in-memory for :memory: ──
        _tmp_blob_dir: Optional[str] = None
        if db_path != ":memory:":
            blob_dir_env = os.environ.get("TFP_BLOB_DIR", "")
            if blob_dir_env:
                _bs_path = Path(blob_dir_env)
            else:
                # Derive blob dir from DB path: /data/pib.db → /data/pib.blobs/
                _bs_path = Path(db_path).with_suffix(".blobs")
            _bs_path.mkdir(parents=True, exist_ok=True)
            _blob_store = BlobStore(_bs_path)
            log.info("BlobStore: filesystem at %s", _bs_path)
        else:
            # :memory: mode — use in-memory BlobStore (tests, dev)
            _blob_store = BlobStore(None)
            log.info("BlobStore: in-memory (TFP_DB_PATH=:memory:)")

        # ── Peer secret: TFP_PEER_SECRET ─────────────────────────────────
        _peer_secret = runtime_cfg.peer_secret
        if _peer_secret:
            log.info("Peer secret configured (X-TFP-Peer-Secret enforcement enabled).")
        else:
            log.info(
                "TFP_PEER_SECRET not set; /api/peer endpoint is unauthenticated. "
                "Set TFP_PEER_SECRET for production deployments."
            )
        if _admin_device_ids:
            log.info(
                "Admin allowlist configured with %d device(s).", len(_admin_device_ids)
            )
        elif _runtime_mode == "production":
            # Should already be blocked by config_validation; keep explicit log guard.
            log.warning("Production mode without TFP_ADMIN_DEVICE_IDS is not allowed.")

        # ── Peer fallback: read TFP_PEER_NODES env var ────────────────────
        peer_nodes_env = os.environ.get("TFP_PEER_NODES", "")
        _peer_urls = [u.strip() for u in peer_nodes_env.split(",") if u.strip()]
        _peer_fallback = _PeerFallback(_peer_urls, peer_secret=_peer_secret)
        if _peer_urls:
            log.info("Peer fallback configured: %s", _peer_urls)

        # ── Hierarchical Lexicon Tree ─────────────────────────────────────
        _hlt = HierarchicalLexiconTree()
        log.info("HLT initialised (root node)")

        _content_store = ContentStore(_conn, _db_lock, blob_store=_blob_store)
        _device_registry = DeviceRegistry(_conn, _db_lock)
        _earn_log = EarnLog(_conn, _db_lock)
        _credit_store = CreditStore(_conn, _db_lock)
        _task_store = TaskStore(_conn, _db_lock)

        # ── Rate limiters: Redis-backed when TFP_REDIS_URL is set ─────────
        _redis_url = os.environ.get("TFP_REDIS_URL", "").strip()
        if _redis_url:
            try:
                _earn_rate_limiter = _RedisRateLimiterAdapter(
                    redis_url=_redis_url,
                    max_calls=_EARN_RATE_MAX,
                    window_seconds=_EARN_RATE_WINDOW,
                    endpoint_type="earn",
                )
                _result_rate_limiter = _RedisRateLimiterAdapter(
                    redis_url=_redis_url,
                    max_calls=_RESULT_RATE_MAX,
                    window_seconds=_RESULT_RATE_WINDOW,
                    endpoint_type="task_submit",
                )
                _rag_rate_limiter = _RedisRateLimiterAdapter(
                    redis_url=_redis_url,
                    max_calls=20,
                    window_seconds=60,
                    endpoint_type="rag_search",
                )
                _enroll_rate_limiter = _RedisRateLimiterAdapter(
                    redis_url=_redis_url,
                    max_calls=_ENROLL_RATE_MAX,
                    window_seconds=_ENROLL_RATE_WINDOW,
                    endpoint_type="enroll",
                )
                log.info("Rate limiters: Redis-backed (%s)", _redis_url)
            except Exception as exc:
                log.warning(
                    "Redis rate limiter init failed (%s); falling back to "
                    "in-memory rate limiters.  Multi-worker deployments will "
                    "not share rate-limit state until Redis is available: %s",
                    _redis_url,
                    exc,
                )
                _earn_rate_limiter = _RateLimiter(
                    max_calls=_EARN_RATE_MAX, window_seconds=_EARN_RATE_WINDOW
                )
                _result_rate_limiter = _RateLimiter(
                    max_calls=_RESULT_RATE_MAX, window_seconds=_RESULT_RATE_WINDOW
                )
                _rag_rate_limiter = _RateLimiter(max_calls=20, window_seconds=60)
                _enroll_rate_limiter = _RateLimiter(
                    max_calls=_ENROLL_RATE_MAX, window_seconds=_ENROLL_RATE_WINDOW
                )
        else:
            _earn_rate_limiter = _RateLimiter(
                max_calls=_EARN_RATE_MAX, window_seconds=_EARN_RATE_WINDOW
            )
            _result_rate_limiter = _RateLimiter(
                max_calls=_RESULT_RATE_MAX, window_seconds=_RESULT_RATE_WINDOW
            )
            _rag_rate_limiter = _RateLimiter(max_calls=20, window_seconds=60)
            _enroll_rate_limiter = _RateLimiter(
                max_calls=_ENROLL_RATE_MAX, window_seconds=_ENROLL_RATE_WINDOW
            )
            log.info(
                "Rate limiters: in-memory (set TFP_REDIS_URL for distributed "
                "limiting required before enabling --workers > 1)."
            )

        # ── Shard size sanity guard ───────────────────────────────────────
        _shard_size_kb = int(os.environ.get("TFP_SHARD_SIZE_KB", "0"))
        _chunking_enabled = os.environ.get("TFP_ENABLE_CHUNKING", "1").strip() != "0"
        if _chunking_enabled and 0 < _shard_size_kb < 64:
            log.warning(
                "TFP_SHARD_SIZE_KB=%d is below 64 KB with TFP_ENABLE_CHUNKING=1.  "
                "For audio/video workloads set TFP_SHARD_SIZE_KB to 256–2048 to "
                "avoid excessive shard counts and poor streaming performance.",
                _shard_size_kb,
            )

        # ── ChunkStore for shard-pin economics ────────────────────────────
        try:
            from tfp_client.lib.cache.chunk_store import ChunkStore as _ChunkStore

            _chunk_store = _ChunkStore(max_chunks=10_000, max_bytes=256 * 1024 * 1024)
            log.info("ChunkStore initialised (shard-pin reward tracking active).")
        except Exception as exc:
            log.warning("ChunkStore init failed (pin rewards disabled): %s", exc)
            _chunk_store = None

        _metrics = _Metrics()
        _metrics.seed_from_db(_conn)
        log.info("DB init complete.")

        # ── Stage: seed_content ───────────────────────────────────────────
        _startup_stage = "seed_content"
        _tag_overlay = TagOverlayIndex()
        # Restore persisted tag overlay (Nostr-discovered announcements survive restart).
        if db_path != ":memory:":
            _overlay_path = Path(db_path).parent / "tag_overlay.json"
            if _overlay_path.exists():
                try:
                    _tag_overlay = TagOverlayIndex.from_json(
                        _overlay_path.read_text(encoding="utf-8")
                    )
                    log.info(
                        "TagOverlayIndex restored from %s (%d domains).",
                        _overlay_path,
                        len(_tag_overlay._storage),
                    )
                except Exception as exc:
                    log.warning(
                        "Could not restore TagOverlayIndex from %s: %s",
                        _overlay_path,
                        exc,
                    )
                    _tag_overlay = TagOverlayIndex()
        _clients.clear()
        if _content_store.count() == 0:
            _seed_sample()
        _preseed_tasks()
        log.info("Content/task seeding complete.")

        # ── Stage: maintenance ────────────────────────────────────────────
        _startup_stage = "maintenance"
        _stop_maintenance = threading.Event()

        def _maintenance_loop() -> None:
            global _last_cleanup_time
            while not _stop_maintenance.wait(timeout=30):
                try:
                    if _task_store is not None:
                        _task_store.reap_expired_tasks()
                        _preseed_tasks()

                    # Publish supply gossip for multi-node coordination
                    if _nostr_bridge and _task_store:
                        from tfp_client.lib.credit.ledger import MAX_SUPPLY

                        current_total = _task_store.get_total_minted()
                        _nostr_bridge.publish_supply_gossip(current_total, MAX_SUPPLY)

                    # Periodic cleanup of stale uploads
                    current_time = time.time()
                    if current_time - _last_cleanup_time >= _UPLOAD_CLEANUP_INTERVAL_SECONDS:
                        _cleanup_stale_uploads()
                        _last_cleanup_time = current_time
                except Exception as exc:
                    log.warning("maintenance loop error: %s", exc)

        if _enable_maintenance:
            _maint_thread = threading.Thread(
                target=_maintenance_loop, name="tfp-maintenance", daemon=True
            )
            _maint_thread.start()
            log.info("Maintenance thread started.")
        else:
            log.info("Maintenance thread disabled (TFP_ENABLE_MAINTENANCE=0).")

        # ── Stage: ipfs_init ──────────────────────────────────────────────
        _startup_stage = "ipfs_init"
        if _enable_ipfs:
            ipfs_api = os.environ.get("TFP_IPFS_API_URL", "http://tfp-ipfs:5001")
            _ipfs_bridge = IPFSBridge(api_url=ipfs_api, offline=not ipfs_api)
            _broadcaster.ipfs_bridge = _ipfs_bridge
            log.info(
                "IPFS bridge initialised (api=%s, offline=%s).", ipfs_api, not ipfs_api
            )
        else:
            _ipfs_bridge = None
            _broadcaster.ipfs_bridge = None
            log.info("IPFS bridge disabled (TFP_ENABLE_IPFS=0).")

        # ── Stage: nostr_init ─────────────────────────────────────────────
        _startup_stage = "nostr_init"
        if _enable_nostr:
            relay_url = os.environ.get("NOSTR_RELAY") or os.environ.get(
                "NOSTR_RELAY_URL", ""
            )

            # Optional persistent Nostr identity key.  When set, the same
            # pubkey is used across restarts so that peer nodes can build
            # stable trust records.  When unset, a random ephemeral key is
            # generated (safe for development / single-restart deployments).
            nostr_privkey: Optional[bytes] = None
            nostr_key_env = os.environ.get("NOSTR_PRIVATE_KEY", "").strip()
            if nostr_key_env:
                try:
                    nostr_privkey = bytes.fromhex(nostr_key_env)
                    if len(nostr_privkey) != 32:
                        raise ValueError(
                            f"expected 32 bytes (64 hex chars), got {len(nostr_privkey)}"
                        )
                    log.info(
                        "Nostr: loaded persistent private key from NOSTR_PRIVATE_KEY."
                    )
                except ValueError as key_exc:
                    log.warning(
                        "NOSTR_PRIVATE_KEY is invalid (%s); using random ephemeral key.",
                        key_exc,
                    )
                    nostr_privkey = None
            else:
                log.debug(
                    "NOSTR_PRIVATE_KEY not set; Nostr identity is ephemeral "
                    "(new pubkey each restart)."
                )

            # TFP_NOSTR_PUBLISH_ENABLED=0/false lets operators run receive-only
            # (air-gapped) nodes: events are still subscribed and ingested but
            # no outbound gossip is sent.
            publish_enabled = runtime_cfg.nostr_publish_enabled

            _nostr_subscriber = NostrSubscriber(
                relay_url=relay_url or "wss://relay.damus.io",
                on_event=_on_nostr_event,
                offline=not relay_url,
                filters={
                    "kinds": [
                        TFP_CONTENT_KIND,
                        TFP_SEARCH_INDEX_KIND,
                        TFP_CONTENT_ANNOUNCE_KIND,
                        30081,  # supply ledger gossip for multi-node coordination
                    ]
                },
            )
            _nostr_subscriber.start()
            bridge_offline = (not relay_url) or (not publish_enabled)
            _nostr_bridge = NostrBridge(
                privkey=nostr_privkey,
                relay_url=relay_url or "wss://relay.damus.io",
                offline=bridge_offline,
            )
            log.info(
                "Nostr initialised (relay=%s, offline=%s, publish=%s).",
                relay_url or "wss://relay.damus.io",
                bridge_offline,
                publish_enabled,
            )
        else:
            _nostr_subscriber = None
            _nostr_bridge = None
            log.info("Nostr disabled (TFP_ENABLE_NOSTR=0).")

        # ── Stage: rag_init (optional) ────────────────────────────────────
        if _enable_rag:
            try:
                from tfp_client.lib.rag_search import RAGGraph

                rag_dir = os.environ.get("TFP_RAG_DIR", "./rag_storage")
                _rag_graph = RAGGraph(persist_directory=rag_dir)
                log.info("RAG search enabled (persist_dir=%s).", rag_dir)
            except ImportError as exc:
                log.warning(
                    "TFP_ENABLE_RAG=1 but required dependencies missing (%s). "
                    "Install chromadb and transformers to enable semantic search.",
                    exc,
                )
                _rag_graph = None
        else:
            _rag_graph = None
            log.info("RAG search disabled (set TFP_ENABLE_RAG=1 to enable).")

        # ── Stage: ready ──────────────────────────────────────────────────
        _startup_stage = "ready"
        _app_ready = True
        log.info("TFP Server ready and yielding.")

        yield

    except Exception as e:
        import traceback

        err_msg = (
            f"CRITICAL: Lifespan failed at stage={_startup_stage!r}: {e}\n"
            f"{traceback.format_exc()}"
        )
        log.error(err_msg)
        # Write crash artifact to a discoverable path.
        # Prefer <DB-dir>/crash.log; fall back to temp directory (secure).
        _db_path_env = os.environ.get("TFP_DB_PATH", "")
        if _db_path_env and _db_path_env != ":memory:":
            _crash_log = str(Path(_db_path_env).parent / "crash.log")
        else:
            # Use tempfile module for secure temporary file handling
            import tempfile

            _crash_log = os.environ.get(
                "TFP_CRASH_LOG", os.path.join(tempfile.gettempdir(), "tfp_crash.log")
            )
        try:
            with open(_crash_log, "a") as crash_file:
                crash_file.write(f"\n--- {time.ctime()} ---\n{err_msg}\n")
        except Exception:
            pass
        raise e
    finally:
        log.info("TFP Server shutting down...")
        _app_ready = False
        _startup_stage = "shutdown"
        try:
            if "_stop_maintenance" in locals():
                _stop_maintenance.set()
            if "_nostr_subscriber" in locals() and _nostr_subscriber:
                _nostr_subscriber.stop()
            # Persist tag overlay (Nostr-discovered announcements) to disk.
            _to_db_path = os.environ.get("TFP_DB_PATH", "")
            if _to_db_path and _to_db_path != ":memory:" and _tag_overlay is not None:
                try:
                    _overlay_save_path = Path(_to_db_path).parent / "tag_overlay.json"
                    _overlay_save_path.write_text(
                        _tag_overlay.to_json(), encoding="utf-8"
                    )
                    log.info("TagOverlayIndex persisted to %s.", _overlay_save_path)
                except Exception as exc:
                    log.warning("Could not persist TagOverlayIndex: %s", exc)
            if "_db" in locals() and _db:
                _db.close()
            # Close Redis connections if distributed limiters were in use.
            for _lim in (
                _earn_rate_limiter,
                _result_rate_limiter,
                _rag_rate_limiter,
                _enroll_rate_limiter,
            ):
                if hasattr(_lim, "close"):
                    try:
                        _lim.close()
                    except Exception:
                        pass
        except Exception:
            pass
        _content_store = None
        _device_registry = None
        _earn_log = None
        _credit_store = None
        _task_store = None
        _tag_overlay = None
        _nostr_subscriber = None
        _nostr_bridge = None
        _blob_store = None
        _peer_fallback = None
        _hlt = None
        _rag_graph = None
        _chunk_store = None
        _peer_secret = ""
        _runtime_mode = "demo"
        _trusted_nostr_pubkeys = frozenset()
        _admin_device_ids = frozenset()


app = FastAPI(title="TFP Demo Node", version="3.1.1", lifespan=lifespan)

# CORS configuration.
# Set TFP_CORS_ORIGINS to a comma-separated list of allowed origins for
# production deployments (e.g. "https://app.example.com,https://admin.example.com").
# When unset, all origins are allowed (demo / development default).
# Note: allow_credentials=True requires explicit origins — browsers reject the
# wildcard + credentials combination, so credentials are disabled with wildcard.
_cors_origins_env = os.environ.get("TFP_CORS_ORIGINS", "").strip()
if _cors_origins_env and _cors_origins_env != "*":
    _cors_origins: list[str] = [
        o.strip() for o in _cors_origins_env.split(",") if o.strip()
    ]
    _cors_credentials = True
else:
    _cors_origins = ["*"]
    _cors_credentials = False  # credentials + wildcard is invalid per CORS spec

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "ready": _app_ready,
        "startup_stage": _startup_stage,
        "content_items": _content_store.count() if _content_store is not None else 0,
    }


@app.post("/api/upload/chunk/{upload_id}/{chunk_index}")
async def upload_chunk(upload_id: str, chunk_index: int, request: Request):
    """
    Upload a single chunk for a parallel upload session.
    
    Chunks are stored in memory until the upload is completed via /api/upload/complete.
    """
    _validate_hash_component(upload_id)
    
    # Read chunk data
    chunk_data = await request.body()
    if not chunk_data:
        raise HTTPException(status_code=400, detail="Empty chunk data")
    
    with _uploads_lock:
        if upload_id not in _ongoing_uploads:
            _ongoing_uploads[upload_id] = {
                "chunks": {},
                "total_chunks": 0,
                "created_at": time.time(),
            }
        
        _ongoing_uploads[upload_id]["chunks"][chunk_index] = chunk_data
        log.debug(
            "Received chunk %d for upload %s (total chunks: %d)",
            chunk_index,
            upload_id,
            len(_ongoing_uploads[upload_id]["chunks"]),
        )
    
    return {"status": "uploaded", "chunk_index": chunk_index, "upload_id": upload_id}


@app.post("/api/upload/complete/{upload_id}")
async def complete_upload(upload_id: str, metadata: dict = None):
    """
    Complete a parallel upload by reassembling chunks and publishing the content.
    
    Args:
        upload_id: Unique identifier for the upload session
        metadata: Optional metadata dict with title, tags, etc.
    
    Returns:
        Published content information including root_hash
    """
    _validate_hash_component(upload_id)
    
    with _uploads_lock:
        if upload_id not in _ongoing_uploads:
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        upload_data = _ongoing_uploads[upload_id]
        chunks_dict = upload_data["chunks"]
        
        if not chunks_dict:
            raise HTTPException(status_code=400, detail="No chunks uploaded")
        
        # Reassemble chunks in order
        sorted_indices = sorted(chunks_dict.keys())
        full_content = b"".join(chunks_dict[i] for i in sorted_indices)
        
        # Clean up upload session
        del _ongoing_uploads[upload_id]
    
    # Publish the reassembled content using the existing publish flow
    # For now, we'll return the content hash. In a full implementation,
    # this would call the publish logic with proper device authentication.
    content_hash = hashlib.sha3_256(full_content).hexdigest()
    
    log.info(
        "Completed upload %s: %d chunks, %d bytes, hash=%s",
        upload_id,
        len(sorted_indices),
        len(full_content),
        content_hash[:16],
    )
    
    return {
        "status": "completed",
        "upload_id": upload_id,
        "root_hash": content_hash,
        "chunk_count": len(sorted_indices),
        "size_bytes": len(full_content),
    }


@app.get("/")
def demo_page():
    return FileResponse(_demo_dir / "index.html")


@app.get("/manifest.json")
def manifest():
    return FileResponse(
        _demo_dir / "manifest.json", media_type="application/manifest+json"
    )


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(
        _demo_dir / "service-worker.js", media_type="application/javascript"
    )


@app.get("/api/content")
def search_content(
    tag: str | None = Query(default=None, min_length=1),
    tags: str | None = Query(
        default=None, description="Comma-separated tags (union match)"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    Search or list published content.

    - ``tag`` — filter by a single tag (exact, case-insensitive)
    - ``tags`` — comma-separated list of tags, returns items matching **any** tag (union)
    - ``limit`` / ``offset`` — pagination; response includes ``total``

    If both ``tag`` and ``tags`` are supplied, ``tags`` takes precedence.
    """
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        items = _content_store.filter_by_tags(tag_list, limit=limit, offset=offset)
        total = _content_store.count_tags(tag_list)
    elif tag:
        t = tag.strip().lower()
        items = _content_store.filter_by_tag(t, limit=limit, offset=offset)
        total = _content_store.count_tag(t)
    else:
        items = _content_store.all(limit=limit, offset=offset)
        total = _content_store.count()
    return {
        "items": [
            {"root_hash": item.root_hash, "title": item.title, "tags": item.tags}
            for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/enroll")
def enroll(payload: EnrollRequest, request: Request) -> dict:
    # Rate-limit enrollment by client IP to prevent mass device registration.
    client_ip = request.client.host if request.client else "unknown"
    if not _enroll_rate_limiter.is_allowed(client_ip):
        _metrics.inc("tfp_enroll_rate_limited_total")
        raise HTTPException(
            status_code=429,
            detail=(
                f"enrollment rate limit exceeded — max {_ENROLL_RATE_MAX} "
                f"enrollments per {_ENROLL_RATE_WINDOW}s per IP"
            ),
        )
    try:
        puf_entropy = bytes.fromhex(payload.puf_entropy_hex)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="puf_entropy_hex must be valid hex"
        ) from exc
    _device_registry.enroll(payload.device_id, puf_entropy)
    _metrics.inc("tfp_devices_enrolled_total")
    return {"enrolled": True, "device_id": payload.device_id}


@app.post("/api/publish")
async def publish(
    request: Request,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        try:
            payload = PublishRequest(**body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        device_id = payload.device_id
        title = payload.title
        tags_raw = payload.tags
        body_bytes = payload.text.encode()
    elif "multipart/form-data" in content_type:
        form = await request.form()
        device_id = form.get("device_id")
        title = form.get("title")
        tags_str = form.get("tags", "")
        tags_raw = [t.strip() for t in tags_str.split(",")] if tags_str else []
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Missing file")
        body_bytes = await file.read()
    else:
        raise HTTPException(status_code=415, detail="Unsupported Media Type")

    message = f"{device_id}:{title}"
    if not _verify_device_sig(device_id, x_device_sig, message, _device_registry):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )

    result = _broadcaster.seed_content(
        body_bytes, metadata={"title": title, "tags": tags_raw}, use_ldm=False
    )
    tags = _normalize_tags(tags_raw)
    root_hash: str = result["root_hash"]

    # ── Recipe / chunking pipeline (TFP_ENABLE_CHUNKING, default=1) ──────
    recipe_json: Optional[str] = None
    recipe_dict: Optional[dict] = None
    _enable_chunking = os.environ.get("TFP_ENABLE_CHUNKING", "1").strip() != "0"
    if _enable_chunking and _blob_store is not None and len(body_bytes) > 0:
        try:
            recipe_json, recipe_dict = _build_recipe(
                root_hash, body_bytes, tags, _blob_store
            )
        except Exception as exc:
            log.warning(
                "Recipe build failed (content will be served without recipe): %s", exc
            )

    # Ensure IPFS CID is included in the Nostr announcement
    if result.get("cid") and _nostr_bridge:
        _nostr_bridge.publish_content_announcement(
            root_hash,
            metadata={"title": title, "tags": tags, "cid": result["cid"]},
        )
    _content_store.put(
        StoredContent(
            root_hash=root_hash,
            title=title,
            tags=tags,
            data=body_bytes,
            cid=result.get("cid"),
            recipe_json=recipe_json,
        )
    )
    _metrics.inc("tfp_content_published_total")
    return {
        "root_hash": root_hash,
        "title": title,
        "tags": tags,
        "status": "broadcasting",
        "recipe": recipe_dict,
    }


def _build_recipe(
    root_hash: str,
    data: bytes,
    tags: List[str],
    blob_store: BlobStore,
) -> tuple:
    """
    Encode *data* into RaptorQ shards, write each shard to *blob_store*, and
    return ``(recipe_json_str, recipe_dict)`` for storage and HTTP response.

    The ``Recipe`` object follows the TFP content-addressable model:
    - ``content_hash``: SHA3-256 of the raw content (root_hash)
    - ``template_id``: same as content_hash (content IS the template)
    - ``chunk_ids``: SHA3-256 of the raw shard payload (source shards only)
    - ``ai_adapter``: first tag or "general" (domain hint for LexiconAdapter)
    """
    # Configurable shard size: TFP_SHARD_SIZE_KB * 1024 bytes, or codec default
    shard_size_kb = int(os.environ.get("TFP_SHARD_SIZE_KB", "0"))
    if shard_size_kb > 0:
        encoder = RealRaptorQAdapter(shard_size=shard_size_kb * 1024)
    else:
        encoder = RealRaptorQAdapter()

    shards = encoder.encode(data, redundancy=0.10)
    if not shards:
        raise ValueError("RaptorQ encode produced no shards")

    # Decode k (number of source blocks) from the first shard header
    import struct

    _orig_len, k, _idx = struct.unpack(">QII", shards[0][:16])

    chunk_ids: List[str] = []
    for idx, shard_bytes in enumerate(shards):
        blob_store.put_shard(root_hash, idx, shard_bytes)
        if idx < k:
            # chunk_id = SHA3-256 of the shard payload (bytes after 16-byte header)
            payload = shard_bytes[16:]
            chunk_ids.append(hashlib.sha3_256(payload).hexdigest())

    ai_adapter = tags[0] if tags else "general"
    recipe = Recipe(
        content_hash=root_hash,
        template_id=root_hash,
        chunk_ids=chunk_ids,
        ai_adapter=ai_adapter,
    )
    recipe_dict = recipe.to_dict()
    recipe_json = json.dumps(recipe_dict, separators=(",", ":"))
    return recipe_json, recipe_dict


def _get_assembly_plan(root_hash: str, recipe_json: str) -> Optional[dict]:
    """
    Return a ``TemplateAssembler`` assembly plan for the recipe, or ``None``
    if chunking prerequisites are not available.

    Attempts to pre-populate a transient ``ChunkStore`` from the local
    ``BlobStore`` so the assembler can report which shards are locally cached.
    This is used to annotate ``/api/get/{hash}`` responses with HLT-sync status
    and cache-hit metrics; it does **not** change the content bytes returned.
    """
    if _blob_store is None or _hlt is None:
        return None
    try:
        recipe_dict = json.loads(recipe_json)
        recipe = Recipe.from_dict(recipe_dict)

        from tfp_client.lib.cache.chunk_store import ChunkStore as _CS

        cs = _CS(max_chunks=len(recipe.chunk_ids) + 1)
        for idx, chunk_id in enumerate(recipe.chunk_ids):
            shard_data = _blob_store.get_shard(root_hash, idx)
            if shard_data is not None:
                # chunk_id is SHA3-256 of the shard payload (bytes after 16-byte header)
                payload = shard_data[16:] if len(shard_data) > 16 else shard_data
                cs.put(payload, category="shard", chunk_id_hint=chunk_id)

        assembler = TemplateAssembler(cs, _hlt)
        plan = assembler.get_assembly_plan(recipe)
        return {
            "hlt_synced": plan["hlt_synced"],
            "cache_hit_rate": plan["cache_hit_rate"],
            "cached_chunks": len(plan["cached_chunks"]),
            "missing_chunks": len(plan["missing_chunks"]),
            "ready_to_assemble": plan["ready_to_assemble"],
        }
    except Exception as exc:
        log.debug("Assembly plan failed for %s: %s", root_hash, exc)
        return None


@app.post("/api/earn")
def earn(
    payload: EarnRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    message = f"{payload.device_id}:{payload.task_id}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )
    # Rate-limit check (sliding window per device)
    if not _earn_rate_limiter.is_allowed(payload.device_id):
        _metrics.inc("tfp_earn_rate_limited_total")
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded — max {_EARN_RATE_MAX} earn calls per {_EARN_RATE_WINDOW}s per device",
        )
    # Deduplication — reject replayed task IDs (normalized format: task:{task_id})
    if not _earn_log.record(payload.device_id, f"task:{payload.task_id}"):
        _metrics.inc("tfp_earn_replay_rejected_total")
        raise HTTPException(
            status_code=409,
            detail="task_id already processed — each task may only be submitted once",
        )
    client = _client_for(payload.device_id)
    # Inject network-wide total so supply cap is enforced
    client.ledger.set_network_total_minted(
        _task_store.get_total_minted() if _task_store else 0
    )
    receipt = client.submit_compute_task(payload.task_id)
    if _task_store:
        _task_store.increment_total_minted(receipt.credits)
    # Persist updated ledger so credits survive a server restart
    _credit_store.save(payload.device_id, client)
    _metrics.inc("tfp_credits_minted_total", receipt.credits)
    return {
        "device_id": payload.device_id,
        "task_id": payload.task_id,
        "credits_earned": receipt.credits,
        "chain_hash": receipt.chain_hash.hex(),
    }


@app.get("/api/get/{root_hash}")
def get_content(
    root_hash: str,
    request: Request,
    stream: bool = Query(False),
    device_id: str = Query(default="web-demo"),
):
    client = _client_for(device_id)
    item = _content_store.get(root_hash)

    # If not in local content store, try fetching via NDN (which now checks IPFS)
    try:
        content = client.request_content(root_hash)
    except ValueError as exc:
        msg = str(exc).lower()
        if "no earned credits" in msg or "insufficient credits" in msg:
            raise HTTPException(
                status_code=402, detail="earn credits first via /api/earn"
            ) from exc
        # Explicit 404 for not found
        raise HTTPException(
            status_code=404,
            detail=f"content {root_hash} not found on local node or via discovery",
        ) from exc
    except Exception as exc:
        log.error("NDN retrieval error for %s: %s", root_hash, exc)
        raise HTTPException(
            status_code=500, detail="Internal error during retrieval"
        ) from exc

    _metrics.inc("tfp_content_served_total")
    _metrics.inc("tfp_credits_spent_total")

    if stream:
        data_bytes = content.content if hasattr(content, "content") else content.data

        # ── HTTP Range request (RFC 7233) ─────────────────────────────────
        range_header = request.headers.get("range")
        if range_header:
            range_response = _build_range_response(data_bytes, range_header)
            if range_response is not None:
                return range_response

        # ── Full streaming response ───────────────────────────────────────
        blob_path = _content_store.get_blob_path(root_hash) if _content_store else None
        if blob_path and _blob_store and _blob_store.exists(blob_path):

            def _fs_stream():
                yield from _blob_store.open_stream(blob_path)

            return StreamingResponse(
                _fs_stream(), media_type="application/octet-stream"
            )

        def stream_generator():
            chunk_size = 64 * 1024
            for i in range(0, len(data_bytes), chunk_size):
                yield data_bytes[i : i + chunk_size]

        return StreamingResponse(
            stream_generator(), media_type="application/octet-stream"
        )
    else:
        # Use metadata from item (local) or fallback to ipfs bridge metadata
        title = item.title if item else "Remote Content"
        tags = item.tags if item else []

        if not item and _ipfs_bridge:
            meta = _ipfs_bridge.get_metadata(root_hash)
            if meta:
                title = meta.get("title", title)
                tags = meta.get("tags", tags)

        data_bytes = content.content if hasattr(content, "content") else content.data
        response: dict = {
            "root_hash": root_hash,
            "title": title,
            "tags": tags,
            "text": data_bytes.decode(errors="replace"),
            "sha3": hashlib.sha3_256(data_bytes).hexdigest(),
        }
        # Annotate with assembly plan (HLT-sync status + chunk cache hit metrics)
        # when a recipe is available.  Never changes the returned content bytes.
        if item and item.recipe_json:
            plan = _get_assembly_plan(root_hash, item.recipe_json)
            if plan is not None:
                response["assembly_plan"] = plan
        return response


def _build_range_response(data: bytes, range_header: str) -> Optional[Response]:
    """
    Parse a ``Range: bytes=start-end`` header and return a 206 Partial Content
    Response, or None if the header cannot be parsed.
    """
    match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        return None
    total = len(data)
    start_str, end_str = match.group(1), match.group(2)
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else total - 1
    end = min(end, total - 1)
    if start > end or start >= total:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{total}"},
        )
    length = end - start + 1
    return Response(
        content=data[start : end + 1],
        status_code=206,
        media_type="application/octet-stream",
        headers={
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
        },
    )


@app.get("/api/content/{root_hash}/recipe")
def get_recipe(root_hash: str) -> dict:
    """Return the Recipe JSON for chunked content (produced at publish time)."""
    if _content_store is None:
        raise HTTPException(status_code=503, detail="store not ready")
    item = _content_store.get(root_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="content not found")
    if not item.recipe_json:
        raise HTTPException(
            status_code=404,
            detail="no recipe for this content (publish with TFP_ENABLE_CHUNKING=1)",
        )
    return json.loads(item.recipe_json)


@app.get("/api/content/{root_hash}/shard/{index}")
def get_shard(root_hash: str, index: int) -> Response:
    """
    Return the raw shard bytes for a single RaptorQ-encoded shard.

    NDN interest name equivalent: ``/tfp/content/{root_hash}/shard/{index}``

    Also tracks the shard in the local ``ChunkStore`` for pin-reward accounting:
    rare shards (low access count) earn a higher reward proportional to rarity.
    The reward is recorded as ``tfp_pin_rewards_total`` in the Prometheus metrics.
    """
    if _blob_store is None:
        raise HTTPException(status_code=503, detail="blob store not ready")
    if _content_store is None or not _content_store.contains(root_hash):
        raise HTTPException(status_code=404, detail="content not found")
    shard_data = _blob_store.get_shard(root_hash, index)
    if shard_data is None:
        raise HTTPException(status_code=404, detail=f"shard {index} not found")

    # ── Shard-pin economics ───────────────────────────────────────────────
    if _chunk_store is not None:
        try:
            chunk_id = f"{root_hash}:shard:{index}"
            is_new_pin = not _chunk_store.contains(chunk_id)
            if is_new_pin:
                # Register this shard in the chunk store so rarity is tracked.
                payload_bytes = shard_data[16:] if len(shard_data) > 16 else shard_data
                _chunk_store.put(
                    payload_bytes, category="shard", chunk_id_hint=chunk_id
                )
                reward = _chunk_store.calculate_pin_reward(chunk_id)
                if reward > 0:
                    _metrics.inc("tfp_pin_rewards_total")
        except Exception as _pin_exc:
            log.debug(
                "Pin reward tracking failed for %s shard %d: %s",
                root_hash,
                index,
                _pin_exc,
            )

    return Response(content=shard_data, media_type="application/octet-stream")


@app.get("/api/peer/{root_hash}")
def peer_get(
    root_hash: str,
    x_tfp_peer_secret: str = Header(default="", alias="X-TFP-Peer-Secret"),
) -> Response:
    """
    Internal mesh endpoint — serves raw blob bytes to peer nodes without credit check.

    This endpoint is intended only for intra-cluster communication (Docker internal
    network) and should not be exposed to the public internet.  It is used by the
    _PeerFallback mechanism so cold-start nodes can bootstrap content from siblings.

    When ``TFP_PEER_SECRET`` is set, callers **must** supply the matching value in the
    ``X-TFP-Peer-Secret`` header.  Mismatched or missing secrets → 401 Unauthorized.
    """
    if _runtime_mode == "production" and not _peer_secret:
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=503,
            detail=(
                "peer endpoint disabled in production mode until TFP_PEER_SECRET "
                "is configured"
            ),
        )
    if _peer_secret and not _hmac.compare_digest(x_tfp_peer_secret, _peer_secret):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing X-TFP-Peer-Secret — "
            "set TFP_PEER_SECRET on both nodes to enable peer mesh access",
        )
    if _content_store is None or _blob_store is None:
        raise HTTPException(status_code=503, detail="store not ready")
    blob_path = _content_store.get_blob_path(root_hash)
    if blob_path is None:
        raise HTTPException(status_code=404, detail="content not found")
    data = _blob_store.get(blob_path)
    if data is None:
        raise HTTPException(status_code=404, detail="blob not found")
    return Response(content=data, media_type="application/octet-stream")


@app.post("/api/delegate-proof")
def delegate_proof(
    payload: DelegateProofRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    """Prototyped ZKP delegation endpoint. Costs 5 credits."""
    message = f"{payload.device_id}:{payload.circuit}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature",
        )

    client = _client_for(payload.device_id)
    try:
        # Cost check: 5 credits for delegated ZKP generation
        client.spend_for_service(5)
    except ValueError as exc:
        raise HTTPException(
            status_code=402, detail=str(exc) + ". Earn credits via /api/earn first."
        ) from exc

    try:
        private_bytes = bytes.fromhex(payload.private_claim_hex)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="private_claim_hex must be valid hex"
        )

    # Use client's adapter (could be RealZKPAdapter if TFP_REAL_ADAPTERS=1)
    proof = client.zkp.generate_proof(circuit=payload.circuit, private=private_bytes)

    # Persist updated ledger balance
    _credit_store.save(payload.device_id, client)
    _metrics.inc("tfp_credits_spent_total", 5)

    return {
        "device_id": payload.device_id,
        "circuit": payload.circuit,
        "proof_hex": proof.hex(),
        "credits_remaining": client.ledger.balance,
    }


@app.get("/api/status")
def status(
    x_tfp_peer_secret: str = Header(default="", alias="X-TFP-Peer-Secret"),
) -> dict:
    """Node status: local content count, tag index stats, and Nostr subscriber state.

    In production mode the full response (including internal metrics and
    infrastructure details) is only returned when the caller supplies a
    valid ``X-TFP-Peer-Secret`` header.  Unauthenticated callers receive a
    minimal public subset.
    """
    # In production, redact internal details unless peer-secret is provided.
    _is_authed = _runtime_mode != "production" or (
        _peer_secret and _hmac.compare_digest(x_tfp_peer_secret, _peer_secret)
    )

    nostr_events = len(_nostr_subscriber.get_received()) if _nostr_subscriber else 0
    task_stats = _task_store.stats() if _task_store else {}

    # Public subset — always safe to expose.
    result: dict = {
        "version": "0.3.0",
        "content_items": _content_store.count(),
        "supply_cap": MAX_SUPPLY,
    }

    if _is_authed:
        rag_stats: Optional[dict] = None
        if _rag_graph is not None:
            try:
                rag_stats = _rag_graph.get_stats()
            except Exception:
                rag_stats = {"error": "unavailable"}
        result.update(
            {
                "runtime_mode": _runtime_mode,
                "nostr_events_received": nostr_events,
                "nostr_subscriber_running": (
                    _nostr_subscriber.is_running() if _nostr_subscriber else False
                ),
                "nostr_relay": (
                    _nostr_subscriber.relay_url if _nostr_subscriber else None
                ),
                "tasks": task_stats,
                "metrics": _metrics.snapshot(),
                "hlt_domains": len(_hlt.domain_names) if _hlt is not None else 0,
                "peer_nodes": (
                    len(_peer_fallback._peers) if _peer_fallback is not None else 0
                ),
                "rag_enabled": _rag_graph is not None,
                "rag_stats": rag_stats,
                "peer_secret_enforced": bool(_peer_secret),
                "admin_allowlist_enforced": bool(_admin_device_ids),
                "pin_rewards_active": _chunk_store is not None,
            }
        )

    return result


@app.get("/api/discovery")
def discovery(domain: str = Query(default="general")) -> dict:
    """
    Return content hashes discovered via Nostr announcements for a domain.

    These are remote peer announcements propagated through the Nostr relay;
    they supplement the local ``/api/content`` index.
    """
    try:
        epoch = TagOverlayIndex._get_current_epoch()
        dag = _tag_overlay.build_merkle_dag(epoch=epoch, domain=domain)
        entries = [
            {
                "content_hash": entry.content_hash.hex(),
                "tag": entry.tag,
                "popularity": entry.popularity_score,
            }
            for entry in dag.entries
        ]
    except (AttributeError, TypeError, ValueError) as e:
        log.warning("Failed to build Merkle DAG for domain %s: %s", domain, e)
        entries = []
    return {"domain": domain, "entries": entries, "source": "nostr"}


# ---------------------------------------------------------------------------
# Semantic search API (production RAG)
# ---------------------------------------------------------------------------


class SemanticSearchRequest(BaseModel):
    """Request body for POST /api/search/semantic."""

    device_id: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)


class AdminReindexRequest(BaseModel):
    """Request body for POST /api/admin/rag/reindex."""

    device_id: str = Field(min_length=1, max_length=120)
    patterns: Optional[str] = Field(
        default=None,
        description="Comma-separated file patterns (default: *.py,*.md)",
    )


@app.post("/api/search/semantic")
def semantic_search(
    payload: SemanticSearchRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    """
    Semantic similarity search over the local RAG index.

    Requires a valid device signature (same as other device-authed endpoints).
    Rate-limited to 20 queries / 60 s per device.  Returns 503 when the RAG
    index has not been initialised (``TFP_ENABLE_RAG=0`` or deps missing).

    Responses include cosine-similarity scored results from the local
    CodeBERT/ChromaDB index.  For hybrid distributed retrieval, combine this
    with ``GET /api/discovery`` to cross-reference peer-announced content.
    """
    message = f"{payload.device_id}:{payload.query}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )

    if not _rag_rate_limiter.is_allowed(payload.device_id):
        raise HTTPException(
            status_code=429,
            detail="semantic search rate limit exceeded — max 20 queries per 60 s per device",
        )

    if _rag_graph is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "semantic search is not available on this node "
                "(set TFP_ENABLE_RAG=1 and install chromadb + transformers)"
            ),
        )

    try:
        results = _rag_graph.search(
            query=payload.query,
            top_k=payload.top_k,
            min_score=payload.min_score,
        )
    except Exception as exc:
        log.error("Semantic search error: %s", exc)
        raise HTTPException(status_code=500, detail="semantic search failed") from exc

    _metrics.inc("tfp_semantic_search_total")
    return {
        "query": payload.query,
        "results": [
            {
                "content": r.content,
                "metadata": r.metadata,
                "score": r.score,
                "chunk_id": r.chunk_id,
            }
            for r in results
        ],
        "total": len(results),
        "rag_stats": _rag_graph.get_stats(),
    }


@app.post("/api/admin/rag/reindex")
def rag_reindex(
    payload: AdminReindexRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    """
    Rebuild the local RAG semantic index from a directory.

    Admin-only: requires a valid enrolled device signature AND the device must
    be in the ``TFP_ADMIN_DEVICE_IDS`` allowlist (when configured).
    This is a **synchronous, blocking** call — for large codebases run it
    off-peak or via a background worker.  Index writes are idempotent (existing
    chunks are overwritten by content hash).

    Returns 503 when ``TFP_ENABLE_RAG=0`` or dependencies are missing.
    """
    message = f"{payload.device_id}:reindex"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )

    # Admin device allowlist: when TFP_ADMIN_DEVICE_IDS is set, only listed
    # device IDs may trigger reindex.  This prevents self-enrolled devices from
    # abusing the expensive reindex operation as a DoS vector.
    if _runtime_mode == "production" and not _admin_device_ids:
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=503,
            detail=(
                "admin reindex is disabled in production mode until "
                "TFP_ADMIN_DEVICE_IDS is configured"
            ),
        )
    if _admin_device_ids and payload.device_id not in _admin_device_ids:
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=403,
            detail=(
                "device is not in the admin allowlist "
                "(set TFP_ADMIN_DEVICE_IDS to include this device_id)"
            ),
        )

    if _rag_graph is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "RAG index not available "
                "(set TFP_ENABLE_RAG=1 and install chromadb + transformers)"
            ),
        )

    # The index source directory: prefer TFP_RAG_SOURCE_DIR (the directory to
    # index), falling back to TFP_RAG_DIR for backwards compatibility.
    # TFP_RAG_DIR is the ChromaDB storage path and should NOT normally be walked.
    _rag_source_env = os.environ.get("TFP_RAG_SOURCE_DIR", "").strip()
    _rag_dir_env = os.environ.get("TFP_RAG_DIR", "").strip()
    if _rag_source_env:
        index_dir = Path(_rag_source_env)
    elif _rag_dir_env:
        log.warning(
            "TFP_RAG_SOURCE_DIR is not set; using TFP_RAG_DIR as index source. "
            "Set TFP_RAG_SOURCE_DIR to the directory you want to index and "
            "TFP_RAG_DIR to the ChromaDB storage path."
        )
        index_dir = Path(_rag_dir_env)
    else:
        raise HTTPException(
            status_code=503,
            detail=(
                "Neither TFP_RAG_SOURCE_DIR nor TFP_RAG_DIR is configured; "
                "set TFP_RAG_SOURCE_DIR to the directory to index"
            ),
        )
    if not index_dir.is_dir():
        raise HTTPException(
            status_code=503,
            detail=f"Index source directory does not exist or is not a directory: {index_dir}",
        )

    pattern_list: Optional[List[str]] = (
        [p.strip() for p in payload.patterns.split(",") if p.strip()]
        if payload.patterns
        else None
    )

    try:
        indexed = _rag_graph.index_directory(str(index_dir), patterns=pattern_list)
    except Exception as exc:
        log.error("RAG reindex error: %s", exc)
        raise HTTPException(status_code=500, detail=f"reindex failed: {exc}") from exc

    log.info("RAG reindex complete: %d chunks from %s", indexed, index_dir)
    _metrics.inc("tfp_rag_reindex_total")

    # Publish a search-index summary to Nostr so peer nodes can detect drift.
    if _nostr_bridge is not None:
        try:
            stats = _rag_graph.get_stats()
            # Build a canonical index fingerprint from content-derived fields:
            # collection name + total_chunks + collection_id (if available).
            # This makes nodes with the same count but different vectors produce
            # different hashes, making drift detection meaningful.
            _coll_id = stats.get("collection_id", stats.get("collection_name", ""))
            _fp = f"{_coll_id}:{stats.get('total_chunks', 0)}"
            # Hash sorted indexed file paths + mtimes for additional specificity.
            try:
                _file_fp = ":".join(
                    f"{p}:{os.path.getmtime(p):.0f}"
                    for p in sorted(str(f) for f in index_dir.rglob("*") if f.is_file())
                )
                _fp = f"{_fp}:{_file_fp}"
            except Exception:
                pass
            index_hash = hashlib.sha3_256(_fp.encode()).hexdigest()
            _nostr_bridge.publish_search_index_summary(
                domain="general",
                index_hash=index_hash,
                chunk_count=stats.get("total_chunks", 0),
            )
        except Exception as exc:
            log.debug("Failed to publish search-index gossip after reindex: %s", exc)

    return {
        "indexed_chunks": indexed,
        "directory": str(index_dir),
        "rag_stats": _rag_graph.get_stats(),
    }


# ---------------------------------------------------------------------------
# Compute task dispatch API
# ---------------------------------------------------------------------------


@app.post("/api/task")
def create_task(
    payload: CreateTaskRequest,
    x_device_sig: str = Header(alias="X-Device-Sig", default=""),
) -> dict:
    """
    Create a new compute task and broadcast it to the mesh.

    Any enrolled device may call this; unenrolled devices may create tasks
    without auth (tasks are public goods).
    """
    seed_bytes = bytes.fromhex(payload.seed_hex) if payload.seed_hex else os.urandom(16)
    try:
        spec = _task_store.create_task(
            task_type=payload.task_type,
            difficulty=payload.difficulty,
            seed=seed_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _metrics.inc("tfp_tasks_created_total")
    return {
        "task_id": spec.task_id,
        "task_type": spec.task_type.value,
        "difficulty": spec.difficulty,
        "credit_reward": spec.credit_reward,
        "deadline": spec.deadline,
        # Include enough input data for device to execute the task
        "input_data_hex": spec.input_data.hex(),
        "expected_output_hash": spec.expected_output_hash,
    }


@app.get("/api/tasks")
def list_tasks(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """
    Return open tasks available for device execution.

    ``open_count`` is the total number of open tasks in the pool (may be larger
    than ``limit``).  Use it to determine whether more tasks are available.
    """
    tasks = _task_store.list_open_tasks(limit=limit)
    stats = _task_store.stats()
    return {"tasks": tasks, "open_count": stats.get("open", 0)}


@app.get("/api/task/{task_id}")
def get_task(task_id: str) -> dict:
    """Get details and current status of a specific task."""
    row = _task_store.get_task_row(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    spec = _task_store.get_spec(task_id)
    result = {**row}
    if spec is not None:
        result["input_data_hex"] = spec.input_data.hex()
        result["expected_output_hash"] = spec.expected_output_hash
    return result


@app.post("/api/task/{task_id}/result")
def submit_task_result(
    task_id: str,
    payload: SubmitResultRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    """
    Submit a compute result for a task.

    The device must be enrolled and provide a valid signature.
    Credits are minted only after HABP consensus (3/5 matching results).

    When credits_earned > 0 the caller should follow up with POST /api/earn
    (using the task_id as proof) to credit their ledger, or the credits are
    automatically applied if the device is already tracked server-side.
    """
    message = f"{payload.device_id}:{task_id}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )

    if not _result_rate_limiter.is_allowed(payload.device_id):
        raise HTTPException(
            status_code=429,
            detail=(
                f"result submission rate limit exceeded — max {_RESULT_RATE_MAX}"
                f" per {_RESULT_RATE_WINDOW}s per device"
            ),
        )

    verification = _task_store.submit_result(
        task_id=task_id,
        device_id=payload.device_id,
        output_hash=payload.output_hash,
        exec_time_s=payload.exec_time_s,
        has_tee=payload.has_tee,
    )
    _metrics.inc("tfp_results_submitted_total")

    if verification["verified"]:
        _metrics.inc("tfp_tasks_completed_total")
        credits = verification["credits_earned"]
        # Auto-apply credits to the device's ledger if consensus is reached
        # (normalized format: task:{task_id} to prevent double-mint with /api/earn)
        if credits > 0 and not _earn_log.record(payload.device_id, f"task:{task_id}"):
            # Already applied (idempotent guard)
            pass
        elif credits > 0:
            client = _client_for(payload.device_id)
            client.ledger.set_network_total_minted(_task_store.get_total_minted())
            try:
                proof_material = f"{task_id}:{payload.output_hash}".encode()
                proof_hash = hashlib.sha3_256(proof_material).digest()
                receipt = client.ledger.mint(credits, proof_hash)
                client._earned_receipts.append(receipt)
                _task_store.increment_total_minted(credits)
                _credit_store.save(payload.device_id, client)
                _metrics.inc("tfp_credits_minted_total", credits)
            except Exception as exc:
                # Re-raise non-supply-cap errors to avoid silent failures
                from tfp_client.lib.credit.ledger import SupplyCapError

                if isinstance(exc, SupplyCapError):
                    # Supply cap reached - return 503 to client
                    log.error(
                        "Supply cap reached during auto-mint for device=%s task=%s credits=%d",
                        payload.device_id,
                        task_id,
                        credits,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail=f"Supply cap reached: cannot mint {credits} credits",
                    ) from exc
                else:
                    # Re-raise other exceptions for visibility
                    log.error(
                        "Auto-mint failed for device=%s task=%s credits=%d: %s",
                        payload.device_id,
                        task_id,
                        credits,
                        exc,
                    )
                    raise

        # Replenish task pool
        try:
            _preseed_tasks()
        except Exception as exc:
            log.warning("Task pool replenish failed: %s", exc)

    return verification


# ---------------------------------------------------------------------------
# Device leaderboard
# ---------------------------------------------------------------------------


@app.get("/api/devices")
def device_leaderboard_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    x_tfp_peer_secret: str = Header(default="", alias="X-TFP-Peer-Secret"),
) -> dict:
    """
    Return all enrolled devices sorted by credits earned (descending).

    Useful for leaderboards, network health checks, and federation tooling.
    ``total_enrolled`` reflects the true count of all devices, regardless of
    the ``limit`` parameter.

    In production mode, requires ``X-TFP-Peer-Secret`` header to prevent
    enumeration of device IDs and credit balances.
    """
    if _runtime_mode == "production":
        if not _peer_secret or not _hmac.compare_digest(
            x_tfp_peer_secret, _peer_secret
        ):
            _metrics.inc("tfp_auth_failures_total")
            raise HTTPException(
                status_code=401,
                detail="X-TFP-Peer-Secret required for /api/devices in production mode",
            )
    devices = _task_store.device_leaderboard(limit=limit)
    return {
        "devices": devices,
        "total_enrolled": _device_registry.count(),
    }


@app.get("/api/device/{device_id}")
def get_device(device_id: str) -> dict:
    """Return stats for a single enrolled device."""
    if not _device_registry.is_enrolled(device_id):
        raise HTTPException(status_code=404, detail="device not enrolled")
    match = _task_store.device_stats(device_id)
    if match is None:
        # Enrolled but no task contributions yet
        match = {
            "device_id": device_id,
            "enrolled_at": None,
            "credits_balance": 0,
            "tasks_contributed": 0,
            "last_active": None,
        }
    client = _clients.get(device_id)
    match["credits_in_memory"] = client.ledger.balance if client else None
    return match


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------


@app.get("/metrics")
def metrics(
    x_tfp_peer_secret: str = Header(default="", alias="X-TFP-Peer-Secret"),
) -> Response:
    """Prometheus-compatible text metrics endpoint.

    In production mode, requires ``X-TFP-Peer-Secret`` header so that
    internal counters (auth failures, credit totals, etc.) are not
    exposed to unauthenticated callers.
    """
    if _runtime_mode == "production":
        if not _peer_secret or not _hmac.compare_digest(
            x_tfp_peer_secret, _peer_secret
        ):
            _metrics.inc("tfp_auth_failures_total")
            raise HTTPException(
                status_code=401,
                detail="X-TFP-Peer-Secret required for /metrics in production mode",
            )
    return Response(
        content=_metrics.to_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>TFP Admin — Scholo Node</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:#0f0f14;color:#e0e0e8;padding:24px}
    h1{font-size:1.5rem;font-weight:700;color:#7c6fcd;margin-bottom:4px}
    .sub{color:#888;font-size:.85rem;margin-bottom:24px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-bottom:32px}
    .card{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;padding:20px}
    .card .label{font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
    .card .value{font-size:2rem;font-weight:700;color:#a89cef}
    .card .sub-value{font-size:.8rem;color:#666;margin-top:4px}
    table{width:100%;border-collapse:collapse;background:#1a1a24;border-radius:8px;overflow:hidden;margin-bottom:32px}
    th{text-align:left;padding:10px 16px;background:#222230;font-size:.8rem;color:#888;text-transform:uppercase}
    td{padding:10px 16px;font-size:.9rem;border-top:1px solid #2a2a38}
    tr:hover td{background:#20202e}
    .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.75rem;font-weight:600}
    .open{background:#1e3a2a;color:#4caf78}
    .completed{background:#1a2e4a;color:#5b9cf6}
    .verifying{background:#3a2a0e;color:#f0a030}
    .failed{background:#3a1a1a;color:#f06060}
    .refresh{margin-top:24px;color:#666;font-size:.8rem}
    .progress{background:#1a1a24;border-radius:99px;height:8px;margin-top:8px;overflow:hidden}
    .progress-bar{height:100%;background:linear-gradient(90deg,#7c6fcd,#a89cef);border-radius:99px;transition:width .4s}
    h2{margin-bottom:12px;font-size:1.1rem;color:#888}
  </style>
</head>
<body>
  <h1>⚡ TFP Node Admin</h1>
  <div class="sub" id="version">Loading…</div>

  <div class="grid" id="cards"></div>

  <h2>Open Tasks</h2>
  <table><thead><tr>
    <th>Task ID</th><th>Type</th><th>Difficulty</th><th>Reward</th><th>Time Left</th>
  </tr></thead><tbody id="tasks-body"></tbody></table>

  <h2>Device Leaderboard</h2>
  <table><thead><tr>
    <th>#</th><th>Device ID</th><th>Credits</th><th>Tasks</th><th>Last Active</th>
  </tr></thead><tbody id="devices-body"></tbody></table>

  <div class="refresh">Auto-refreshes every 5 seconds ·
    <a href="/api/status" style="color:#7c6fcd">Raw JSON</a> ·
    <a href="/api/devices" style="color:#7c6fcd">Devices</a> ·
    <a href="/metrics" style="color:#7c6fcd">Prometheus</a>
  </div>

  <script>
    async function refresh() {
      const [s, t, dv] = await Promise.all([
        fetch('/api/status').then(r=>r.json()).catch(()=>({})),
        fetch('/api/tasks').then(r=>r.json()).catch(()=>({tasks:[]})),
        fetch('/api/devices').then(r=>r.json()).catch(()=>({devices:[]})),
      ]);
      const tasks_s = s.tasks || {};
      const metrics_s = s.metrics || {};
      const supply_used = tasks_s.total_minted || 0;
      const supply_cap = s.supply_cap || 21000000;
      const pct = Math.min(100, (supply_used / supply_cap * 100)).toFixed(4);

      document.getElementById('version').textContent =
        `v${s.version || '?'} · Content: ${s.content_items||0} · Supply: ${supply_used.toLocaleString()} / ${supply_cap.toLocaleString()} credits`;

      const cards = [
        {label:'Open Tasks', value: tasks_s.open||0, sub:'awaiting devices'},
        {label:'Completed', value: tasks_s.completed||0, sub:'verified by consensus'},
        {label:'Credits Minted', value: (metrics_s.tfp_credits_minted_total||0).toLocaleString(), sub:`of ${supply_cap.toLocaleString()} cap`},
        {label:'Credits Spent', value: (metrics_s.tfp_credits_spent_total||0).toLocaleString(), sub:'on content access'},
        {label:'Devices Enrolled', value: metrics_s.tfp_devices_enrolled_total||0, sub:'unique devices'},
        {label:'Content Served', value: metrics_s.tfp_content_served_total||0, sub:'requests fulfilled'},
        {label:'Nostr Events', value: s.nostr_events_received||0, sub: s.nostr_subscriber_running?'live':'offline'},
        {label:'Supply Used', value: pct+'%', sub:'<div class="progress"><div class="progress-bar" style="width:'+pct+'%"></div></div>'},
      ];
      document.getElementById('cards').innerHTML = cards.map(c=>
        `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div><div class="sub-value">${c.sub}</div></div>`
      ).join('');

      const rows = (t.tasks||[]).map(tk=>`<tr>
        <td><code>${tk.task_id}</code></td>
        <td>${tk.task_type}</td>
        <td>${tk.difficulty}</td>
        <td>${tk.credit_reward} cr</td>
        <td>${tk.time_left_s}s</td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#555">No open tasks</td></tr>';
      document.getElementById('tasks-body').innerHTML = rows;

      const drows = (dv.devices||[]).slice(0,20).map((d,i)=>`<tr>
        <td>${i+1}</td>
        <td><code>${d.device_id}</code></td>
        <td>${(d.credits_balance||0).toLocaleString()}</td>
        <td>${d.tasks_contributed||0}</td>
        <td>${d.last_active ? new Date(d.last_active*1000).toLocaleTimeString() : '—'}</td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#555">No devices yet</td></tr>';
      document.getElementById('devices-body').innerHTML = drows;
    }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    x_tfp_peer_secret: str = Header(default="", alias="X-TFP-Peer-Secret"),
) -> HTMLResponse:
    """Live admin dashboard — shows node health, task pool, and credit supply."""
    if _runtime_mode == "production":
        if not _peer_secret:
            raise HTTPException(
                status_code=503,
                detail=(
                    "admin dashboard disabled in production mode until TFP_PEER_SECRET "
                    "is configured"
                ),
            )
        if not _hmac.compare_digest(x_tfp_peer_secret, _peer_secret):
            _metrics.inc("tfp_auth_failures_total")
            raise HTTPException(
                status_code=401,
                detail=(
                    "invalid or missing X-TFP-Peer-Secret for /admin in production mode"
                ),
            )
    return HTMLResponse(content=_ADMIN_HTML)
