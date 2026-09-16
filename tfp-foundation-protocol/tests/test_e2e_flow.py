# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_e2e_flow.py

End-to-end test: enroll â†’ open tasks â†’ execute task â†’ HABP consensus mint
â†’ spend credit â†’ retrieve content.

Every step is real (no mocks); the only stub is the in-process TestClient.
"""

import hashlib
import hmac as _hmac
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest

from tfp_client.lib.compute.task_executor import TaskSpec, execute_task
from fastapi.testclient import TestClient
from tfp_demo.server import app


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


def _publish(client, device_id: str, puf: bytes, title: str, text: str) -> str:
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={"title": title, "text": text, "tags": ["e2e"], "device_id": device_id},
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    return r.json()["root_hash"]


def _create_task(
    client, task_type: str = "content_verify", difficulty: int = 1
) -> dict:
    r = client.post(
        "/api/task",
        json={"task_type": task_type, "difficulty": difficulty, "seed_hex": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _submit_result(
    client, device_id: str, puf: bytes, task_id: str, output_hash: str
) -> dict:
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


# ---------------------------------------------------------------------------
# Test 1 â€” Full E2E lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_type", ["hash_preimage", "matrix_verify", "content_verify"])
def test_full_e2e_enroll_task_consensus_mint_spend_retrieve(task_type):
    """
    Complete lifecycle: enroll 3 compute devices + 1 publisher, publish
    content, create task, drive HABP consensus with 3 matching result
    submissions, verify auto-mint, then spend credits to retrieve content.
    """
    with TestClient(app) as client:
        # Step 1 â€” enroll publisher + 3 compute devices
        pub_puf = os.urandom(32)
        _enroll(client, "e2e-pub", pub_puf)

        compute_devices = []
        for i in range(3):
            puf = os.urandom(32)
            _enroll(client, f"e2e-compute-{i}", puf)
            compute_devices.append((f"e2e-compute-{i}", puf))

        # Step 2 â€” publisher publishes content
        root_hash = _publish(
            client, "e2e-pub", pub_puf, "E2E Article", "Hello from the E2E test!"
        )
        assert len(root_hash) == 64

        # Step 3 â€” verify content is indexed
        content_resp = client.get("/api/content", params={"tag": "e2e"})
        assert content_resp.status_code == 200
        hashes = [item["root_hash"] for item in content_resp.json()["items"]]
        assert root_hash in hashes

        # Step 4 â€” create a task
        task = _create_task(client, task_type=task_type, difficulty=1)
        task_id = task["task_id"]
        expected_hash = task["expected_output_hash"]
        assert len(task_id) > 0
        assert len(expected_hash) == 64

        # Step 5 â€” poll open tasks and verify task appears
        tasks_resp = client.get("/api/tasks")
        assert tasks_resp.status_code == 200
        open_ids = [t["task_id"] for t in tasks_resp.json()["tasks"]]
        assert task_id in open_ids

        # Step 6 â€” 3 devices submit the correct output hash (HABP consensus)
        detail = client.get(f"/api/task/{task_id}").json()
        results = []
        for device_id, puf in compute_devices:
            spec = TaskSpec.from_dict({**detail, "expected_output_hash": ""})
            executed = execute_task(spec, timeout_s=5)
            assert executed.output_hash == hashlib.sha3_256(executed.result_bytes).hexdigest()
            assert executed.output_hash == expected_hash
            result = _submit_result(client, device_id, puf, task_id, executed.output_hash)
            results.append(result)

        # Step 7 â€” 3rd submission must trigger consensus
        final = results[-1]
        assert final["verified"] is True, f"Expected consensus: {final}"
        assert final["credits_earned"] > 0
        assert final["consensus_needed"] == 0
        # Step 8 — every participant can spend its earned credits.
        for device_id, puf in compute_devices:
            before = client.get(f"/api/device/{device_id}").json()["credits_balance"]
            assert before > 0
            get_resp = client.get(
                f"/api/get/{root_hash}", params={"device_id": device_id},
                headers={"X-Device-Sig": _sig(puf, f"{device_id}:{root_hash}")},
            )
            assert get_resp.status_code == 200, get_resp.text
            body = get_resp.json()
            assert body["text"] == "Hello from the E2E test!"
            assert body["root_hash"] == root_hash
            assert body["sha3"] == hashlib.sha3_256(b"Hello from the E2E test!").hexdigest()
            after = client.get(f"/api/device/{device_id}").json()["credits_balance"]
            assert after == before - 1



# ---------------------------------------------------------------------------
# Test 2 â€” Partial consensus (only 2 devices) must NOT mint
# ---------------------------------------------------------------------------


def test_e2e_two_devices_insufficient_no_mint():
    """Two matching submissions must not trigger consensus (threshold is 3)."""
    with TestClient(app) as client:
        devices = []
        for i in range(2):
            puf = os.urandom(32)
            _enroll(client, f"e2e-partial-{i}", puf)
            devices.append((f"e2e-partial-{i}", puf))

        task = _create_task(client, task_type="matrix_verify", difficulty=1)
        task_id = task["task_id"]
        expected_hash = task["expected_output_hash"]

        for device_id, puf in devices:
            result = _submit_result(client, device_id, puf, task_id, expected_hash)
            assert result["verified"] is False
            assert result["credits_earned"] == 0

        # Task should still be in verifying state (not completed)
        task_detail = client.get(f"/api/task/{task_id}")
        assert task_detail.status_code == 200
        assert task_detail.json()["status"] in ("verifying", "open")


# ---------------------------------------------------------------------------
# Test 3 â€” Task types all supported
# ---------------------------------------------------------------------------


def test_e2e_all_three_task_types_achieve_consensus():
    """hash_preimage, matrix_verify, and content_verify all support E2E consensus."""
    for task_type in ("hash_preimage", "matrix_verify", "content_verify"):
        with TestClient(app) as client:
            compute_devices = []
            for i in range(3):
                puf = os.urandom(32)
                device_id = f"e2e-type-{task_type[:4]}-{i}"
                _enroll(client, device_id, puf)
                compute_devices.append((device_id, puf))

            task = _create_task(client, task_type=task_type, difficulty=1)
            task_id = task["task_id"]
            expected_hash = task["expected_output_hash"]

            results = [
                _submit_result(client, did, puf, task_id, expected_hash)
                for did, puf in compute_devices
            ]
            assert results[-1]["verified"] is True, (
                f"{task_type}: expected consensus, got {results[-1]}"
            )
            assert results[-1]["credits_earned"] > 0


# ---------------------------------------------------------------------------
# Test 4 â€” Open-tasks endpoint reflects state correctly
# ---------------------------------------------------------------------------


def test_e2e_open_tasks_endpoint_reflects_created_tasks():
    """GET /api/tasks returns newly-created tasks in the open pool."""
    with TestClient(app) as client:
        before = client.get("/api/tasks").json()
        before_count = before["open_count"]

        task = _create_task(client, task_type="hash_preimage", difficulty=1)
        task_id = task["task_id"]

        after = client.get("/api/tasks").json()
        assert after["open_count"] >= before_count
        task_ids = [t["task_id"] for t in after["tasks"]]
        assert task_id in task_ids


# ---------------------------------------------------------------------------
# Test 5 â€” Status endpoint reflects task and supply data
# ---------------------------------------------------------------------------


def test_e2e_status_reflects_task_lifecycle():
    """GET /api/status tracks task counts and supply correctly through the lifecycle."""
    with TestClient(app) as client:
        status_before = client.get("/api/status").json()
        supply_before = status_before["tasks"].get("total_minted", 0)

        # Drive a consensus
        devices = []
        for i in range(3):
            puf = os.urandom(32)
            _enroll(client, f"e2e-status-{i}", puf)
            devices.append((f"e2e-status-{i}", puf))

        task = _create_task(client)
        task_id = task["task_id"]
        expected_hash = task["expected_output_hash"]
        for did, puf in devices:
            _submit_result(client, did, puf, task_id, expected_hash)

        status_after = client.get("/api/status").json()
        supply_after = status_after["tasks"].get("total_minted", 0)
        # Credits were minted
        assert supply_after > supply_before
        # At least one task is now completed
        assert status_after["tasks"]["completed"] >= 1
