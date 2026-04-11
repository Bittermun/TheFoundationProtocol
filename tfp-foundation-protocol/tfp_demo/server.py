import collections
import hashlib
import hmac as _hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tfp_broadcaster.broadcaster import Broadcaster
from tfp_client.lib.bridges.nostr_subscriber import NostrSubscriber
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import CreditLedger, Receipt
from tfp_client.lib.metadata.tag_index import TagOverlayIndex
from tfp_client.lib.ndn.adapter import Data, NDNAdapter

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "pib.db"


@dataclass
class StoredContent:
    root_hash: str
    title: str
    tags: List[str]
    data: bytes


# ---------------------------------------------------------------------------
# Content store (SQLite-backed)
# ---------------------------------------------------------------------------

class ContentStore:
    """
    Persistent content store backed by SQLite with an in-memory tag index.

    The in-memory ``_tag_index`` maps tag → set[root_hash] for O(1) tag
    look-ups on the hot ``filter_by_tag`` path.  It is rebuilt from the DB
    on construction and kept in sync on every ``put``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._tag_index: Dict[str, set] = {}  # tag → {root_hash, ...}
        self._init_schema()
        self._rebuild_tag_index()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                root_hash TEXT PRIMARY KEY,
                title     TEXT NOT NULL,
                tags      TEXT NOT NULL,
                data      BLOB NOT NULL
            )
            """
        )
        self._conn.commit()

    def _rebuild_tag_index(self) -> None:
        """Rebuild the in-memory tag index from the current DB rows."""
        self._tag_index.clear()
        rows = self._conn.execute("SELECT root_hash, tags FROM content").fetchall()
        for root_hash, tags_json in rows:
            for tag in json.loads(tags_json):
                self._tag_index.setdefault(tag, set()).add(root_hash)

    def put(self, item: StoredContent) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO content (root_hash, title, tags, data) VALUES (?, ?, ?, ?)",
            (item.root_hash, item.title, json.dumps(item.tags), item.data),
        )
        self._conn.commit()
        for tag in item.tags:
            self._tag_index.setdefault(tag, set()).add(item.root_hash)

    def get(self, root_hash: str) -> Optional[StoredContent]:
        row = self._conn.execute(
            "SELECT root_hash, title, tags, data FROM content WHERE root_hash = ?",
            (root_hash,),
        ).fetchone()
        if row is None:
            return None
        return StoredContent(
            root_hash=row[0],
            title=row[1],
            tags=json.loads(row[2]),
            data=row[3],
        )

    def all(self) -> List[StoredContent]:
        rows = self._conn.execute(
            "SELECT root_hash, title, tags, data FROM content"
        ).fetchall()
        return [
            StoredContent(root_hash=r[0], title=r[1], tags=json.loads(r[2]), data=r[3])
            for r in rows
        ]

    def filter_by_tag(self, tag: str) -> List[StoredContent]:
        """Return items matching *tag* using the in-memory index (O(n_matches))."""
        hashes = self._tag_index.get(tag, set())
        if not hashes:
            return []
        placeholders = ",".join("?" * len(hashes))
        rows = self._conn.execute(
            f"SELECT root_hash, title, tags, data FROM content WHERE root_hash IN ({placeholders})",
            list(hashes),
        ).fetchall()
        return [
            StoredContent(root_hash=r[0], title=r[1], tags=json.loads(r[2]), data=r[3])
            for r in rows
        ]

    def contains(self, root_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM content WHERE root_hash = ?", (root_hash,)
        ).fetchone()
        return row is not None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]



# ---------------------------------------------------------------------------
# Device registry (SQLite-backed)
# ---------------------------------------------------------------------------

class DeviceRegistry:
    """Stores enrolled device PUF entropy for request-signing verification."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
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
        self._conn.execute(
            "INSERT OR REPLACE INTO devices (device_id, puf_entropy, enrolled_at) "
            "VALUES (?, ?, ?)",
            (device_id, puf_entropy, time.time()),
        )
        self._conn.commit()

    def get_entropy(self, device_id: str) -> Optional[bytes]:
        row = self._conn.execute(
            "SELECT puf_entropy FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        return bytes(row[0]) if row else None

    def is_enrolled(self, device_id: str) -> bool:
        return self.get_entropy(device_id) is not None


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

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS earn_log (
                device_id TEXT NOT NULL,
                task_id   TEXT NOT NULL,
                earned_at REAL NOT NULL,
                PRIMARY KEY (device_id, task_id)
            )
            """
        )
        self._conn.commit()

    def record(self, device_id: str, task_id: str) -> bool:
        """Attempt to record an earn event.  Returns True if new, False if duplicate."""
        try:
            self._conn.execute(
                "INSERT INTO earn_log (device_id, task_id, earned_at) VALUES (?, ?, ?)",
                (device_id, task_id, time.time()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


# ---------------------------------------------------------------------------
# Credit store — persists ledger state across server restarts
# ---------------------------------------------------------------------------

class CreditStore:
    """
    SQLite-backed persistence for per-device CreditLedger state.

    Stores the hash chain, current balance, and the unspent receipt hashes so
    the ledger can be fully reconstructed after a server restart.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_ledger (
                device_id             TEXT PRIMARY KEY,
                balance               INTEGER NOT NULL DEFAULT 0,
                chain_json            TEXT    NOT NULL DEFAULT '[]',
                unspent_receipts_json TEXT    NOT NULL DEFAULT '[]'
            )
            """
        )
        self._conn.commit()

    def save(self, device_id: str, client: "TFPClient") -> None:
        """Persist the client's current ledger + unspent receipts."""
        chain_json = json.dumps([h.hex() for h in client.ledger.chain])
        balance = client.ledger.balance
        unspent_json = json.dumps(
            [r.chain_hash.hex() for r in client._earned_receipts]
        )
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
        client = TFPClient(ndn=DemoNDNAdapter(_content_store), ledger=ledger)
        client._earned_receipts = unspent_receipts
        return client


# ---------------------------------------------------------------------------
# Rate limiter — sliding-window token bucket per device
# ---------------------------------------------------------------------------

_EARN_RATE_MAX = int(os.environ.get("TFP_EARN_RATE_MAX", "10"))
_EARN_RATE_WINDOW = int(os.environ.get("TFP_EARN_RATE_WINDOW", "60"))


class _RateLimiter:
    """
    In-memory sliding-window rate limiter.

    Allows at most ``max_calls`` calls per ``window_seconds`` per key.
    Thread-safe by virtue of the GIL on CPython; each bucket is a deque of
    float timestamps that is pruned on every check.
    """

    def __init__(self, max_calls: int = _EARN_RATE_MAX, window_seconds: int = _EARN_RATE_WINDOW) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: Dict[str, collections.deque] = {}

    def is_allowed(self, key: str) -> bool:
        """Return True and record the call, or False if the rate limit is exceeded."""
        now = time.monotonic()
        bucket = self._buckets.setdefault(key, collections.deque())
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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    tags: List[str] = Field(default_factory=list)
    device_id: str = Field(min_length=1, max_length=120)


class EarnRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=256)


class EnrollRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    puf_entropy_hex: str = Field(min_length=64, max_length=64)


# ---------------------------------------------------------------------------
# App state (initialised in lifespan)
# ---------------------------------------------------------------------------

_content_store: Optional[ContentStore] = None
_device_registry: Optional[DeviceRegistry] = None
_earn_log: Optional[EarnLog] = None
_credit_store: Optional[CreditStore] = None
_earn_rate_limiter: _RateLimiter = _RateLimiter()
_tag_overlay: Optional[TagOverlayIndex] = None
_nostr_subscriber: Optional[NostrSubscriber] = None
_broadcaster = Broadcaster()
_clients: Dict[str, TFPClient] = {}
_demo_dir = Path(__file__).resolve().parent.parent / "demo"


class DemoNDNAdapter(NDNAdapter):
    def __init__(self, store: ContentStore):
        self._store = store

    def express_interest(self, interest):
        root_hash = interest.name.rsplit("/", 1)[-1]
        item = self._store.get(root_hash)
        if item is None:
            raise ValueError("content not found")
        return Data(name=interest.name, content=item.data)


def _make_ndn_adapter() -> NDNAdapter:
    """Return the real NDN adapter when TFP_REAL_ADAPTERS=1, else the demo store adapter."""
    if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
        from tfp_client.lib.ndn.ndn_real import RealNDNAdapter
        return RealNDNAdapter()
    return DemoNDNAdapter(_content_store)


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
            if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
                from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter
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
    result = _broadcaster.seed_content(sample, metadata={"title": "Welcome Sample"}, use_ldm=False)
    _content_store.put(StoredContent(
        root_hash=result["root_hash"],
        title="Welcome Sample",
        tags=["demo", "welcome", "audio"],
        data=sample,
    ))


def _on_nostr_event(event_dict: dict) -> None:
    """Callback: ingest a remote TFP Nostr announcement into the tag overlay."""
    try:
        payload = json.loads(event_dict.get("content", "{}"))
        content_hash_hex = payload.get("hash", "")
        tags = payload.get("tags", [])
        if content_hash_hex and len(content_hash_hex) == 64:
            content_hash_bytes = bytes.fromhex(content_hash_hex)
            domain = payload.get("domain", "general")
            _tag_overlay.add_entry(
                domain=domain,
                tags=tags if tags else ["nostr"],
                content_hash=content_hash_bytes,
                popularity=0.5,
            )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _content_store, _device_registry, _earn_log, _credit_store, _earn_rate_limiter, _tag_overlay, _nostr_subscriber, _clients
    db_path = os.environ.get("TFP_DB_PATH", str(_DEFAULT_DB_PATH))
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _content_store = ContentStore(_conn)
    _device_registry = DeviceRegistry(_conn)
    _earn_log = EarnLog(_conn)
    _credit_store = CreditStore(_conn)
    _earn_rate_limiter = _RateLimiter()
    _tag_overlay = TagOverlayIndex()
    _clients.clear()
    if _content_store.count() == 0:
        _seed_sample()

    # Start Nostr subscriber in offline mode unless NOSTR_RELAY is set
    relay_url = os.environ.get("NOSTR_RELAY", "")
    _nostr_subscriber = NostrSubscriber(
        relay_url=relay_url or "wss://relay.damus.io",
        on_event=_on_nostr_event,
        offline=not relay_url,
    )
    _nostr_subscriber.start()

    yield

    _nostr_subscriber.stop()
    _conn.close()
    _content_store = None
    _device_registry = None
    _earn_log = None
    _credit_store = None
    _tag_overlay = None
    _nostr_subscriber = None


app = FastAPI(title="TFP Demo Node", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "content_items": _content_store.count()}


@app.get("/")
def demo_page():
    return FileResponse(_demo_dir / "index.html")


@app.get("/manifest.json")
def manifest():
    return FileResponse(_demo_dir / "manifest.json", media_type="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(_demo_dir / "service-worker.js", media_type="application/javascript")


@app.get("/api/content")
def search_content(tag: str | None = Query(default=None, min_length=1)) -> dict:
    if tag:
        items = _content_store.filter_by_tag(tag.strip().lower())
    else:
        items = _content_store.all()
    return {
        "items": [
            {"root_hash": item.root_hash, "title": item.title, "tags": item.tags}
            for item in items
        ]
    }


@app.post("/api/enroll")
def enroll(payload: EnrollRequest) -> dict:
    try:
        puf_entropy = bytes.fromhex(payload.puf_entropy_hex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="puf_entropy_hex must be valid hex") from exc
    _device_registry.enroll(payload.device_id, puf_entropy)
    return {"enrolled": True, "device_id": payload.device_id}


@app.post("/api/publish")
def publish(
    payload: PublishRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    message = f"{payload.device_id}:{payload.title}"
    if not _verify_device_sig(payload.device_id, x_device_sig, message, _device_registry):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )
    body = payload.text.encode()
    result = _broadcaster.seed_content(body, metadata={"title": payload.title}, use_ldm=False)
    tags = _normalize_tags(payload.tags)
    _content_store.put(StoredContent(
        root_hash=result["root_hash"],
        title=payload.title,
        tags=tags,
        data=body,
    ))
    return {
        "root_hash": result["root_hash"],
        "title": payload.title,
        "tags": tags,
        "status": "broadcasting",
    }


@app.post("/api/earn")
def earn(
    payload: EarnRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    message = f"{payload.device_id}:{payload.task_id}"
    if not _verify_device_sig(payload.device_id, x_device_sig, message, _device_registry):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )
    # Rate-limit check (sliding window per device)
    if not _earn_rate_limiter.is_allowed(payload.device_id):
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded — max {_EARN_RATE_MAX} earn calls per {_EARN_RATE_WINDOW}s per device",
        )
    # Deduplication — reject replayed task IDs
    if not _earn_log.record(payload.device_id, payload.task_id):
        raise HTTPException(
            status_code=409,
            detail="task_id already processed — each task may only be submitted once",
        )
    client = _client_for(payload.device_id)
    receipt = client.submit_compute_task(payload.task_id)
    # Persist updated ledger so credits survive a server restart
    _credit_store.save(payload.device_id, client)
    return {
        "device_id": payload.device_id,
        "task_id": payload.task_id,
        "credits_earned": receipt.credits,
        "chain_hash": receipt.chain_hash.hex(),
    }


@app.get("/api/get/{root_hash}")
def get_content(root_hash: str, device_id: str = Query(default="web-demo")) -> dict:
    item = _content_store.get(root_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="content not found")

    client = _client_for(device_id)
    try:
        content = client.request_content(root_hash)
    except ValueError as exc:
        if "no earned credits" in str(exc):
            raise HTTPException(status_code=402, detail="earn credits first via /api/earn") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "root_hash": content.root_hash,
        "title": item.title,
        "tags": item.tags,
        "text": content.data.decode(errors="replace"),
        "sha3": hashlib.sha3_256(content.data).hexdigest(),
    }


@app.get("/api/status")
def status() -> dict:
    """Node status: local content count, tag index stats, and Nostr subscriber state."""
    nostr_events = len(_nostr_subscriber.get_received()) if _nostr_subscriber else 0
    return {
        "version": "0.2.0",
        "content_items": _content_store.count(),
        "nostr_events_received": nostr_events,
        "nostr_subscriber_running": _nostr_subscriber.is_running() if _nostr_subscriber else False,
        "nostr_relay": _nostr_subscriber.relay_url if _nostr_subscriber else None,
    }


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
    except Exception:
        entries = []
    return {"domain": domain, "entries": entries, "source": "nostr"}
