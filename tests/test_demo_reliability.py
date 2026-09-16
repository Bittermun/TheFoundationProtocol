# SPDX-License-Identifier: Apache-2.0
"""User-journey regressions for identity, accounting, and packaged UI assets."""

import hashlib
import hmac
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from tfp_demo import server
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import CreditLedger

SECRET = bytes(range(32))
DEVICE = "reliability-browser"


def signed(message):
    return {"X-Device-Sig": hmac.new(SECRET, message.encode(), hashlib.sha256).hexdigest()}


def enroll(client, secret=SECRET):
    return client.post("/api/enroll", json={"device_id": DEVICE, "puf_entropy_hex": secret.hex()})


def allowance(client):
    response = client.post("/api/earn", json={"device_id": DEVICE, "task_id": "allowance"}, headers=signed(f"{DEVICE}:allowance"))
    assert response.status_code == 200, response.text


def publish(client):
    original = "A note in UTF-8: café, 水, 🌱."
    response = client.post("/api/publish", json={"device_id": DEVICE, "title": "A note", "text": original, "tags": ["community"]}, headers=signed(f"{DEVICE}:A note"))
    assert response.status_code == 200, response.text
    root = response.json()["root_hash"]
    assert root == hashlib.sha3_256(original.encode()).hexdigest()
    return root


def read(client, root, **kwargs):
    return client.get(f"/api/get/{root}", params={"device_id": DEVICE, **kwargs}, headers=signed(f"{DEVICE}:{root}"))


@pytest.fixture(autouse=True)
def isolated_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "demo.db"))
    monkeypatch.setenv("TFP_MODE", "demo")
    for variable in ("TFP_ENABLE_NOSTR", "TFP_ENABLE_IPFS", "TFP_ENABLE_MAINTENANCE"):
        monkeypatch.setenv(variable, "0")
    monkeypatch.delenv("TFP_DATABASE_URL", raising=False)


def test_refresh_preserves_identity_credits_and_enrollment_time_across_restart():
    with TestClient(server.app) as client:
        assert enroll(client).status_code == 200
        allowance(client)
        root = publish(client)
        assert read(client, root).status_code == 200
        before = client.get(f"/api/device/{DEVICE}").json()
        assert before["credits_balance"] == 9
        assert enroll(client).status_code == 200
        after = client.get(f"/api/device/{DEVICE}").json()
        assert after["credits_balance"] == 9
        assert after["enrolled_at"] == before["enrolled_at"]
        assert client.get("/api/status").json()["metrics"]["tfp_devices_enrolled_total"] == 1
    with TestClient(server.app) as client:
        assert enroll(client).status_code == 200
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 9
        assert read(client, root).status_code == 200
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 8
        restored = server._credit_store.load(DEVICE)
        assert len(restored.ledger.spent_receipts) == 2
        assert restored.ledger.total_minted == 10


def test_reenrollment_cannot_take_over_another_device():
    with TestClient(server.app) as client:
        enroll(client)
        allowance(client)
        assert enroll(client, b"x" * 32).status_code == 409
        assert server._device_registry.get_entropy(DEVICE) == SECRET
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 10


def test_ten_credits_allow_ten_reads_and_no_more():
    with TestClient(server.app) as client:
        enroll(client)
        root = publish(client)
        assert read(client, root).status_code == 402
        allowance(client)
        for remaining in range(9, -1, -1):
            assert read(client, root).status_code == 200
            assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == remaining
        assert read(client, root).status_code == 402
        metrics = client.get("/api/status").json()["metrics"]
        assert metrics["tfp_credits_spent_total"] == 10
        assert metrics["tfp_content_served_total"] == 10


def test_concurrent_reads_do_not_overspend():
    with TestClient(server.app) as client:
        enroll(client)
        allowance(client)
        root = publish(client)
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: read(client, root).status_code, range(16)))
        assert statuses.count(200) == 10
        assert statuses.count(402) == 6
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 0


def test_failed_and_invalid_range_reads_do_not_spend():
    with TestClient(server.app) as client:
        enroll(client)
        allowance(client)
        root = publish(client)
        assert read(client, "f" * 64).status_code == 404
        invalid = client.get(f"/api/get/{root}?device_id={DEVICE}&stream=true", headers={**signed(f"{DEVICE}:{root}"), "Range": "bytes=9999-"})
        assert invalid.status_code == 416
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 10
        suffix = client.get(f"/api/get/{root}?device_id={DEVICE}&stream=true", headers={**signed(f"{DEVICE}:{root}"), "Range": "bytes=-5"})
        assert suffix.status_code == 206
        assert suffix.content == "🌱.".encode()
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 9


def test_invalid_signature_cannot_spend_even_in_demo_mode():
    with TestClient(server.app) as client:
        enroll(client)
        allowance(client)
        root = publish(client)
        result = client.get(f"/api/get/{root}?device_id={DEVICE}", headers={"X-Device-Sig": "0" * 64})
        assert result.status_code == 401
        assert client.get(f"/api/device/{DEVICE}").json()["credits_balance"] == 10


def test_restricted_mode_disables_unverified_grants_and_requires_read_signature(monkeypatch):
    with TestClient(server.app) as client:
        enroll(client)
        allowance(client)
        root = publish(client)
        monkeypatch.setattr(server, "_runtime_mode", "production")
        grant = client.post("/api/earn", json={"device_id": DEVICE, "task_id": "arbitrary"}, headers=signed(f"{DEVICE}:arbitrary"))
        assert grant.status_code == 403
        assert client.get(f"/api/get/{root}?device_id={DEVICE}").status_code == 401
        assert read(client, root).status_code == 200


def test_static_assets_and_sample_library_are_available():
    with TestClient(server.app) as client:
        for path, kind in [("/", "text/html"), ("/assets/app.js", "javascript"), ("/assets/app.css", "text/css"), ("/assets/icon.svg", "image/svg+xml"), ("/manifest.json", "json"), ("/service-worker.js", "javascript")]:
            response = client.get(path)
            assert response.status_code == 200, path
            assert kind in response.headers["content-type"]
        notes = client.get("/api/content").json()["items"]
        assert len(notes) == 3
        assert client.get("/api/content?tag=community").json()["total"] >= 1
        assert client.get("/api/content?tag=learning").json()["total"] >= 1
        assert client.get("/api/content?tag=protocol").json()["total"] >= 1


def test_change_receipt_preserves_supply_and_rejects_old_receipt_replay():
    client = TFPClient(ledger=CreditLedger())
    receipt = client.submit_compute_task("one-grant")
    for _ in range(10):
        client.spend_for_service(1)
    assert client.ledger.balance == 0
    assert client.ledger.total_minted == 10
    assert client.ledger.network_total_minted == 10
    with pytest.raises(ValueError, match="already been spent"):
        client.ledger.spend(1, receipt)


def test_legacy_credit_schema_and_receipts_migrate_without_erasing_balance():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE credit_ledger (device_id TEXT PRIMARY KEY, balance INTEGER, chain_json TEXT, unspent_receipts_json TEXT)")
        original = TFPClient()
        receipt = original.submit_compute_task("legacy")
        encoded = json.dumps([receipt.chain_hash.hex()])
        conn.execute("INSERT INTO credit_ledger VALUES (?, ?, ?, ?)", ("legacy", 10, encoded, encoded))
        conn.commit()
        store = server.CreditStore(conn, threading.RLock())
        restored = store.load("legacy")
        assert restored.ledger.balance == 10
        restored.spend_for_service(1)
        store.save("legacy", restored)
        assert store.load("legacy").ledger.balance == 9
        assert receipt.chain_hash in store.load("legacy").ledger.spent_receipts
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_shard_verifier_accepts_encoder_mac_and_rejects_a_forged_mac():
    from tfp_client.lib.distribution.shard_retriever import ShardRetriever
    from tfp_client.lib.fountain.raptorq_ffi import RealRaptorQAdapter

    key = b"authenticated-shard-key"
    shard = RealRaptorQAdapter().encode(b"a real encoded shard", hmac_key=key)[0]
    verifier = ShardRetriever(None)
    assert await verifier.verify_shard_integrity(shard, hashlib.sha256(shard).hexdigest(), key)
    forged = shard[:-1] + bytes([shard[-1] ^ 1])
    # Even when the advertised plain hash matches, a forged MAC must fail.
    assert not await verifier.verify_shard_integrity(forged, hashlib.sha256(forged).hexdigest(), key)
