# SPDX-License-Identifier: Apache-2.0
"""Phase B tests: supported deployment specification and receiver server provisioning."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from tfp_core_v4.cli import main
from tfp_core_v4.visualizer_server import get_static_assets_dir


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_deployment_specification_document_covers_required_scenarios():
    repo_root = Path(__file__).resolve().parent.parent
    doc_path = repo_root / "docs" / "device_to_phone_deployment.md"
    assert doc_path.is_file(), "Phase B deployment specification must exist"
    text = doc_path.read_text(encoding="utf-8")

    # Verify both scenarios and all 6 required dimensions + named targets are documented
    for required_phrase in (
        "Prepared-Phone Scenario",
        "Fresh-Phone Scenario",
        "Android 11+",
        "iOS / iPadOS 16.4+",
        "How the Application Is Obtained",
        "How Microphone Access Becomes Available",
        "What the User Must Do",
        "How the Publisher Key Becomes Trusted",
        "What Must Remain Available During the Outage",
        "Lifecycle Behavior Under Closure, Reboot, Permission Revocation, or Storage Eviction",
    ):
        assert required_phrase in text, f"Missing required Phase B section/phrase: {required_phrase}"


def test_static_default_receiver_config_exists_and_is_valid():
    static_dir = get_static_assets_dir()
    cfg_path = static_dir / "receiver_config.json"
    assert cfg_path.is_file()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["version"] == 1
    assert cfg["cache_version"] == "tfp-acoustic-receiver-v1"
    assert cfg["deployment_mode"] == "prepared_phone_baseline"
    assert isinstance(cfg["trusted_publishers"], list)


def test_acoustic_receiver_cli_rejects_invalid_pubkey_and_incomplete_tls(capsys):
    with pytest.raises(SystemExit) as exc1:
        main(["acoustic-receiver", "--no-browser", "--trusted-pubkey", "not-a-64-char-hex-key"])
    assert exc1.value.code == 1
    assert "Invalid Ed25519 public key hex" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc2:
        main(["acoustic-receiver", "--no-browser", "--tls-cert", "only_cert.pem"])
    assert exc2.value.code == 1
    assert "Both --tls-cert and --tls-key must be provided together" in capsys.readouterr().err


def test_acoustic_receiver_serves_provisioned_trusted_publishers():
    port = _free_port()
    pub1 = "a1" * 32
    pub2 = "b2" * 32
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tfp_core_v4.cli",
            "acoustic-receiver",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
            "--trusted-pubkey",
            f"{pub1},{pub2}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/receiver_config.json"
        deadline = time.time() + 5.0
        payload = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    break
            except Exception:
                time.sleep(0.1)
        assert payload is not None, "Failed to fetch /receiver_config.json from acoustic-receiver"
        assert payload["trusted_publishers"] == [pub1, pub2]
        assert payload["deployment_mode"] == "prepared_phone_baseline"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
