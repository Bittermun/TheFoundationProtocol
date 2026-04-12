"""
tests/test_habp_consensus.py

Verifies HABP (Hardware-Agnostic Benchmark Proof) consensus rules:
  - Single device cannot self-mint (cannot submit 3 proofs alone — UNIQUE constraint)
  - Two devices are insufficient (threshold = 3)
  - Three devices with identical output hash trigger consensus
  - Conflicting hashes prevent consensus
  - Credits are positive after consensus
"""

import hashlib
import hmac as _hmac
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient
from tfp_client.lib.compute.verify_habp import HABPVerifier, generate_execution_proof
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


def _create_task(client) -> dict:
    r = client.post(
        "/api/task",
        json={"task_type": "content_verify", "difficulty": 1, "seed_hex": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _submit_result(client, device_id, puf, task_id, output_hash) -> dict:
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
# Unit tests — HABPVerifier class
# ---------------------------------------------------------------------------


def test_habp_verifier_requires_three_proofs_for_consensus():
    """verify_consensus returns None until consensus_threshold proofs arrive."""
    verifier = HABPVerifier(consensus_threshold=3, redundancy_factor=5)
    task_id = "unit-task-001"
    output_hash = "a" * 64

    for i in range(2):
        proof = generate_execution_proof(
            device_id=f"dev-{i}",
            task_id=task_id,
            output_data=bytes.fromhex(output_hash),
            execution_time=0.1,
        )
        proof.output_hash = output_hash
        verifier.submit_proof(proof)
        assert verifier.verify_consensus(task_id) is None

    # Third proof triggers consensus
    proof3 = generate_execution_proof(
        device_id="dev-2",
        task_id=task_id,
        output_data=bytes.fromhex(output_hash),
        execution_time=0.1,
    )
    proof3.output_hash = output_hash
    verifier.submit_proof(proof3)
    result = verifier.verify_consensus(task_id)
    assert result is not None
    assert result.verified is True
    assert len(result.matching_devices) == 3


def test_habp_verifier_conflicting_hashes_no_consensus():
    """Three proofs with different output hashes must NOT produce consensus."""
    verifier = HABPVerifier(consensus_threshold=3, redundancy_factor=5)
    task_id = "unit-conflict-task"

    # Each device submits a different hash → no consensus possible
    for i in range(3):
        distinct_hash = hashlib.sha3_256(f"distinct-{i}".encode()).hexdigest()
        proof = generate_execution_proof(
            device_id=f"conflict-dev-{i}",
            task_id=task_id,
            output_data=distinct_hash.encode(),
            execution_time=0.1,
        )
        proof.output_hash = distinct_hash
        verifier.submit_proof(proof)

    result = verifier.verify_consensus(task_id)
    assert result is not None
    assert result.verified is False


def test_habp_verifier_credit_weight_is_positive_on_consensus():
    """A successful consensus must produce credit_weight > 0."""
    verifier = HABPVerifier(consensus_threshold=3)
    task_id = "unit-weight-task"
    output_hash = "b" * 64

    for i in range(3):
        proof = generate_execution_proof(
            device_id=f"w-dev-{i}",
            task_id=task_id,
            output_data=bytes.fromhex(output_hash),
            execution_time=0.1,
        )
        proof.output_hash = output_hash
        verifier.submit_proof(proof)

    result = verifier.verify_consensus(task_id)
    assert result is not None and result.verified
    assert result.credit_weight > 0.0
    assert result.confidence == 1.0


def test_habp_verifier_proof_count():
    """get_proof_count returns the number of submitted proofs."""
    verifier = HABPVerifier()
    task_id = "count-task"
    proof = generate_execution_proof("d0", task_id, b"data", 0.1)
    assert verifier.get_proof_count(task_id) == 0
    verifier.submit_proof(proof)
    assert verifier.get_proof_count(task_id) == 1


# ---------------------------------------------------------------------------
# Integration tests — server endpoint
# ---------------------------------------------------------------------------


def test_single_device_cannot_self_mint():
    """
    A single device submitting the same result twice must receive 409 on the
    second call.  The UNIQUE(task_id, device_id) DB constraint plus the
    rowcount=0 guard in TaskStore.submit_result() prevent a device from
    accumulating multiple HABP proofs and triggering self-mint.
    """
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "self-mint-attacker"
        _enroll(client, device_id, puf)

        task = _create_task(client)
        task_id = task["task_id"]
        output_hash = task["expected_output_hash"]

        # First submission — accepted, no consensus yet (only 1 of 3 required)
        r1 = _submit_result(client, device_id, puf, task_id, output_hash)
        assert r1["verified"] is False
        assert r1["credits_earned"] == 0

        # Second submission — same device, same task.
        # The DB UNIQUE constraint fires (rowcount=0) → 409 before submit_proof is called.
        sig = _sig(puf, f"{device_id}:{task_id}")
        r2 = client.post(
            f"/api/task/{task_id}/result",
            json={
                "device_id": device_id,
                "output_hash": output_hash,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r2.status_code == 409, (
            "Duplicate submission must be rejected with 409 to prevent self-mint"
        )

        # Third submission — still 409, HABP proof count must still be 1
        r3 = client.post(
            f"/api/task/{task_id}/result",
            json={
                "device_id": device_id,
                "output_hash": output_hash,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r3.status_code == 409, (
            "Third submission must also be rejected — device must not accumulate proofs"
        )


def test_two_devices_insufficient_for_consensus():
    """Two matching proofs must not trigger consensus (threshold = 3)."""
    with TestClient(app) as client:
        devices = [(f"two-dev-{i}", os.urandom(32)) for i in range(2)]
        for did, puf in devices:
            _enroll(client, did, puf)

        task = _create_task(client)
        task_id = task["task_id"]
        output_hash = task["expected_output_hash"]

        for did, puf in devices:
            result = _submit_result(client, did, puf, task_id, output_hash)
            assert result["verified"] is False
            assert result["credits_earned"] == 0


def test_three_devices_same_hash_triggers_consensus():
    """Three distinct devices submitting the same output hash trigger consensus."""
    with TestClient(app) as client:
        devices = [(f"three-dev-{i}", os.urandom(32)) for i in range(3)]
        for did, puf in devices:
            _enroll(client, did, puf)

        task = _create_task(client)
        task_id = task["task_id"]
        output_hash = task["expected_output_hash"]

        results = [
            _submit_result(client, did, puf, task_id, output_hash)
            for did, puf in devices
        ]

        # Only 3rd triggers consensus
        assert results[0]["verified"] is False
        assert results[1]["verified"] is False
        assert results[2]["verified"] is True
        assert results[2]["credits_earned"] > 0


def test_consensus_requires_matching_output_hashes():
    """3 proofs with different hashes must not produce consensus."""
    with TestClient(app) as client:
        devices = [(f"mismatch-dev-{i}", os.urandom(32)) for i in range(3)]
        for did, puf in devices:
            _enroll(client, did, puf)

        task = _create_task(client)
        task_id = task["task_id"]

        # Each device submits a different (wrong) hash
        for i, (did, puf) in enumerate(devices):
            wrong_hash = hashlib.sha3_256(f"wrong-{i}".encode()).hexdigest()
            result = _submit_result(client, did, puf, task_id, wrong_hash)
            assert result["credits_earned"] == 0

        # Task must not be completed
        task_detail = client.get(f"/api/task/{task_id}")
        assert task_detail.json()["status"] != "completed"


def test_completed_task_returns_409_on_further_submission():
    """Once a task is completed, further submissions must return 409."""
    with TestClient(app) as client:
        devices = [(f"post-consensus-{i}", os.urandom(32)) for i in range(4)]
        for did, puf in devices:
            _enroll(client, did, puf)

        task = _create_task(client)
        task_id = task["task_id"]
        output_hash = task["expected_output_hash"]

        # Drive to consensus with 3 devices
        for did, puf in devices[:3]:
            _submit_result(client, did, puf, task_id, output_hash)

        # 4th device tries to submit after completion
        did4, puf4 = devices[3]
        sig = _sig(puf4, f"{did4}:{task_id}")
        r4 = client.post(
            f"/api/task/{task_id}/result",
            json={
                "device_id": did4,
                "output_hash": output_hash,
                "exec_time_s": 0.1,
                "has_tee": False,
            },
            headers={"X-Device-Sig": sig},
        )
        assert r4.status_code == 409
