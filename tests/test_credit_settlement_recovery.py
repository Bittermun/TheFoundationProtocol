"""Durable accounting must survive failures without lost or duplicate credits."""

import hashlib
import hmac
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from tfp_demo import server

SECRET = bytes(range(32))


@pytest.fixture(autouse=True)
def isolated_node(monkeypatch, tmp_path):
    monkeypatch.setenv("TFP_DB_PATH", str(tmp_path / "node.db"))
    monkeypatch.setenv("TFP_MODE", "demo")
    for flag in ("TFP_ENABLE_IPFS", "TFP_ENABLE_NOSTR", "TFP_ENABLE_MAINTENANCE"):
        monkeypatch.setenv(flag, "0")
    monkeypatch.delenv("TFP_DATABASE_URL", raising=False)


def headers(message):
    return {"X-Device-Sig": hmac.new(SECRET, message.encode(), hashlib.sha256).hexdigest()}


def enroll(client, device="worker"):
    response = client.post("/api/enroll", json={"device_id": device, "puf_entropy_hex": SECRET.hex()})
    assert response.status_code == 200


def balance(client, device="worker"):
    return client.get(f"/api/device/{device}").json()["credits_balance"]


def grant(client):
    return client.post("/api/earn", json={"device_id": "worker", "task_id": "allowance"}, headers=headers("worker:allowance"))


def submit(client, task, device):
    return client.post(f"/api/task/{task['task_id']}/result", json={
        "device_id": device, "output_hash": task["expected_output_hash"], "exec_time_s": 0.1,
    }, headers=headers(f"{device}:{task['task_id']}"))


def ready_task(client):
    for device in ("one", "two", "three"):
        enroll(client, device)
    task = client.post("/api/task", json={"task_type": "content_verify", "difficulty": 1}).json()
    for device in ("one", "two"):
        assert submit(client, task, device).status_code == 200
    return task


def fail_save_once(monkeypatch):
    original = server._credit_store.save
    calls = []

    def save(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("injected storage failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(server._credit_store, "save", save)


def test_failed_grant_rolls_back_balance_supply_and_claim(monkeypatch):
    with TestClient(server.app, raise_server_exceptions=False) as client:
        enroll(client)
        fail_save_once(monkeypatch)
        assert grant(client).status_code == 500
        assert balance(client) == 0
        assert server._task_store.get_total_minted() == 0
        assert grant(client).status_code == 200
        assert balance(client) == 10
        assert server._task_store.get_total_minted() == 10


def test_failed_debit_can_be_retried_without_losing_credit(monkeypatch):
    with TestClient(server.app, raise_server_exceptions=False) as client:
        enroll(client)
        assert grant(client).status_code == 200
        root = client.get("/api/content").json()["items"][0]["root_hash"]
        fail_save_once(monkeypatch)
        def read():
            return client.get(f"/api/get/{root}", params={"device_id": "worker"}, headers=headers(f"worker:{root}"))
        assert read().status_code == 500
        assert balance(client) == 10
        assert read().status_code == 200
        assert balance(client) == 9


def test_all_qualifying_participants_receive_reward_once():
    with TestClient(server.app) as client:
        task = ready_task(client)
        response = submit(client, task, "three")
        assert response.status_code == 200
        credits = response.json()["credits_earned"]
        assert credits > 0
        assert [balance(client, d) for d in ("one", "two", "three")] == [credits] * 3
        total = server._task_store.get_total_minted()
        retry = submit(client, task, "three")
        assert retry.status_code == 200
        assert retry.json()["credits_earned"] == 0
        assert server._task_store.get_total_minted() == total == credits * 3


def test_failed_task_reward_is_recovered_on_restart(monkeypatch):
    with TestClient(server.app, raise_server_exceptions=False) as client:
        task = ready_task(client)
        fail_save_once(monkeypatch)
        assert submit(client, task, "three").status_code == 500
        assert [balance(client, d) for d in ("one", "two", "three")] == [0] * 3
        assert server._task_store.get_total_minted() == 0
    with TestClient(server.app) as client:
        amounts = [balance(client, d) for d in ("one", "two", "three")]
        assert amounts[0] > 0 and len(set(amounts)) == 1
        assert server._task_store.get_total_minted() == sum(amounts)
        assert submit(client, task, "one").json()["credits_earned"] == 0


def test_task_reward_failure_can_be_retried_without_restart(monkeypatch):
    with TestClient(server.app, raise_server_exceptions=False) as client:
        task = ready_task(client)
        fail_save_once(monkeypatch)
        assert submit(client, task, "three").status_code == 500
        response = submit(client, task, "three")
        assert response.status_code == 200
        amounts = [balance(client, d) for d in ("one", "two", "three")]
        assert amounts[0] > 0 and len(set(amounts)) == 1
        assert server._task_store.get_total_minted() == sum(amounts)


@pytest.mark.parametrize("boundary", ["quorum", "uncommitted_rewards", "committed_rewards"])
def test_actual_process_exit_recovers_every_task_reward(boundary):
    with TestClient(server.app) as client:
        task = ready_task(client)
    # Deliberately terminate our child without lifespan cleanup or exception
    # handling. Its SQLite recovery is exercised by a new node below.
    code = r'''
import os, sys
from pathlib import Path
sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tfp-foundation-protocol")]
from fastapi.testclient import TestClient
from tfp_demo import server
import hashlib, hmac
boundary, task_id, output_hash = sys.argv[1:]
with TestClient(server.app) as client:
    if boundary == "quorum":
        server._task_store._finish_consensus = lambda *args: os._exit(73)
    elif boundary == "uncommitted_rewards":
        original = server._credit_store.save
        def crash_save(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(73)
        server._credit_store.save = crash_save
    else:
        original = server._settle_task_rewards
        def crash_after_commit(*args):
            original(*args)
            os._exit(73)
        server._settle_task_rewards = crash_after_commit
    signature = hmac.new(bytes(range(32)), f"three:{task_id}".encode(), hashlib.sha256).hexdigest()
    client.post(f"/api/task/{task_id}/result", json={"device_id": "three", "output_hash": output_hash, "exec_time_s": 0.1}, headers={"X-Device-Sig": signature})
'''
    child = subprocess.run(
        [sys.executable, "-c", code, boundary, task["task_id"], task["expected_output_hash"]],
        cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(),
        capture_output=True, text=True, timeout=20,
    )
    assert child.returncode == 73, child.stderr
    with TestClient(server.app) as client:
        amounts = [balance(client, d) for d in ("one", "two", "three")]
        assert amounts[0] > 0 and len(set(amounts)) == 1
        assert server._task_store.get_total_minted() == sum(amounts)
        assert submit(client, task, "three").json()["credits_earned"] == 0
        assert server._task_store.get_total_minted() == sum(amounts)


def test_insufficient_supply_keeps_all_rewards_pending():
    with TestClient(server.app) as client:
        task = ready_task(client)
        server._task_store.increment_total_minted(server.MAX_SUPPLY - 30)
        assert submit(client, task, "three").status_code == 503
        assert [balance(client, d) for d in ("one", "two", "three")] == [0] * 3
        assert server._task_store.get_total_minted() == server.MAX_SUPPLY - 30
        conn = server._credit_store._conn
        assert conn.execute("SELECT COUNT(*) FROM task_rewards WHERE settled = 0").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM earn_log WHERE task_id LIKE 'compute:%'").fetchone()[0] == 0


def test_agreement_on_incorrect_answer_cannot_mint():
    with TestClient(server.app) as client:
        for device in ("one", "two", "three"):
            enroll(client, device)
        task = client.post("/api/task", json={"task_type": "content_verify", "difficulty": 1}).json()
        task["expected_output_hash"] = "0" * 64
        for device in ("one", "two", "three"):
            response = submit(client, task, device)
            assert response.status_code == 200
            assert response.json()["verified"] is False
        assert server._task_store.get_total_minted() == 0


def test_invalid_delegation_does_not_consume_credits():
    with TestClient(server.app) as client:
        enroll(client)
        assert grant(client).status_code == 200
        payload = {"device_id": "worker", "circuit": "demo", "private_claim_hex": "zz"}
        response = client.post("/api/delegate-proof", json=payload, headers=headers("worker:demo"))
        assert response.status_code == 400
        root = client.get("/api/content").json()["items"][0]["root_hash"]
        response = client.get(f"/api/get/{root}", params={"device_id": "worker"}, headers=headers(f"worker:{root}"))
        assert response.status_code == 200
        assert balance(client) == 9
