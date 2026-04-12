"""
tests/test_credit_replay.py

Verifies that the EarnLog + task_results UNIQUE constraints prevent a device
from collecting credits more than once for the same task.
"""

import hashlib
import hmac as _hmac
import os
import sqlite3

os.environ.setdefault("TFP_DB_PATH", ":memory:")

from fastapi.testclient import TestClient
from tfp_demo.server import EarnLog, app


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


def _earn(client, device_id: str, puf: bytes, task_id: str) -> dict:
    sig = _sig(puf, f"{device_id}:{task_id}")
    r = client.post(
        "/api/earn",
        json={"device_id": device_id, "task_id": task_id},
        headers={"X-Device-Sig": sig},
    )
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_earn_same_task_id_second_call_returns_409():
    """POST /api/earn with a replayed task_id must return 409 Conflict."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "replay-dev-1"
        _enroll(client, device_id, puf)

        r1 = _earn(client, device_id, puf, "replay-task-a")
        assert r1.status_code == 200
        assert r1.json()["credits_earned"] == 10

        r2 = _earn(client, device_id, puf, "replay-task-a")
        assert r2.status_code == 409
        assert "already processed" in r2.json()["detail"]


def test_earn_different_task_ids_both_succeed():
    """Each distinct task_id may be earned exactly once per device."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "replay-dev-2"
        _enroll(client, device_id, puf)

        for i in range(4):
            r = _earn(client, device_id, puf, f"distinct-task-{i}")
            assert r.status_code == 200, f"task {i} failed: {r.text}"
            assert r.json()["credits_earned"] == 10


def test_earn_replay_rejected_for_any_device_task_combo():
    """Each (device_id, task_id) pair is unique; different devices may earn the same task."""
    with TestClient(app) as client:
        puf_a = os.urandom(32)
        puf_b = os.urandom(32)
        _enroll(client, "replay-alice", puf_a)
        _enroll(client, "replay-bob", puf_b)

        shared_task = "shared-task-001"

        # Alice earns — succeeds
        ra = _earn(client, "replay-alice", puf_a, shared_task)
        assert ra.status_code == 200

        # Bob earns the same task — also succeeds (different device)
        rb = _earn(client, "replay-bob", puf_b, shared_task)
        assert rb.status_code == 200

        # Alice tries again — must fail
        ra2 = _earn(client, "replay-alice", puf_a, shared_task)
        assert ra2.status_code == 409

        # Bob tries again — must also fail
        rb2 = _earn(client, "replay-bob", puf_b, shared_task)
        assert rb2.status_code == 409


def test_earn_replay_rejected_metric_incremented():
    """Replay rejections must be tracked in tfp_earn_replay_rejected_total."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "replay-metric-dev"
        _enroll(client, device_id, puf)

        _earn(client, device_id, puf, "metric-task")
        _earn(client, device_id, puf, "metric-task")  # replay

        metrics_text = client.get("/metrics").text
        for line in metrics_text.splitlines():
            if line.startswith("tfp_earn_replay_rejected_total "):
                count = int(line.split()[-1])
                assert count >= 1
                break
        else:
            raise AssertionError(
                "tfp_earn_replay_rejected_total not found in /metrics"
            )


def test_earn_log_class_first_call_returns_true():
    """EarnLog.record returns True on the first insert for a (device, task) pair."""
    conn = sqlite3.connect(":memory:")
    log = EarnLog(conn)
    assert log.record("dev-1", "task-1") is True


def test_earn_log_class_duplicate_returns_false():
    """EarnLog.record returns False when the same pair is inserted a second time."""
    conn = sqlite3.connect(":memory:")
    log = EarnLog(conn)
    log.record("dev-1", "task-1")
    assert log.record("dev-1", "task-1") is False


def test_earn_log_class_different_device_same_task_returns_true():
    """Different devices can each earn the same task (different row)."""
    conn = sqlite3.connect(":memory:")
    log = EarnLog(conn)
    assert log.record("alice", "task-1") is True
    assert log.record("bob", "task-1") is True


def test_earn_log_class_same_device_different_tasks_returns_true():
    """One device can earn multiple different tasks."""
    conn = sqlite3.connect(":memory:")
    log = EarnLog(conn)
    assert log.record("dev-1", "task-a") is True
    assert log.record("dev-1", "task-b") is True
    assert log.record("dev-1", "task-a") is False  # duplicate
