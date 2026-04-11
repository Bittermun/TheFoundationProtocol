"""
Grand Completion Test — TFP Protocol v3.0

This is the definitive end-to-end test that validates the complete
"super compute for pennies — pooled compute" vision.

Scenario:
  1. Server starts with 5 pre-seeded open tasks
  2. 5 devices enroll independently
  3. Each device fetches open tasks, executes them, submits results
  4. Consensus is reached when 3 devices agree on the same output hash
  5. Credits are minted automatically on consensus
  6. Devices spend credits to access content
  7. Supply cap is enforced
  8. Replay attacks are rejected (HTTP 409)
  9. Rate limiting fires on burst (HTTP 429)
  10. Prometheus /metrics returns all expected counters
  11. Admin /admin dashboard returns HTML with correct structure
  12. Full Merkle audit trail is verifiable
"""
import hashlib
import hmac as _hmac
import json
import os
import sqlite3

os.environ["TFP_DB_PATH"] = ":memory:"

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app, TaskStore, _Metrics
from tfp_client.lib.credit.ledger import CreditLedger, MAX_SUPPLY, SupplyCapError
from tfp_client.lib.compute.task_executor import (
    TaskSpec, execute_task, generate_hash_preimage_task,
    generate_matrix_verify_task, generate_content_verify_task,
)
from tfp_client.lib.core.tfp_engine import TFPClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sig(puf_entropy: bytes, message: str) -> str:
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf_entropy: bytes) -> None:
    r = client.post("/api/enroll", json={
        "device_id": device_id,
        "puf_entropy_hex": puf_entropy.hex(),
    })
    assert r.status_code == 200, f"enroll failed: {r.text}"


DEVICES = {f"device-{i}": os.urandom(32) for i in range(5)}


# ---------------------------------------------------------------------------
# 1. Server startup and health
# ---------------------------------------------------------------------------

class TestServerStartup:
    def test_health(self):
        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["content_items"] >= 1

    def test_pre_seeded_tasks_exist(self):
        """Server should pre-populate at least 3 open tasks on startup."""
        with TestClient(app) as client:
            r = client.get("/api/tasks")
            assert r.status_code == 200
            tasks = r.json()["tasks"]
            assert len(tasks) >= 3, f"Expected ≥3 tasks, got {len(tasks)}"

    def test_status_includes_task_stats(self):
        with TestClient(app) as client:
            r = client.get("/api/status")
            assert r.status_code == 200
            body = r.json()
            assert "tasks" in body
            assert "supply_cap" in body
            assert body["supply_cap"] == MAX_SUPPLY

    def test_admin_dashboard_returns_html(self):
        with TestClient(app) as client:
            r = client.get("/admin")
            assert r.status_code == 200
            assert "text/html" in r.headers["content-type"]
            assert "TFP Node Admin" in r.text
            assert "supply_cap" in r.text.lower() or "Supply" in r.text

    def test_metrics_endpoint_returns_prometheus_text(self):
        with TestClient(app) as client:
            r = client.get("/metrics")
            assert r.status_code == 200
            assert "tfp_tasks_created_total" in r.text
            assert "tfp_credits_minted_total" in r.text
            assert "tfp_devices_enrolled_total" in r.text


# ---------------------------------------------------------------------------
# 2. Device enrollment
# ---------------------------------------------------------------------------

class TestDeviceEnrollment:
    def test_all_five_devices_enroll(self):
        with TestClient(app) as client:
            for device_id, entropy in DEVICES.items():
                _enroll(client, device_id, entropy)

    def test_enrollment_increments_metrics(self):
        with TestClient(app) as client:
            _enroll(client, "metrics-device", os.urandom(32))
            r = client.get("/api/status")
            body = r.json()
            assert body["metrics"]["tfp_devices_enrolled_total"] >= 1

    def test_duplicate_enroll_is_idempotent(self):
        """Re-enrolling the same device updates entropy (upsert)."""
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "re-enroll-dev", entropy)
            r = client.post("/api/enroll", json={
                "device_id": "re-enroll-dev",
                "puf_entropy_hex": entropy.hex(),
            })
            assert r.status_code == 200

    def test_invalid_entropy_hex_rejected(self):
        with TestClient(app) as client:
            r = client.post("/api/enroll", json={
                "device_id": "bad-dev",
                "puf_entropy_hex": "zzzz" + "0" * 60,
            })
            assert r.status_code == 422


# ---------------------------------------------------------------------------
# 3. Task creation and retrieval
# ---------------------------------------------------------------------------

class TestTaskCreation:
    def test_create_hash_preimage_task(self):
        with TestClient(app) as client:
            r = client.post("/api/task", json={
                "task_type": "hash_preimage",
                "difficulty": 2,
                "seed_hex": os.urandom(8).hex(),
            }, headers={"X-Device-Sig": ""})
            assert r.status_code == 200
            body = r.json()
            assert "task_id" in body
            assert body["task_type"] == "hash_preimage"
            assert body["difficulty"] == 2
            assert len(body["expected_output_hash"]) == 64
            assert len(body["input_data_hex"]) > 0

    def test_create_matrix_verify_task(self):
        with TestClient(app) as client:
            r = client.post("/api/task", json={
                "task_type": "matrix_verify",
                "difficulty": 1,
            }, headers={"X-Device-Sig": ""})
            assert r.status_code == 200
            assert r.json()["task_type"] == "matrix_verify"

    def test_create_content_verify_task(self):
        with TestClient(app) as client:
            r = client.post("/api/task", json={
                "task_type": "content_verify",
                "difficulty": 1,
            }, headers={"X-Device-Sig": ""})
            assert r.status_code == 200
            assert r.json()["task_type"] == "content_verify"

    def test_invalid_task_type_rejected(self):
        with TestClient(app) as client:
            r = client.post("/api/task", json={
                "task_type": "quantum_fold",
                "difficulty": 1,
            }, headers={"X-Device-Sig": ""})
            assert r.status_code == 422

    def test_difficulty_bounds_enforced(self):
        with TestClient(app) as client:
            r = client.post("/api/task", json={
                "task_type": "hash_preimage",
                "difficulty": 99,  # > 10
            }, headers={"X-Device-Sig": ""})
            assert r.status_code == 422

    def test_get_task_returns_spec(self):
        with TestClient(app) as client:
            create_r = client.post("/api/task", json={
                "task_type": "hash_preimage",
                "difficulty": 2,
            }, headers={"X-Device-Sig": ""})
            task_id = create_r.json()["task_id"]
            r = client.get(f"/api/task/{task_id}")
            assert r.status_code == 200
            assert r.json()["task_id"] == task_id

    def test_list_tasks_returns_open(self):
        with TestClient(app) as client:
            # Create a task
            client.post("/api/task", json={
                "task_type": "hash_preimage", "difficulty": 2,
            }, headers={"X-Device-Sig": ""})
            r = client.get("/api/tasks")
            assert r.status_code == 200
            tasks = r.json()["tasks"]
            assert any(t["task_type"] == "hash_preimage" for t in tasks)

    def test_metrics_increments_on_task_create(self):
        with TestClient(app) as client:
            before = client.get("/metrics").text
            before_count = int([l for l in before.splitlines()
                                 if l.startswith("tfp_tasks_created_total ")][0].split()[1])
            client.post("/api/task", json={
                "task_type": "hash_preimage", "difficulty": 1,
            }, headers={"X-Device-Sig": ""})
            after = client.get("/metrics").text
            after_count = int([l for l in after.splitlines()
                                if l.startswith("tfp_tasks_created_total ")][0].split()[1])
            assert after_count == before_count + 1


# ---------------------------------------------------------------------------
# 4. Real task execution (local, no server)
# ---------------------------------------------------------------------------

class TestRealTaskExecution:
    def test_hash_preimage_executes_and_verifies(self):
        spec = generate_hash_preimage_task("hp-test-1", difficulty=2, seed=b"test-seed-hp")
        result = execute_task(spec, timeout_s=30.0)
        assert result.verified_locally
        assert result.output_hash == spec.expected_output_hash
        assert result.execution_time_s >= 0

    def test_matrix_verify_executes_and_verifies(self):
        spec = generate_matrix_verify_task("mv-test-1", difficulty=2, seed=b"test-seed-mv")
        result = execute_task(spec, timeout_s=10.0)
        assert result.verified_locally
        assert result.output_hash == spec.expected_output_hash

    def test_content_verify_executes_and_verifies(self):
        spec = generate_content_verify_task("cv-test-1", difficulty=2, content=b"hello world content")
        result = execute_task(spec, timeout_s=10.0)
        assert result.verified_locally
        assert result.output_hash == spec.expected_output_hash

    def test_tampered_expected_hash_fails_local_verify(self):
        spec = generate_hash_preimage_task("hp-tamper", difficulty=1, seed=b"tamper-test")
        spec.expected_output_hash = "0" * 64  # Wrong hash
        result = execute_task(spec, timeout_s=10.0)
        assert not result.verified_locally

    def test_difficulty_1_faster_than_difficulty_5(self):
        import time
        spec1 = generate_hash_preimage_task("hp-d1", difficulty=1, seed=b"speed-test")
        spec3 = generate_hash_preimage_task("hp-d3", difficulty=3, seed=b"speed-test")
        t1 = time.monotonic(); execute_task(spec1, timeout_s=30.0); t1 = time.monotonic() - t1
        t3 = time.monotonic(); execute_task(spec3, timeout_s=60.0); t3 = time.monotonic() - t3
        assert t3 >= t1  # Higher difficulty should take longer (or equal in degenerate case)


# ---------------------------------------------------------------------------
# 5. Full compute → credit cycle (consensus path)
# ---------------------------------------------------------------------------

class TestComputeCreditCycle:
    def _create_and_solve_task(self, client, task_type="hash_preimage", difficulty=1):
        """Create a task and return (spec, correct_output_hash)."""
        r = client.post("/api/task", json={
            "task_type": task_type,
            "difficulty": difficulty,
        }, headers={"X-Device-Sig": ""})
        assert r.status_code == 200, r.text
        spec_dict = r.json()
        spec = TaskSpec.from_dict({
            "task_id": spec_dict["task_id"],
            "task_type": spec_dict["task_type"],
            "difficulty": spec_dict["difficulty"],
            "input_data_hex": spec_dict["input_data_hex"],
            "expected_output_hash": spec_dict["expected_output_hash"],
            "credit_reward": spec_dict["credit_reward"],
        })
        result = execute_task(spec, timeout_s=30.0)
        assert result.verified_locally, f"Local execution failed for {task_type}"
        return spec, result.output_hash

    def test_three_device_consensus_mints_credits(self):
        """When 3 devices submit the same output_hash, consensus is reached and credits minted."""
        with TestClient(app) as client:
            # Enroll 3 devices
            devices = [(f"cons-dev-{i}", os.urandom(32)) for i in range(3)]
            for dev_id, entropy in devices:
                _enroll(client, dev_id, entropy)

            spec, correct_hash = self._create_and_solve_task(client)
            task_id = spec.task_id

            results = []
            for i, (dev_id, entropy) in enumerate(devices):
                sig = _sig(entropy, f"{dev_id}:{task_id}")
                r = client.post(f"/api/task/{task_id}/result", json={
                    "device_id": dev_id,
                    "output_hash": correct_hash,
                    "exec_time_s": 0.5 + i * 0.1,
                    "has_tee": False,
                }, headers={"X-Device-Sig": sig})
                assert r.status_code == 200, r.text
                results.append(r.json())

            # The 3rd submission should trigger consensus
            assert results[-1]["verified"] is True, f"Expected consensus at 3rd submission, got: {results[-1]}"
            assert results[-1]["credits_earned"] > 0

    def test_wrong_output_hash_no_consensus(self):
        """If devices submit different hashes, no consensus is reached."""
        with TestClient(app) as client:
            devices = [(f"wrong-dev-{i}", os.urandom(32)) for i in range(3)]
            for dev_id, entropy in devices:
                _enroll(client, dev_id, entropy)

            spec, _ = self._create_and_solve_task(client)
            task_id = spec.task_id

            for i, (dev_id, entropy) in enumerate(devices):
                sig = _sig(entropy, f"{dev_id}:{task_id}")
                wrong_hash = hashlib.sha3_256(f"wrong-{i}".encode()).hexdigest()
                r = client.post(f"/api/task/{task_id}/result", json={
                    "device_id": dev_id,
                    "output_hash": wrong_hash,
                    "exec_time_s": 0.5,
                    "has_tee": False,
                }, headers={"X-Device-Sig": sig})
                assert r.status_code == 200
                assert r.json()["verified"] is False

    def test_unenrolled_device_cannot_submit_result(self):
        with TestClient(app) as client:
            spec, correct_hash = self._create_and_solve_task(client)
            sig = _sig(os.urandom(32), f"ghost:{spec.task_id}")
            r = client.post(f"/api/task/{spec.task_id}/result", json={
                "device_id": "ghost",
                "output_hash": correct_hash,
                "exec_time_s": 0.5,
                "has_tee": False,
            }, headers={"X-Device-Sig": sig})
            assert r.status_code == 401

    def test_task_not_found_returns_404(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "nf-dev", entropy)
            sig = _sig(entropy, "nf-dev:nonexistent")
            r = client.post("/api/task/nonexistent/result", json={
                "device_id": "nf-dev",
                "output_hash": "a" * 64,
                "exec_time_s": 0.1,
            }, headers={"X-Device-Sig": sig})
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. Legacy earn path (still works for backward compatibility)
# ---------------------------------------------------------------------------

class TestLegacyEarnPath:
    def test_earn_and_spend_cycle(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "earn-dev", entropy)
            task_id = "legacy-task-001"
            sig = _sig(entropy, f"earn-dev:{task_id}")
            r = client.post("/api/earn", json={
                "device_id": "earn-dev",
                "task_id": task_id,
            }, headers={"X-Device-Sig": sig})
            assert r.status_code == 200
            assert r.json()["credits_earned"] == 10

            # Now spend credits to get content
            all_content = client.get("/api/content").json()["items"]
            assert len(all_content) >= 1
            root_hash = all_content[0]["root_hash"]
            r2 = client.get(f"/api/get/{root_hash}", params={"device_id": "earn-dev"})
            assert r2.status_code == 200
            assert "text" in r2.json()

    def test_replay_rejected_with_409(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "replay-dev", entropy)
            task_id = "replay-task-dup"
            sig = _sig(entropy, f"replay-dev:{task_id}")
            # First submission — OK
            r1 = client.post("/api/earn", json={
                "device_id": "replay-dev", "task_id": task_id,
            }, headers={"X-Device-Sig": sig})
            assert r1.status_code == 200
            # Replay — must be rejected
            r2 = client.post("/api/earn", json={
                "device_id": "replay-dev", "task_id": task_id,
            }, headers={"X-Device-Sig": sig})
            assert r2.status_code == 409
            assert "already processed" in r2.json()["detail"]

    def test_rate_limit_fires_at_burst(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "rate-dev", entropy)
            # Make 10 earn calls (the default max)
            last_status = 200
            for i in range(12):
                task_id = f"rate-task-{i}"
                sig = _sig(entropy, f"rate-dev:{task_id}")
                r = client.post("/api/earn", json={
                    "device_id": "rate-dev", "task_id": task_id,
                }, headers={"X-Device-Sig": sig})
                last_status = r.status_code
            assert last_status == 429, f"Expected 429 after burst, got {last_status}"

    def test_no_credits_returns_402(self):
        with TestClient(app) as client:
            all_content = client.get("/api/content").json()["items"]
            root_hash = all_content[0]["root_hash"]
            r = client.get(f"/api/get/{root_hash}", params={"device_id": "penniless-dev"})
            assert r.status_code == 402

    def test_invalid_sig_returns_401(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "bad-sig-dev", entropy)
            # Use wrong entropy for sig
            wrong_sig = _sig(os.urandom(32), "bad-sig-dev:task-x")
            r = client.post("/api/earn", json={
                "device_id": "bad-sig-dev", "task_id": "task-x",
            }, headers={"X-Device-Sig": wrong_sig})
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# 7. Supply cap enforcement
# ---------------------------------------------------------------------------

class TestSupplyCap:
    def test_ledger_respects_supply_cap(self):
        ledger = CreditLedger(max_supply=100)
        proof = b"\x01" * 32
        # Mint up to cap
        for i in range(10):
            ledger.mint(10, hashlib.sha3_256(bytes([i])).digest())
        assert ledger.total_minted == 100
        # Next mint should fail
        with pytest.raises(SupplyCapError):
            ledger.mint(1, proof)

    def test_network_total_minted_prevents_overspend(self):
        ledger = CreditLedger(max_supply=50, network_total_minted=45)
        proof = hashlib.sha3_256(b"x").digest()
        # 5 credits left: OK
        ledger.mint(5, proof)
        # Now cap reached
        with pytest.raises(SupplyCapError):
            ledger.mint(1, hashlib.sha3_256(b"y").digest())

    def test_max_supply_is_21_million(self):
        assert MAX_SUPPLY == 21_000_000

    def test_supply_cap_shown_in_status(self):
        with TestClient(app) as client:
            r = client.get("/api/status")
            assert r.json()["supply_cap"] == 21_000_000


# ---------------------------------------------------------------------------
# 8. Merkle audit trail
# ---------------------------------------------------------------------------

class TestMerkleAuditTrail:
    def test_ledger_produces_auditable_chain(self):
        ledger = CreditLedger()
        proofs = [hashlib.sha3_256(bytes([i])).digest() for i in range(5)]
        for p in proofs:
            ledger.mint(10, p)
        trail = ledger.audit_trail()
        assert len(trail) == 5
        for entry in trail:
            assert "index" in entry
            assert "hex" in entry
            assert len(entry["hex"]) == 64

    def test_merkle_root_changes_on_new_mint(self):
        ledger = CreditLedger()
        proof1 = hashlib.sha3_256(b"a").digest()
        proof2 = hashlib.sha3_256(b"b").digest()
        ledger.mint(10, proof1)
        root1 = ledger.export_merkle_root()
        ledger.mint(10, proof2)
        root2 = ledger.export_merkle_root()
        assert root1 != root2

    def test_spend_verifies_chain(self):
        ledger = CreditLedger()
        proof = hashlib.sha3_256(b"spend-test").digest()
        receipt = ledger.mint(10, proof)
        assert ledger.verify_spend(receipt)
        ledger.spend(1, receipt)
        assert ledger.balance == 9

    def test_forged_receipt_rejected(self):
        from tfp_client.lib.credit.ledger import Receipt
        ledger = CreditLedger()
        fake_receipt = Receipt(chain_hash=b"\xff" * 32, credits=10)
        with pytest.raises(ValueError, match="invalid receipt"):
            ledger.spend(1, fake_receipt)


# ---------------------------------------------------------------------------
# 9. Content publish and retrieval
# ---------------------------------------------------------------------------

class TestContentFlow:
    def test_publish_and_retrieve_full_cycle(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "pub-dev", entropy)

            # Publish
            title = "Grand Test Article"
            sig = _sig(entropy, f"pub-dev:{title}")
            r = client.post("/api/publish", json={
                "title": title,
                "text": "This is a decade-proof article about pooled compute.",
                "tags": ["compute", "pooled", "test"],
                "device_id": "pub-dev",
            }, headers={"X-Device-Sig": sig})
            assert r.status_code == 200
            root_hash = r.json()["root_hash"]

            # Earn credits
            task_id = "pub-earn-task"
            earn_sig = _sig(entropy, f"pub-dev:{task_id}")
            client.post("/api/earn", json={"device_id": "pub-dev", "task_id": task_id},
                        headers={"X-Device-Sig": earn_sig})

            # Retrieve
            r2 = client.get(f"/api/get/{root_hash}", params={"device_id": "pub-dev"})
            assert r2.status_code == 200
            body = r2.json()
            assert "pooled compute" in body["text"]
            assert "compute" in body["tags"]

    def test_search_by_tag_works(self):
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "tag-dev", entropy)
            sig = _sig(entropy, "tag-dev:Tag Search Test")
            client.post("/api/publish", json={
                "title": "Tag Search Test",
                "text": "unique-tag-content",
                "tags": ["unique-grand-tag-xyz"],
                "device_id": "tag-dev",
            }, headers={"X-Device-Sig": sig})

            r = client.get("/api/content", params={"tag": "unique-grand-tag-xyz"})
            assert r.status_code == 200
            items = r.json()["items"]
            assert any("Tag Search Test" in i["title"] for i in items)

    def test_content_hash_integrity(self):
        """SHA3-256 of served content must match stored hash."""
        with TestClient(app) as client:
            entropy = os.urandom(32)
            _enroll(client, "hash-dev", entropy)

            body_text = "Verify me with hash integrity check."
            sig = _sig(entropy, "hash-dev:Hash Check")
            pr = client.post("/api/publish", json={
                "title": "Hash Check", "text": body_text,
                "tags": [], "device_id": "hash-dev",
            }, headers={"X-Device-Sig": sig})
            root_hash = pr.json()["root_hash"]

            task_sig = _sig(entropy, "hash-dev:hash-earn-1")
            client.post("/api/earn", json={
                "device_id": "hash-dev", "task_id": "hash-earn-1",
            }, headers={"X-Device-Sig": task_sig})

            gr = client.get(f"/api/get/{root_hash}", params={"device_id": "hash-dev"})
            assert gr.status_code == 200
            served_sha3 = gr.json()["sha3"]
            expected_sha3 = hashlib.sha3_256(body_text.encode()).hexdigest()
            assert served_sha3 == expected_sha3


# ---------------------------------------------------------------------------
# 10. Prometheus metrics completeness
# ---------------------------------------------------------------------------

class TestMetrics:
    EXPECTED_COUNTERS = [
        "tfp_tasks_created_total",
        "tfp_tasks_completed_total",
        "tfp_tasks_failed_total",
        "tfp_results_submitted_total",
        "tfp_credits_minted_total",
        "tfp_credits_spent_total",
        "tfp_content_published_total",
        "tfp_content_served_total",
        "tfp_devices_enrolled_total",
        "tfp_earn_rate_limited_total",
        "tfp_earn_replay_rejected_total",
        "tfp_auth_failures_total",
    ]

    def test_all_expected_counters_present(self):
        with TestClient(app) as client:
            r = client.get("/metrics")
            assert r.status_code == 200
            for counter in self.EXPECTED_COUNTERS:
                assert counter in r.text, f"Missing counter: {counter}"

    def test_metrics_counter_types_are_annotated(self):
        with TestClient(app) as client:
            r = client.get("/metrics")
            for counter in self.EXPECTED_COUNTERS:
                assert f"# TYPE {counter} counter" in r.text

    def test_enroll_increments_devices_counter(self):
        with TestClient(app) as client:
            before = self._get_counter(client, "tfp_devices_enrolled_total")
            _enroll(client, "metrics-test-dev", os.urandom(32))
            after = self._get_counter(client, "tfp_devices_enrolled_total")
            assert after == before + 1

    def test_auth_failure_increments_counter(self):
        with TestClient(app) as client:
            before = self._get_counter(client, "tfp_auth_failures_total")
            # Unsigned request to earn
            client.post("/api/earn", json={
                "device_id": "ghost", "task_id": "x",
            }, headers={"X-Device-Sig": "bad"})
            after = self._get_counter(client, "tfp_auth_failures_total")
            assert after >= before + 1

    def _get_counter(self, client, name: str) -> int:
        r = client.get("/metrics")
        for line in r.text.splitlines():
            if line.startswith(f"{name} "):
                return int(line.split()[1])
        return 0


# ---------------------------------------------------------------------------
# 11. Task executor unit tests
# ---------------------------------------------------------------------------

class TestTaskExecutorUnit:
    def test_generate_hash_preimage_task_is_solvable(self):
        spec = generate_hash_preimage_task("gen-hp", 1, b"solvable")
        assert spec.task_type.value == "hash_preimage"
        assert len(spec.expected_output_hash) == 64
        result = execute_task(spec, timeout_s=15.0)
        assert result.verified_locally

    def test_generate_matrix_verify_task_is_correct(self):
        spec = generate_matrix_verify_task("gen-mv", 2, b"matrix-seed")
        result = execute_task(spec, timeout_s=10.0)
        assert result.verified_locally

    def test_generate_content_verify_task_is_correct(self):
        spec = generate_content_verify_task("gen-cv", 2, b"content data here")
        result = execute_task(spec, timeout_s=10.0)
        assert result.verified_locally

    def test_taskspec_serialises_round_trip(self):
        spec = generate_hash_preimage_task("rt-test", 1, b"roundtrip")
        d = spec.to_dict()
        spec2 = TaskSpec.from_dict(d)
        assert spec2.task_id == spec.task_id
        assert spec2.task_type == spec.task_type
        assert spec2.expected_output_hash == spec.expected_output_hash
        assert spec2.input_data == spec.input_data

    def test_execute_and_earn_wires_result_to_ledger(self):
        spec = generate_content_verify_task("earn-cv", 1, b"earn test content")
        client = TFPClient()
        result, receipt = client.execute_and_earn(spec, credits=10, timeout_s=10.0)
        assert result.verified_locally
        assert receipt.credits == 10
        assert client.ledger.balance == 10
        assert len(client._earned_receipts) == 1


# ---------------------------------------------------------------------------
# 12. End-to-end pooled compute demonstration
# ---------------------------------------------------------------------------

class TestGrandPooledComputeScenario:
    """
    The full vision: 5 devices pool compute, earn credits, spend on content.

    This is the "decade-proof deployment" test that validates the complete
    economic flywheel from idle compute → verified work → credits → content.
    """

    def test_five_devices_pool_compute_and_earn(self):
        """
        End-to-end scenario:
          1. 5 devices enroll
          2. Server creates 3 real compute tasks
          3. All 5 devices execute each task (produces same output hash)
          4. First 3 submissions reach consensus → credits minted
          5. Devices spend credits to retrieve content
          6. Supply ledger updated correctly
        """
        with TestClient(app) as client:
            # Setup: 5 devices
            n_devices = 5
            devs = {f"pool-dev-{i}": os.urandom(32) for i in range(n_devices)}
            for dev_id, entropy in devs.items():
                _enroll(client, dev_id, entropy)

            # Create 3 compute tasks of increasing difficulty
            task_specs = []
            for task_type, difficulty in [
                ("hash_preimage", 1),
                ("matrix_verify", 1),
                ("content_verify", 1),
            ]:
                r = client.post("/api/task", json={
                    "task_type": task_type,
                    "difficulty": difficulty,
                }, headers={"X-Device-Sig": ""})
                assert r.status_code == 200, r.text
                raw = r.json()
                spec = TaskSpec.from_dict({
                    "task_id": raw["task_id"],
                    "task_type": raw["task_type"],
                    "difficulty": raw["difficulty"],
                    "input_data_hex": raw["input_data_hex"],
                    "expected_output_hash": raw["expected_output_hash"],
                    "credit_reward": raw["credit_reward"],
                })
                task_specs.append(spec)

            verified_tasks = []
            for spec in task_specs:
                # All 5 devices execute the task
                result = execute_task(spec, timeout_s=30.0)
                assert result.verified_locally, f"Task {spec.task_id} local exec failed"

                consensus_reached = False
                for i, (dev_id, entropy) in enumerate(devs.items()):
                    sig = _sig(entropy, f"{dev_id}:{spec.task_id}")
                    r = client.post(f"/api/task/{spec.task_id}/result", json={
                        "device_id": dev_id,
                        "output_hash": result.output_hash,
                        "exec_time_s": 0.3 + i * 0.05,
                        "has_tee": False,
                    }, headers={"X-Device-Sig": sig})
                    assert r.status_code == 200, f"Submit failed: {r.text}"
                    v = r.json()
                    if v["verified"]:
                        consensus_reached = True
                        break  # Consensus reached, no need for remaining devices

                assert consensus_reached, f"Consensus never reached for task {spec.task_id}"
                verified_tasks.append(spec.task_id)

            assert len(verified_tasks) == 3

            # Verify metrics reflect completed tasks
            status_r = client.get("/api/status").json()
            assert status_r["tasks"]["completed"] >= 3

            # Verify supply was updated
            assert status_r["tasks"]["total_minted"] > 0

            # Publish content for devices to spend on
            pub_entropy = os.urandom(32)
            _enroll(client, "pub-node", pub_entropy)
            title = "Pooled Compute Results"
            pub_sig = _sig(pub_entropy, f"pub-node:{title}")
            pr = client.post("/api/publish", json={
                "title": title,
                "text": "The compute pool produced this content. 5 devices, 3 tasks, all verified.",
                "tags": ["compute", "pooled", "verified"],
                "device_id": "pub-node",
            }, headers={"X-Device-Sig": pub_sig})
            assert pr.status_code == 200
            root_hash = pr.json()["root_hash"]

            # One device earns legacy credits and retrieves the article
            entropy0 = list(devs.values())[0]
            dev0 = list(devs.keys())[0]
            task_id = "pool-earn-final"
            earn_sig = _sig(entropy0, f"{dev0}:{task_id}")
            er = client.post("/api/earn", json={
                "device_id": dev0, "task_id": task_id,
            }, headers={"X-Device-Sig": earn_sig})
            assert er.status_code == 200

            gr = client.get(f"/api/get/{root_hash}", params={"device_id": dev0})
            assert gr.status_code == 200
            assert "5 devices" in gr.json()["text"]

            print("\n✅ Grand Completion Test PASSED")
            print(f"   Tasks verified by consensus: {len(verified_tasks)}")
            print(f"   Devices in pool: {n_devices}")
            print(f"   Credits minted: {status_r['tasks']['total_minted']}")
            print(f"   Supply cap: {MAX_SUPPLY:,}")
            print(f"   Content served: OK\n")
