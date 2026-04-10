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
from tfp_client.lib.core.tfp_engine import TFPClient
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
    """Persistent content store backed by SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_schema()

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

    def put(self, item: StoredContent) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO content (root_hash, title, tags, data) VALUES (?, ?, ?, ?)",
            (item.root_hash, item.title, json.dumps(item.tags), item.data),
        )
        self._conn.commit()

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
        rows = self._conn.execute(
            """
            SELECT c.root_hash, c.title, c.tags, c.data
            FROM content c
            WHERE EXISTS (
                SELECT 1 FROM json_each(c.tags) WHERE value = ?
            )
            """,
            (tag,),
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


def _client_for(device_id: str) -> TFPClient:
    if device_id not in _clients:
        _clients[device_id] = TFPClient(ndn=DemoNDNAdapter(_content_store))
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _content_store, _device_registry, _clients
    db_path = os.environ.get("TFP_DB_PATH", str(_DEFAULT_DB_PATH))
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _content_store = ContentStore(_conn)
    _device_registry = DeviceRegistry(_conn)
    _clients.clear()
    if _content_store.count() == 0:
        _seed_sample()
    yield
    _conn.close()
    _content_store = None
    _device_registry = None


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
    client = _client_for(payload.device_id)
    receipt = client.submit_compute_task(payload.task_id)
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
