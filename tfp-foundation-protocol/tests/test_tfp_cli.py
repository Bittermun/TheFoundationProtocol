# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import json
import pytest

from tfp_cli.main import main


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "v3.2.0-alpha" in captured.out or "v3.2.0-alpha" in captured.err

    with pytest.raises(SystemExit) as excinfo:
        main(["-v"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "v3.2.0-alpha" in captured.out or "v3.2.0-alpha" in captured.err


def test_cli_publish(monkeypatch, tmp_path, capsys):
    # Point identity storage at a temp dir so tests don't pollute ~/.tfp
    # Set environment variable to use temp directory for identity
    monkeypatch.setenv("HOME", str(tmp_path))

    calls = []

    def fake_post(url, json=None, headers=None, timeout=10):  # noqa: A002
        calls.append(url)
        if url.endswith("/api/enroll"):
            return FakeResponse(200, {"enrolled": True, "device_id": "cli-user"})
        assert url.endswith("/api/publish"), f"Unexpected POST to {url}"
        assert json["title"] == "Demo"
        return FakeResponse(200, {"root_hash": "abc", "status": "broadcasting"})

    monkeypatch.setattr("tfp_cli.main.httpx.post", fake_post)
    code = main(["publish", "--title", "Demo", "--text", "Hello", "--tags", "demo"])
    assert code == 0
    assert '"root_hash": "abc"' in capsys.readouterr().out
    assert any(c.endswith("/api/publish") for c in calls)


def test_cli_get_error(monkeypatch, capsys):
    def fake_get(url, params=None, timeout=10):
        assert "/api/get/" in url
        return FakeResponse(402, {"detail": "earn credits first"})

    monkeypatch.setattr("tfp_cli.main.httpx.get", fake_get)
    code = main(["get", "missing-hash"])
    assert code == 1
    assert '"status_code": 402' in capsys.readouterr().out


def test_cli_run_task(monkeypatch, tmp_path, capsys):
    # Point identity storage at a temp dir so tests don't pollute ~/.tfp
    monkeypatch.setenv("HOME", str(tmp_path))

    calls = []

    def fake_post(url, json=None, headers=None, timeout=10):  # noqa: A002
        calls.append(url)
        if url.endswith("/api/enroll"):
            return FakeResponse(200, {"enrolled": True, "device_id": "cli-user"})
        assert url.endswith("/result"), f"Unexpected POST to {url}"
        assert json["device_id"] == "cli-user"
        return FakeResponse(200, {"verified": True, "credits_earned": 15})

    def fake_get(url, params=None, timeout=10):
        calls.append(url)
        assert url.endswith("/api/task/task-123")
        import json as _json
        spec_input = _json.dumps({
            "seed_hex": "aabbcc",
            "leading_zeros": 4,
        })
        return FakeResponse(200, {
            "task_id": "task-123",
            "task_type": "hash_preimage",
            "difficulty": 1,
            "input_data_hex": spec_input.encode().hex(),
            "expected_output_hash": "a"*64,
            "credit_reward": 15
        })

    from tfp_client.lib.compute.task_executor import ExecutionResult
    def fake_execute_task(spec, timeout_s=30.0):
        return ExecutionResult(
            task_id=spec.task_id,
            task_type=spec.task_type,
            output_hash="a"*64,
            result_bytes=b"result",
            execution_time_s=0.01,
            verified_locally=True
        )

    monkeypatch.setattr("tfp_cli.main.httpx.post", fake_post)
    monkeypatch.setattr("tfp_cli.main.httpx.get", fake_get)
    monkeypatch.setattr("tfp_cli.main.execute_task", fake_execute_task)

    code = main(["run-task", "--task-id", "task-123", "--device-id", "cli-user"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Device: cli-user" in out
    assert "Enrolled" in out
    assert "earned 15 credits" in out


def test_cli_ping(monkeypatch, capsys):
    calls = []
    def fake_get(url, timeout=5.0):
        calls.append(url)
        assert url.endswith("/health")
        return FakeResponse(200, {
            "status": "ok",
            "ready": True,
            "startup_stage": "ready",
            "content_items": 42
        })

    monkeypatch.setattr("tfp_cli.main.httpx.get", fake_get)
    code = main(["ping"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Latency:" in out
    assert "READY" in out
    assert "Content Items: 42" in out


def test_cli_identity_security(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from tfp_cli.main import _load_or_create_identity, IdentityError

    # 1. Plaintext fallback secure permissions check
    res = _load_or_create_identity("device-a")
    assert res["device_id"] == "device-a"
    assert len(res["puf_entropy"]) == 32
    
    path = tmp_path / ".tfp" / "identity.json"
    assert path.exists()
    
    # On non-Windows platforms, we can assert file mode is 0o600
    import sys as _sys
    if _sys.platform != "win32":
        import os as _os
        assert (_os.stat(path).st_mode & 0o777) == 0o600

    # 2. Strict Passphrase Fail Check
    monkeypatch.setenv("TFP_IDENTITY_PASSPHRASE", "securepass")
    
    # Write a dummy encrypted file (identity.enc) which has invalid data
    enc_path = tmp_path / ".tfp" / "identity.enc"
    enc_path.write_bytes(b"invalid_ciphertext_long_enough_to_trigger")

    with pytest.raises(IdentityError) as excinfo:
        _load_or_create_identity("device-a")
    assert "Failed to load encrypted identity" in str(excinfo.value)



