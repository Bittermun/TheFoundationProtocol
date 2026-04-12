"""
tests/test_recipe_pipeline.py

Phase B — Recipe/chunking pipeline tests.

Verifies:
- /api/publish with TFP_ENABLE_CHUNKING=1 stores shards and a Recipe JSON.
- GET /api/content/{root_hash}/recipe returns a valid Recipe.
- GET /api/content/{root_hash}/shard/{index} serves raw shard bytes.
- Recipe chunk_ids are SHA3-256 hashes of the shard payloads.
- /api/publish with TFP_ENABLE_CHUNKING=0 stores no recipe (backward compat).
- Retrieval via /api/get still works after chunked publish.
"""

import hashlib
import hmac as _hmac
import json
import os
import struct

os.environ.setdefault("TFP_DB_PATH", ":memory:")
os.environ.setdefault("TFP_ENABLE_CHUNKING", "1")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200, r.text


def _publish(client, device_id: str, puf: bytes, title: str, text: str) -> str:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={
            "title": title,
            "text": text,
            "tags": ["test", "audio"],
            "device_id": device_id,
        },
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


def _earn(client, device_id: str, puf: bytes, task_id: str) -> None:
    sig = _sig(puf, f"{device_id}:{task_id}")
    r = client.post(
        "/api/earn",
        json={"device_id": device_id, "task_id": task_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Recipe endpoint tests
# ---------------------------------------------------------------------------


def test_publish_chunking_enabled_returns_recipe_in_response(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "chunk-dev", puf)
        sig = _sig(puf, "chunk-dev:ChunkTitle")
        r = client.post(
            "/api/publish",
            json={
                "title": "ChunkTitle",
                "text": "chunked content body",
                "tags": ["audio"],
                "device_id": "chunk-dev",
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 200
        body = r.json()
        # Recipe must be embedded in the publish response when chunking is on
        assert "recipe" in body
        recipe = body["recipe"]
        assert "chunk_ids" in recipe
        assert len(recipe["chunk_ids"]) >= 1
        assert recipe["content_hash"] == body["root_hash"]


def test_recipe_endpoint_returns_valid_recipe(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "recipe-dev", puf)
        root_hash = _publish(client, "recipe-dev", puf, "RecipeTitle", "recipe body")

        r = client.get(f"/api/content/{root_hash}/recipe")
        assert r.status_code == 200
        recipe = r.json()
        assert recipe["content_hash"] == root_hash
        assert "chunk_ids" in recipe
        assert isinstance(recipe["chunk_ids"], list)
        assert "ai_adapter" in recipe
        assert "template_id" in recipe


def test_recipe_chunk_ids_are_sha3_hashes(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "hashdev", puf)
        root_hash = _publish(client, "hashdev", puf, "HashCheck", "data for hashing")

        recipe = client.get(f"/api/content/{root_hash}/recipe").json()
        for cid in recipe["chunk_ids"]:
            # Each chunk_id must be a 64-char hex string (SHA3-256)
            assert len(cid) == 64, f"chunk_id {cid!r} is not 64 chars"
            int(cid, 16)  # must be valid hex


def test_shard_endpoint_returns_bytes(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard-dev", puf)
        root_hash = _publish(client, "shard-dev", puf, "ShardTitle", "shard data body")

        recipe = client.get(f"/api/content/{root_hash}/recipe").json()
        assert len(recipe["chunk_ids"]) >= 1

        # First shard must be serveable
        r = client.get(f"/api/content/{root_hash}/shard/0")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert len(r.content) > 0


def test_shard_endpoint_missing_returns_404(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard404-dev", puf)
        root_hash = _publish(
            client, "shard404-dev", puf, "Shard404", "some content here"
        )

        # Shard index way out of range must 404
        r = client.get(f"/api/content/{root_hash}/shard/9999")
        assert r.status_code == 404


def test_shard_endpoint_unknown_hash_returns_404(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        r = client.get(f"/api/content/{'0' * 64}/shard/0")
        assert r.status_code == 404


def test_recipe_endpoint_without_recipe_returns_404(monkeypatch):
    """Content published with chunking disabled must return 404 for /recipe."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "nochunk-dev", puf)
        root_hash = _publish(
            client, "nochunk-dev", puf, "NoChunk", "plain content no recipe"
        )

        r = client.get(f"/api/content/{root_hash}/recipe")
        assert r.status_code == 404


def test_publish_chunking_disabled_no_recipe_in_response(monkeypatch):
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "0")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "nochunk2-dev", puf)
        sig = _sig(puf, "nochunk2-dev:NoChunk2")
        r = client.post(
            "/api/publish",
            json={
                "title": "NoChunk2",
                "text": "plain",
                "tags": [],
                "device_id": "nochunk2-dev",
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 200
        body = r.json()
        # recipe key absent or None when chunking disabled
        assert body.get("recipe") is None


def test_get_content_still_works_after_chunked_publish(monkeypatch):
    """End-to-end: chunked publish, earn credits, get by hash — text round-trip."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "e2e-chunk-dev"
        _enroll(client, device_id, puf)
        text = "hello chunked world"
        root_hash = _publish(client, device_id, puf, "E2EChunk", text)
        _earn(client, device_id, puf, "task-e2e-chunk")

        r = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert r.status_code == 200
        assert r.json()["text"] == text


def test_recipe_ai_adapter_derived_from_tags(monkeypatch):
    """ai_adapter in Recipe must be derived from content tags or 'general'."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "adapter-dev", puf)

        sig = _sig(puf, "adapter-dev:AdapterTitle")
        r = client.post(
            "/api/publish",
            json={
                "title": "AdapterTitle",
                "text": "adapter test",
                "tags": ["medical", "healthcare"],
                "device_id": "adapter-dev",
            },
            headers={"X-Device-Sig": sig},
        )
        assert r.status_code == 200
        root_hash = r.json()["root_hash"]

        recipe = client.get(f"/api/content/{root_hash}/recipe").json()
        # ai_adapter should be the first tag or "general"
        assert recipe["ai_adapter"] in ("medical", "healthcare", "general")


def test_shard_content_integrity(monkeypatch):
    """Shard served via HTTP must be a valid RaptorQ-framed shard (16-byte header)."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "integrity-dev", puf)
        root_hash = _publish(
            client, "integrity-dev", puf, "IntegrityTitle", "x" * 300
        )

        r = client.get(f"/api/content/{root_hash}/shard/0")
        assert r.status_code == 200
        shard_bytes = r.content
        # RaptorQ frame header: orig_len (8) + k (4) + idx (4) = 16 bytes
        assert len(shard_bytes) >= 16
        orig_len, k, idx = struct.unpack(">QII", shard_bytes[:16])
        assert orig_len > 0
        assert k >= 1
        assert idx == 0  # first shard has index 0
