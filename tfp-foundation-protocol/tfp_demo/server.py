import hashlib
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tfp_broadcaster.broadcaster import Broadcaster
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.ndn.adapter import Data, NDNAdapter


@dataclass
class StoredContent:
    root_hash: str
    title: str
    tags: List[str]
    data: bytes


class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    tags: List[str] = Field(default_factory=list)


class EarnRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=256)


class DemoNDNAdapter(NDNAdapter):
    def __init__(self, content_store: Dict[str, StoredContent]):
        self._content_store = content_store

    def express_interest(self, interest):
        root_hash = interest.name.rsplit("/", 1)[-1]
        if root_hash not in self._content_store:
            raise ValueError("content not found")
        return Data(name=interest.name, content=self._content_store[root_hash].data)


_store: Dict[str, StoredContent] = {}
_broadcaster = Broadcaster()
_clients: Dict[str, TFPClient] = {}
_demo_dir = Path(__file__).resolve().parent.parent / "demo"


def _client_for(device_id: str) -> TFPClient:
    if device_id not in _clients:
        _clients[device_id] = TFPClient(ndn=DemoNDNAdapter(_store))
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
    _store[result["root_hash"]] = StoredContent(
        root_hash=result["root_hash"],
        title="Welcome Sample",
        tags=["demo", "welcome", "audio"],
        data=sample,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not _store:
        _seed_sample()
    yield


app = FastAPI(title="TFP Demo Node", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "content_items": len(_store)}


@app.get("/")
def demo_page():
    return FileResponse(_demo_dir / "index.html")


@app.get("/api/content")
def search_content(tag: str | None = Query(default=None, min_length=1)) -> dict:
    items = list(_store.values())
    if tag:
        tag_norm = tag.strip().lower()
        items = [item for item in items if tag_norm in item.tags]
    return {
        "items": [
            {"root_hash": item.root_hash, "title": item.title, "tags": item.tags}
            for item in items
        ]
    }


@app.post("/api/publish")
def publish(payload: PublishRequest) -> dict:
    body = payload.text.encode()
    result = _broadcaster.seed_content(body, metadata={"title": payload.title}, use_ldm=False)
    tags = _normalize_tags(payload.tags)
    _store[result["root_hash"]] = StoredContent(
        root_hash=result["root_hash"],
        title=payload.title,
        tags=tags,
        data=body,
    )
    return {
        "root_hash": result["root_hash"],
        "title": payload.title,
        "tags": tags,
        "status": "broadcasting",
    }


@app.post("/api/earn")
def earn(payload: EarnRequest) -> dict:
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
    if root_hash not in _store:
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
        "title": _store[root_hash].title,
        "tags": _store[root_hash].tags,
        "text": content.data.decode(errors="replace"),
        "sha3": hashlib.sha3_256(content.data).hexdigest(),
    }
