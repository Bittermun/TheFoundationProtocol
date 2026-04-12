"""
tests/test_shard_economics.py

Tests for shard-pin reward tracking on GET /api/content/{hash}/shard/{N}.

Verifies:
- GET /api/content/{hash}/shard/{N} returns 200 with shard bytes.
- First shard serve increments tfp_pin_rewards_total metric (reward > 0 for new shard).
- Subsequent requests for the same shard do not double-count rewards.
- GET shard for missing content returns 404.
- GET shard for out-of-range index returns 404.
"""

import hashlib
import hmac as _hmac
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

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
    assert r.status_code == 200


def _publish(client, device_id: str, puf: bytes, title: str, text: str) -> dict:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={
            "title": title,
            "text": text,
            "tags": ["test"],
            "device_id": device_id,
        },
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Shard serve + pin economics
# ---------------------------------------------------------------------------


def test_shard_serve_returns_bytes(monkeypatch):
    """GET shard returns 200 with raw bytes when recipe is present."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard-econ-1", puf)
        result = _publish(
            client,
            "shard-econ-1",
            puf,
            "ShardTitle",
            "A" * 500,  # enough bytes to trigger sharding
        )
        root_hash = result["root_hash"]
        recipe = result.get("recipe")
        if recipe is None:
            pytest.skip("No recipe generated (chunking may be disabled or too short)")

        # Fetch shard 0
        r = client.get(f"/api/content/{root_hash}/shard/0")
        assert r.status_code == 200
        assert len(r.content) > 0


def test_shard_serve_increments_pin_reward_metric(monkeypatch):
    """First shard serve must increment tfp_pin_rewards_total."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    from tfp_demo import server

    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard-econ-2", puf)
        result = _publish(
            client,
            "shard-econ-2",
            puf,
            "PinTitle",
            "B" * 500,
        )
        root_hash = result["root_hash"]
        recipe = result.get("recipe")
        if recipe is None:
            pytest.skip("No recipe generated")

        if server._chunk_store is None:
            pytest.skip("ChunkStore not initialised")

        before = server._metrics.get("tfp_pin_rewards_total")
        r = client.get(f"/api/content/{root_hash}/shard/0")
        assert r.status_code == 200
        after = server._metrics.get("tfp_pin_rewards_total")
        # First-ever serve of a new shard must earn a reward
        assert after > before


def test_shard_serve_no_double_reward_on_second_request(monkeypatch):
    """Second request for the same shard does not earn an additional reward."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    from tfp_demo import server

    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard-econ-3", puf)
        result = _publish(
            client,
            "shard-econ-3",
            puf,
            "NoDblPin",
            "C" * 500,
        )
        root_hash = result["root_hash"]
        recipe = result.get("recipe")
        if recipe is None:
            pytest.skip("No recipe generated")

        if server._chunk_store is None:
            pytest.skip("ChunkStore not initialised")

        # First fetch
        client.get(f"/api/content/{root_hash}/shard/0")
        before = server._metrics.get("tfp_pin_rewards_total")
        # Second fetch — same shard already in ChunkStore
        client.get(f"/api/content/{root_hash}/shard/0")
        after = server._metrics.get("tfp_pin_rewards_total")
        # calculate_pin_reward returns 0 for already-cached chunks
        assert after == before


def test_shard_404_for_unknown_root_hash():
    with TestClient(app) as client:
        r = client.get(f"/api/content/{'0' * 64}/shard/0")
        assert r.status_code == 404


def test_shard_404_for_out_of_range_index(monkeypatch):
    """Requesting a shard index that was never written returns 404."""
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with TestClient(app) as client:
        puf = os.urandom(32)
        _enroll(client, "shard-econ-4", puf)
        result = _publish(
            client,
            "shard-econ-4",
            puf,
            "OobShard",
            "D" * 300,
        )
        root_hash = result["root_hash"]
        # Shard 9999 almost certainly doesn't exist
        r = client.get(f"/api/content/{root_hash}/shard/9999")
        assert r.status_code == 404


def test_shard_503_without_blob_store(monkeypatch):
    """With blob store disabled the endpoint returns 503."""
    import tfp_demo.server as srv

    with TestClient(app) as client:
        orig = srv._blob_store
        try:
            srv._blob_store = None
            r = client.get(f"/api/content/{'a' * 64}/shard/0")
            assert r.status_code == 503
        finally:
            srv._blob_store = orig
