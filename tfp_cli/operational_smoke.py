"""Check real HTTP operations and task/accounting recovery across process restart."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

from tfp_client.lib.compute.task_executor import TaskSpec, execute_task
from .smoke import _check, demo_server


class Node:
    def __init__(self, base, secret):
        self.base, self.secret = base, secret

    def call(self, path, payload=None, message=None, expected=200, raw=False):
        headers = {"Content-Type": "application/json"}
        if message is not None:
            headers["X-Device-Sig"] = hmac.new(self.secret, message.encode(), hashlib.sha256).hexdigest()
        request = urllib.request.Request(self.base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read().decode()
            _check(response.status == expected, f"{path}: expected {expected}, got {response.status}: {body}")
        return body if raw else json.loads(body)

    def surfaces(self):
        _check(self.call("/health")["status"] == "ok", "unhealthy node")
        status = self.call("/api/status")
        _check(status["supply_cap"] == 21_000_000 and status["version"], "invalid status")
        for path in ("/admin", "/docs", "/api/tasks", "/api/devices", "/api/content"):
            self.call(path, raw=True)
        _check("entries" in self.call("/api/discovery"), "missing discovery entries")
        for path, payload in (
            ("/api/search/semantic", {"device_id": "unauthenticated", "query": "test"}),
            ("/api/admin/rag/reindex", {"device_id": "unauthenticated"}),
        ):
            self.call(path, payload, expected=401)
        metrics = self.metrics()
        _check(len(metrics) >= 12, "too few metrics")
        return metrics

    def metrics(self):
        return {parts[0]: float(parts[1]) for line in self.call("/metrics", raw=True).splitlines()
                if line.startswith("tfp_") and len(parts := line.split()) == 2}

    def balance(self, device):
        return self.call(f"/api/device/{device}")["credits_balance"]

    def task(self):
        return self.call("/api/task", {"task_type": "content_verify", "difficulty": 1})["task_id"]

    def execute(self, task, device):
        detail = self.call(f"/api/task/{task}")
        spec = TaskSpec.from_dict({**detail, "expected_output_hash": ""})
        result = execute_task(spec, timeout_s=5)
        return self.call(f"/api/task/{task}/result", {
            "device_id": device, "output_hash": result.output_hash,
            "exec_time_s": result.execution_time_s,
        }, f"{device}:{task}")


def run_operational_smoke():
    secret = os.urandom(32)
    devices = ["ops-worker-0", "ops-worker-1", "ops-worker-2"]
    content = "Persistent operational check: café, 水."
    with tempfile.TemporaryDirectory(prefix="tfp-ops-") as directory:
        with demo_server(Path(directory)) as base:
            node = Node(base, secret)
            node.surfaces()
            for device in devices:
                node.call("/api/enroll", {"device_id": device, "puf_entropy_hex": secret.hex()})
            root = node.call("/api/publish", {"device_id": devices[0], "title": "ops", "text": content, "tags": ["ops"]}, f"{devices[0]}:ops")["root_hash"]
            completed = node.task()
            for device in devices:
                result = node.execute(completed, device)
            _check(result["verified"], "no consensus from executed results")
            for device in devices:
                before = node.balance(device)
                _check(before > 0, "participant was not rewarded")
                text = node.call(f"/api/get/{root}?device_id={device}", message=f"{device}:{root}")["text"]
                _check(text == content and node.balance(device) == before - 1, "retrieval or debit failed")
            pending = node.task()
            for device in devices[:2]:
                _check(not node.execute(pending, device)["verified"], "premature consensus")
            opened = node.task()
            balances = [node.balance(d) for d in devices]
            metrics = node.metrics()
        # demo_server has stopped and reaped the old process. Reopen the same DB.
        with demo_server(Path(directory)) as base:
            node = Node(base, secret)
            recovered_metrics = node.surfaces()
            _check([node.balance(d) for d in devices] == balances, "balances changed across restart")
            for name in ("tfp_tasks_completed_total", "tfp_results_submitted_total", "tfp_credits_minted_total", "tfp_content_published_total", "tfp_devices_enrolled_total"):
                _check(recovered_metrics[name] == metrics[name], f"persisted metric lost: {name}")
            for task, state in ((completed, "completed"), (pending, "verifying"), (opened, "open")):
                _check(node.call(f"/api/task/{task}")["status"] == state, f"lost {state} task")
            _check(node.execute(completed, devices[0])["credits_earned"] == 0, "replay minted twice")
            _check(node.execute(pending, devices[2])["verified"], "persisted quorum proofs were lost")
            for device, old_balance in zip(devices, balances):
                _check(node.balance(device) > old_balance, "recovered consensus did not pay every participant")
                response = node.call(f"/api/get/{root}?device_id={device}", message=f"{device}:{root}")
                _check(response["text"] == content, "content did not survive restart")
    return {"passed": True, "checks": ["fresh and restarted operational surfaces", "unauthenticated optional endpoints rejected", "actual task execution and all-participant rewards", "exact content and debit", "balances and five persisted counters", "open/completed/verifying task recovery", "persisted quorum completion", "completed-task replay without reward"], "scope": "two real local server processes, one temporary SQLite directory; no external networks, Docker, or physical worker fleet"}


def main():
    try:
        result = run_operational_smoke()
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
