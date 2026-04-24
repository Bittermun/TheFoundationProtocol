# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import hashlib
import hmac as _hmac
import os
import sqlite3
import threading
import time

os.environ["TFP_DB_PATH"] = ":memory:"

import pytest
from fastapi.testclient import TestClient
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import CreditLedger
from tfp_demo.server import CreditStore, EarnLog, _RateLimiter, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sig(puf_entropy: bytes, message: str) -> str:
    """Compute HMAC-SHA-256(puf_entropy, message) as hex."""
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf_entropy: bytes) -> None:
    resp = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["content_items"] >= 1


def test_enroll_device():
    with TestClient(app) as client:
        puf_entropy = bytes(range(32))
        response = client.post(
            "/api/enroll",
            json={"device_id": "test-device", "puf_entropy_hex": puf_entropy.hex()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enrolled"] is True
        assert body["device_id"] == "test-device"


def test_enroll_invalid_hex():
    with TestClient(app) as client:
        response = client.post(
            "/api/enroll",
            json={"device_id": "dev", "puf_entropy_hex": "not-valid-hex" + "0" * 51},
        )
        assert response.status_code == 422


def test_publish_missing_sig_header_returns_422():
    with TestClient(app) as client:
        response = client.post(
            "/api/publish",
            json={"title": "Demo", "text": "Hello", "tags": [], "device_id": "anon"},
        )
        assert response.status_code == 422


def test_publish_unknown_device_returns_401():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        sig = _make_sig(puf_entropy, "ghost:Demo")
        response = client.post(
            "/api/publish",
            json={"title": "Demo", "text": "Hello", "tags": [], "device_id": "ghost"},
            headers={"X-Device-Sig": sig},
        )
        assert response.status_code == 401


def test_earn_missing_sig_header_returns_422():
    with TestClient(app) as client:
        response = client.post(
            "/api/earn",
            json={"device_id": "anon", "task_id": "t1"},
        )
        assert response.status_code == 422


def test_publish_and_get_requires_credits():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "tester"
        _enroll(client, device_id, puf_entropy)

        # Publish with valid signature
        title = "Demo"
        publish_sig = _make_sig(puf_entropy, f"{device_id}:{title}")
        publish = client.post(
            "/api/publish",
            json={
                "title": title,
                "text": "Hello network",
                "tags": ["demo"],
                "device_id": device_id,
            },
            headers={"X-Device-Sig": publish_sig},
        )
        assert publish.status_code == 200
        root_hash = publish.json()["root_hash"]

        # Get without credits → 402
        denied = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert denied.status_code == 402

        # Earn credits
        task_id = "task-1"
        earn_sig = _make_sig(puf_entropy, f"{device_id}:{task_id}")
        earn = client.post(
            "/api/earn",
            json={"device_id": device_id, "task_id": task_id},
            headers={"X-Device-Sig": earn_sig},
        )
        assert earn.status_code == 200
        assert earn.json()["credits_earned"] == 10

        # Get with credits → 200
        ok = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert ok.status_code == 200
        body = ok.json()
        assert body["text"] == "Hello network"
        assert body["root_hash"] == root_hash


def test_search_by_tag():
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "tag-tester"
        _enroll(client, device_id, puf_entropy)

        title = "Tagged Content"
        sig = _make_sig(puf_entropy, f"{device_id}:{title}")
        pub = client.post(
            "/api/publish",
            json={
                "title": title,
                "text": "tag filtering test",
                "tags": ["unique-tag-xyz"],
                "device_id": device_id,
            },
            headers={"X-Device-Sig": sig},
        )
        assert pub.status_code == 200
        root_hash = pub.json()["root_hash"]

        results = client.get("/api/content", params={"tag": "unique-tag-xyz"}).json()
        hashes = [item["root_hash"] for item in results["items"]]
        assert root_hash in hashes

        no_results = client.get(
            "/api/content", params={"tag": "nonexistent-tag"}
        ).json()
        assert no_results["items"] == []


def test_get_missing_content_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/get/deadbeef" + "0" * 56)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fix 1: Task-ID deduplication — credit replay prevention
# ---------------------------------------------------------------------------


def test_earn_duplicate_task_id_returns_409():
    """The same task_id must only earn credits once per device."""
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "replay-device"
        _enroll(client, device_id, puf_entropy)

        sig = _make_sig(puf_entropy, f"{device_id}:task-replay")
        first = client.post(
            "/api/earn",
            json={"device_id": device_id, "task_id": "task-replay"},
            headers={"X-Device-Sig": sig},
        )
        assert first.status_code == 200
        assert first.json()["credits_earned"] == 10

        # Second call with the same task_id must be rejected
        second = client.post(
            "/api/earn",
            json={"device_id": device_id, "task_id": "task-replay"},
            headers={"X-Device-Sig": sig},
        )
        assert second.status_code == 409
        assert "already processed" in second.json()["detail"]


def test_earn_different_task_ids_both_succeed():
    """Different task IDs must each earn exactly once."""
    with TestClient(app) as client:
        puf_entropy = os.urandom(32)
        device_id = "dedup-two-tasks"
        _enroll(client, device_id, puf_entropy)

        for i in range(3):
            task_id = f"unique-task-{i}"
            sig = _make_sig(puf_entropy, f"{device_id}:{task_id}")
            r = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": task_id},
                headers={"X-Device-Sig": sig},
            )
            assert r.status_code == 200, f"task {i} failed: {r.text}"
            assert r.json()["credits_earned"] == 10


def test_earn_log_class_deduplication():
    """EarnLog.record returns True on first insert, False on duplicate."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    log = EarnLog(conn, db_lock)
    assert log.record("dev-a", "task-1") is True
    assert log.record("dev-a", "task-1") is False  # duplicate
    assert log.record("dev-a", "task-2") is True  # different task
    assert log.record("dev-b", "task-1") is True  # different device


# ---------------------------------------------------------------------------
# Fix 2: Credit persistence across server restarts
# ---------------------------------------------------------------------------


def test_credits_persist_across_restarts():
    """Credits earned in one lifespan must be spendable in the next."""
    import pathlib
    import tempfile
    import shutil

    orig_env = os.environ.get("TFP_DB_PATH")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_file = tmp.name
    try:
        os.environ["TFP_DB_PATH"] = db_file

        puf_entropy = os.urandom(32)
        device_id = "persist-tester"

        # Lifecycle 1: enroll + earn
        with TestClient(app) as client:
            _enroll(client, device_id, puf_entropy)

            # Publish some content
            title = "PersistTest"
            pub_sig = _make_sig(puf_entropy, f"{device_id}:{title}")
            pub = client.post(
                "/api/publish",
                json={
                    "title": title,
                    "text": "data",
                    "tags": [],
                    "device_id": device_id,
                },
                headers={"X-Device-Sig": pub_sig},
            )
            root_hash = pub.json()["root_hash"]

            # Earn credits
            earn_sig = _make_sig(puf_entropy, f"{device_id}:persist-task")
            earn = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "persist-task"},
                headers={"X-Device-Sig": earn_sig},
            )
            assert earn.status_code == 200

        # Lifecycle 2: new server context — credits must still work
        with TestClient(app) as client:
            ok = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
            assert ok.status_code == 200, f"credits lost on restart: {ok.json()}"
    finally:
        os.environ.pop("TFP_DB_PATH", None)
        if orig_env is not None:
            os.environ["TFP_DB_PATH"] = orig_env
        else:
            os.environ["TFP_DB_PATH"] = ":memory:"
        # Retry deletion for Windows file locking
        for _ in range(5):
            try:
                pathlib.Path(db_file).unlink(missing_ok=True)
                shutil.rmtree(
                    pathlib.Path(db_file).with_suffix(".blobs"), ignore_errors=True
                )
                break
            except PermissionError:
                time.sleep(0.1)


def test_credit_store_class_save_and_load():
    """CreditStore round-trips a ledger + unspent receipts correctly."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    store = CreditStore(conn, db_lock)

    # Build a client with credits
    ledger = CreditLedger()
    import hashlib as _hl

    r1 = ledger.mint(10, _hl.sha3_256(b"task1").digest())
    r2 = ledger.mint(10, _hl.sha3_256(b"task2").digest())

    from tfp_demo.server import ContentStore, DemoNDNAdapter

    content_conn = sqlite3.connect(":memory:")
    content_db_lock = threading.RLock()
    cs = ContentStore(content_conn, content_db_lock)
    client = TFPClient(ndn=DemoNDNAdapter(cs), ledger=ledger)
    client._earned_receipts = [r1, r2]

    store.save("dev-x", client)

    # Wipe in-memory state and reload
    conn2 = sqlite3.connect(":memory:")
    db_lock2 = threading.RLock()
    # Copy schema + data via backup
    conn.backup(conn2)
    store2 = CreditStore(conn2, db_lock2)

    # CreditStore.load needs _content_store set; patch temporarily
    import tfp_demo.server as srv

    old_store = srv._content_store
    srv._content_store = cs
    restored = store2.load("dev-x")
    srv._content_store = old_store

    assert restored is not None
    assert restored.ledger.balance == 20
    assert len(restored._earned_receipts) == 2
    hashes = {r.chain_hash for r in restored._earned_receipts}
    assert r1.chain_hash in hashes
    assert r2.chain_hash in hashes


def test_credit_ledger_from_snapshot():
    """CreditLedger.from_snapshot restores chain and balance."""
    original = CreditLedger()
    import hashlib as _hl

    original.mint(10, _hl.sha3_256(b"p0").digest())
    original.mint(10, _hl.sha3_256(b"p1").digest())

    restored = CreditLedger.from_snapshot(original.chain, original.balance)
    assert restored.balance == 20
    assert restored.chain == original.chain


# ---------------------------------------------------------------------------
# Fix 3: Per-device rate limiting
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_within_window():
    limiter = _RateLimiter(max_calls=3, window_seconds=60)
    assert limiter.is_allowed("dev") is True
    assert limiter.is_allowed("dev") is True
    assert limiter.is_allowed("dev") is True


def test_rate_limiter_blocks_over_limit():
    limiter = _RateLimiter(max_calls=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("dev")
    assert limiter.is_allowed("dev") is False


def test_rate_limiter_independent_per_device():
    limiter = _RateLimiter(max_calls=1, window_seconds=60)
    assert limiter.is_allowed("alice") is True
    assert limiter.is_allowed("bob") is True  # different key — unaffected
    assert limiter.is_allowed("alice") is False


def test_rate_limiter_reset():
    limiter = _RateLimiter(max_calls=1, window_seconds=60)
    assert limiter.is_allowed("dev") is True
    assert limiter.is_allowed("dev") is False
    limiter.reset("dev")
    assert limiter.is_allowed("dev") is True


def test_earn_rate_limit_returns_429():
    """Hitting the earn endpoint more than the limit returns HTTP 429."""
    import tfp_demo.server as srv

    with TestClient(app) as client:
        # Replace the limiter AFTER lifespan init so it isn't overwritten
        original_limiter = srv._earn_rate_limiter
        srv._earn_rate_limiter = _RateLimiter(max_calls=2, window_seconds=60)
        try:
            puf_entropy = os.urandom(32)
            device_id = "rate-limit-dev"
            _enroll(client, device_id, puf_entropy)

            for i in range(2):
                sig = _make_sig(puf_entropy, f"{device_id}:task-rl-{i}")
                r = client.post(
                    "/api/earn",
                    json={"device_id": device_id, "task_id": f"task-rl-{i}"},
                    headers={"X-Device-Sig": sig},
                )
                assert r.status_code == 200

            # Third call exceeds limit
            sig3 = _make_sig(puf_entropy, f"{device_id}:task-rl-2")
            r3 = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": "task-rl-2"},
                headers={"X-Device-Sig": sig3},
            )
            assert r3.status_code == 429
            assert "rate limit" in r3.json()["detail"]
        finally:
            srv._earn_rate_limiter = original_limiter


# ---------------------------------------------------------------------------
# Fix 4: Real adapters wired via TFP_REAL_ADAPTERS=1
# ---------------------------------------------------------------------------


def test_real_adapters_importable():
    """All real adapter classes must import without error."""
    from tfp_broadcaster.src.multicast.multicast_real import RealMulticastAdapter
    from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter
    from tfp_client.lib.ndn.ndn_real import RealNDNAdapter
    from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

    for cls in (
        RealNDNAdapter,
        RealRaptorQAdapter,
        RealZKPAdapter,
        RealMulticastAdapter,
    ):
        assert callable(cls)


def test_real_raptorq_encode_decode_roundtrip():
    """RealRaptorQAdapter encode→decode must recover original data."""
    from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter

    adapter = RealRaptorQAdapter()
    data = b"Hello fountain codes! " * 20
    shards = adapter.encode(data, redundancy=0.2)
    assert len(shards) > 1
    recovered = adapter.decode(shards)
    assert data in recovered or recovered[: len(data)] == data


def test_real_zkp_generate_and_verify():
    """RealZKPAdapter proof must be 64 bytes and verify correctly."""
    from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

    adapter = RealZKPAdapter()
    proof = adapter.generate_proof("access_to_hash", b"my_secret_witness")
    assert len(proof) == 65  # 33 bytes compressed R + 32 bytes s
    # Verify against the same public input
    public = hashlib.sha3_256(b"access_to_hash").digest()
    assert adapter.verify_proof(proof, public) is True


def test_client_for_uses_real_adapters_when_env_set():
    """When TFP_REAL_ADAPTERS=1, _client_for must return real RaptorQ/ZKP adapters."""
    import tfp_demo.server as srv
    from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter
    from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

    os.environ["TFP_REAL_ADAPTERS"] = "1"
    try:
        with TestClient(app) as _:
            # Force a fresh client
            srv._clients.pop("real-adapter-test", None)
            client = srv._client_for("real-adapter-test")
            assert isinstance(client.raptorq, RealRaptorQAdapter)
            assert isinstance(client.zkp, RealZKPAdapter)
    finally:
        del os.environ["TFP_REAL_ADAPTERS"]
        srv._clients.pop("real-adapter-test", None)


# ---------------------------------------------------------------------------
# Fix 5: ZKP proof gate is enforced in request_content
# ---------------------------------------------------------------------------


def test_request_content_valid_zkp_proof_passes():
    """request_content must succeed when a valid ZKP proof is supplied."""
    from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

    zkp = RealZKPAdapter()
    root_hash = "abc123"
    proof = zkp.generate_proof("access_to_hash", b"secret")
    client = TFPClient(zkp=zkp)
    client.submit_compute_task("task-zkp-valid")
    # Does not raise
    content = client.request_content(root_hash, zkp_proof=proof)
    assert content is not None


def test_request_content_invalid_zkp_proof_raises_security_error():
    """request_content must raise SecurityError when the ZKP proof is invalid."""
    from tfp_client.lib.core.tfp_engine import SecurityError
    from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

    zkp = RealZKPAdapter()
    bad_proof = bytes(64)  # all-zero proof — invalid
    client = TFPClient(zkp=zkp)
    client.submit_compute_task("task-zkp-bad")
    with pytest.raises(SecurityError, match="ZKP proof verification failed"):
        client.request_content("abc123", zkp_proof=bad_proof)


def test_request_content_no_zkp_proof_skips_gate():
    """Passing zkp_proof=None must not trigger the ZKP gate (backward-compat)."""
    client = TFPClient()
    client.submit_compute_task("task-no-zkp")
    content = client.request_content("abc123")  # no zkp_proof — no error
    assert content is not None
