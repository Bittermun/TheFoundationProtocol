# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_restart_safety.py

Verifies that all durable state (device enrollments, content, tasks, credits,
metrics) survives a simulated server restart by closing one TestClient context
and opening a second one against the same SQLite file.
"""

import hashlib
import hmac as _hmac
import os
import pathlib
import tempfile

import pytest
from fastapi.testclient import TestClient
from tfp_demo.server import _Metrics, app


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


def _publish(client, device_id, puf, title, text="body"):
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={"title": title, "text": text, "tags": [], "device_id": device_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


def _earn(client, device_id, puf, task_id):
    sig = _sig(puf, f"{device_id}:{task_id}")
    r = client.post(
        "/api/earn",
        json={"device_id": device_id, "task_id": task_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _submit_result(client, device_id, puf, task_id, output_hash):
    sig = _sig(puf, f"{device_id}:{task_id}")
    r = client.post(
        f"/api/task/{task_id}/result",
        json={
            "device_id": device_id,
            "output_hash": output_hash,
            "exec_time_s": 0.1,
            "has_tee": False,
        },
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def db_file():
    """Yield a temporary file-backed SQLite path, restore env on teardown."""
    import shutil
    import time

    orig = os.environ.get("TFP_DB_PATH")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["TFP_DB_PATH"] = tmp.name
    yield tmp.name
    # Restore
    if orig is not None:
        os.environ["TFP_DB_PATH"] = orig
    else:
        os.environ["TFP_DB_PATH"] = ":memory:"
    # Retry deletion for Windows file locking
    for _ in range(5):
        try:
            pathlib.Path(tmp.name).unlink(missing_ok=True)
            shutil.rmtree(pathlib.Path(tmp.name).with_suffix(".blobs"), ignore_errors=True)
            break
        except PermissionError:
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Test 1 — Device enrollments survive restart
# ---------------------------------------------------------------------------


def test_device_enrollments_survive_restart(db_file):
    """A device enrolled in lifecycle-1 must still be recognised in lifecycle-2."""
    puf = os.urandom(32)
    device_id = "restart-enroll-dev"

    with TestClient(app) as c1:
        _enroll(c1, device_id, puf)
        assert c1.get("/api/devices").json()["total_enrolled"] >= 1

    with TestClient(app) as c2:
        # Device must still be enrolled
        r = c2.get(f"/api/device/{device_id}")
        assert r.status_code == 200
        assert r.json()["device_id"] == device_id


# ---------------------------------------------------------------------------
# Test 2 — Published content survives restart
# ---------------------------------------------------------------------------


def test_content_survives_restart(db_file):
    """Content published in lifecycle-1 must be retrievable in lifecycle-2."""
    puf = os.urandom(32)
    device_id = "restart-content-dev"
    title = "RestartTest"

    with TestClient(app) as c1:
        _enroll(c1, device_id, puf)
        root_hash = _publish(c1, device_id, puf, title, "persisted body text")

    with TestClient(app) as c2:
        # Content must be in the listing
        listing = c2.get("/api/content").json()
        hashes = [item["root_hash"] for item in listing["items"]]
        assert root_hash in hashes


# ---------------------------------------------------------------------------
# Test 3 — Credit balances survive restart
# ---------------------------------------------------------------------------


def test_credits_survive_restart(db_file):
    """Credits earned in lifecycle-1 must be spendable in lifecycle-2."""
    puf = os.urandom(32)
    device_id = "restart-credits-dev"
    title = "CreditRestartTitle"

    with TestClient(app) as c1:
        _enroll(c1, device_id, puf)
        root_hash = _publish(c1, device_id, puf, title, "credit restart body")
        _earn(c1, device_id, puf, "restart-task-1")

    with TestClient(app) as c2:
        # Credits persisted — content retrieval must succeed (200)
        get_r = c2.get(f"/api/get/{root_hash}", params={"device_id": device_id})
        assert get_r.status_code == 200, f"Credits lost on restart: {get_r.json()}"
        assert get_r.json()["text"] == "credit restart body"


# ---------------------------------------------------------------------------
# Test 4 — Task records survive restart
# ---------------------------------------------------------------------------


def test_tasks_survive_restart(db_file):
    """Tasks created in lifecycle-1 must be visible in lifecycle-2."""
    with TestClient(app) as c1:
        r = c1.post(
            "/api/task",
            json={"task_type": "hash_preimage", "difficulty": 1, "seed_hex": ""},
        )
        assert r.status_code == 200, r.text
        task_id = r.json()["task_id"]

    with TestClient(app) as c2:
        task_r = c2.get(f"/api/task/{task_id}")
        assert task_r.status_code == 200
        assert task_r.json()["task_id"] == task_id


# ---------------------------------------------------------------------------
# Test 5 — Metrics are seeded from SQLite on restart
# ---------------------------------------------------------------------------


def test_metrics_seeded_from_db_on_restart(db_file):
    """After a restart, durable Prometheus counters are seeded from SQLite."""
    puf = os.urandom(32)
    device_id = "restart-metrics-dev"

    with TestClient(app) as c1:
        _enroll(c1, device_id, puf)
        _earn(c1, device_id, puf, "metrics-task-seed")

        # Credits minted in lifecycle-1
        metrics_text = c1.get("/metrics").text
        assert "tfp_credits_minted_total" in metrics_text

    with TestClient(app) as c2:
        metrics_text2 = c2.get("/metrics").text
        # After restart, the counter is seeded from the supply_ledger table
        # It must be >= what was minted before
        assert "tfp_credits_minted_total" in metrics_text2
        # Parse the value
        for line in metrics_text2.splitlines():
            if line.startswith("tfp_credits_minted_total "):
                value = int(line.split()[-1])
                assert value >= 10, f"Expected minted >= 10 after restart, got {value}"
                break


# ---------------------------------------------------------------------------
# Test 6 — HABP consensus state rebuilt on restart
# ---------------------------------------------------------------------------


def test_habp_proofs_rebuilt_after_restart(db_file):
    """
    Proofs submitted pre-restart must be replayed so consensus can still be
    reached after the server restarts.
    """
    pufs = [os.urandom(32) for _ in range(3)]
    device_ids = [f"restart-habp-{i}" for i in range(3)]

    with TestClient(app) as c1:
        for did, puf in zip(device_ids, pufs):
            _enroll(c1, did, puf)

        # Create task
        task_r = c1.post(
            "/api/task",
            json={"task_type": "content_verify", "difficulty": 1, "seed_hex": ""},
        )
        task_id = task_r.json()["task_id"]
        expected_hash = task_r.json()["expected_output_hash"]

        # Submit 2 proofs pre-restart
        for did, puf in zip(device_ids[:2], pufs[:2]):
            result = _submit_result(c1, did, puf, task_id, expected_hash)
            assert result["verified"] is False  # not yet

    # Restart
    with TestClient(app) as c2:
        # Submit the 3rd proof post-restart — consensus must still be reachable
        # because proofs are rebuilt from task_results table on startup
        result = _submit_result(c2, device_ids[2], pufs[2], task_id, expected_hash)
        assert result["verified"] is True, (
            f"HABP state not rebuilt after restart: {result}"
        )
