"""Advertised commands must not report success without performing their action."""

import subprocess
import sys
import importlib.util
from pathlib import Path

import pytest

# Other suites import the legacy package under the same name. Load this test
# helper by source path; the commands under test still run in fresh processes.
_spec = importlib.util.spec_from_file_location("root_cli_smoke", Path(__file__).resolve().parents[1] / "tfp_cli" / "smoke.py")
_smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smoke)
demo_server = _smoke.demo_server


@pytest.mark.parametrize("command", ["fetch", "inspect"])
def test_unimplemented_v4_action_reports_failure(command, tmp_path):
    args = [sys.executable, "-m", "tfp_core_v4.cli", command, "0" * 64]
    if command == "fetch":
        args += ["--output", str(tmp_path / "output.bin")]
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "not implemented" in result.stderr.lower()


def test_ping_succeeds_with_ascii_console():
    import os

    with demo_server() as base:
        result = subprocess.run(
            [sys.executable, "-m", "tfp_cli.main", "--api", base, "ping"],
            env={**os.environ, "PYTHONIOENCODING": "ascii"},
            capture_output=True, text=True, timeout=10,
        )
    assert result.returncode == 0, result.stderr
