"""The audit must distinguish a detected invariant from a broken runner."""

import sys

import pytest

from scripts import run_adversarial_audit as audit


def spec(snippet):
    return {"id": "regression", "name": "regression", "target": "regression", "description": "regression", "snippet": snippet}


def test_python_crash_is_not_mutation_detection():
    result = audit.run_mutant(spec("raise RuntimeError('runner failed before collecting tests')"))
    assert result["exit_code"] == 1
    assert result["detected"] is False


def test_printed_failure_is_not_pytest_evidence():
    result = audit.run_mutant(spec("print('FAILED fake_test - AssertionError'); raise SystemExit(1)"))
    assert result["detected"] is False


def test_timeout_is_bounded_and_not_detection():
    result = audit.run_mutant(spec("import time; time.sleep(60)"), timeout=0.2)
    assert result["detected"] is False
    assert result["timed_out"] is True
    assert result["exit_code"] is None


def test_baseline_timeout_is_not_a_pass():
    result = audit.run_clean_baseline(timeout=0.2)
    assert result["passed"] is False
    assert result["timed_out"] is True


@pytest.mark.parametrize("json_mode", [False, True])
def test_rejected_cli_returns_failure_in_both_output_modes(monkeypatch, tmp_path, json_mode):
    monkeypatch.setattr(audit, "MUTANT_SPECS", [spec("")])
    monkeypatch.setattr(audit, "run_mutant", lambda _: {"detected": False, "exit_code": 1, "reason": "runner failure"})
    monkeypatch.setattr(audit, "run_clean_baseline", lambda **_: {"passed": True, "exit_code": 0, "summary": "passed"})
    monkeypatch.setattr(sys, "argv", ["audit", "--report-file", str(tmp_path / "report.json")] + (["--json"] if json_mode else []))
    assert audit.main() == 1


def test_report_write_failure_rejects_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "MUTANT_SPECS", [spec("")])
    monkeypatch.setattr(audit, "run_mutant", lambda _: {"detected": True, "exit_code": 1, "reason": "assertion"})
    monkeypatch.setattr(audit, "run_clean_baseline", lambda **_: {"passed": True, "exit_code": 0, "summary": "passed"})
    monkeypatch.setattr(sys, "argv", ["audit", "--json", "--report-file", str(tmp_path)])
    assert audit.main() == 1
