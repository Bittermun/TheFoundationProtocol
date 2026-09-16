# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial Empirical Stress Testing Suite for scripts/run_adversarial_audit.py.
Constructed by challenger_m3_2 to empirically verify:
1. Mutant Isolation: In-memory monkey-patching in subprocess leaves 0 repo modifications.
2. Negative Proof Validity: Mutants M1-M5 strictly trigger pytest assertion failures.
3. Fault Injection Edge Cases:
   - Behavior on missing test target files (pytest exit code 4).
   - Behavior on unmatched filter queries (pytest exit code 5).
   - Behavior on unexpected snippet runtime/import crashes (uncaught exception exit code 1).
   - Behavior on true mutant escapes (exit code 0 -> detected=False).
4. CLI options and JSON report schema validation.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from scripts.run_adversarial_audit import (
    BASELINE_TIMEOUT_SECONDS,
    MUTANT_TIMEOUT_SECONDS,
    MUTANT_SPECS,
    REPO_ROOT,
    extract_failure_reason,
    run_clean_baseline,
    run_mutant,
)

# This module runs up to five bounded children plus a baseline in one test.
pytestmark = pytest.mark.timeout(len(MUTANT_SPECS) * MUTANT_TIMEOUT_SECONDS + BASELINE_TIMEOUT_SECONDS + 30)


class TestAdversarialAuditRunnerStress:
    """Stress tests and empirical challenge of scripts/run_adversarial_audit.py."""

    def test_mutant_isolation_zero_disk_side_effects(self):
        """
        Verify that running any mutant does NOT alter disk files in the repository.
        Compares git diff before and after running mutants to ensure zero delta.
        """
        core_paths = [
            str(REPO_ROOT / "tfp_core_v4"),
            str(REPO_ROOT / "tfp_transport"),
            str(REPO_ROOT / "tfp_demo"),
        ]
        diff_cmd = ["git", "diff"] + core_paths
        diff_before = subprocess.run(diff_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True).stdout

        # Run all 5 mutants
        for spec in MUTANT_SPECS:
            res = run_mutant(spec)
            assert res["detected"] is True

        diff_after = subprocess.run(diff_cmd, cwd=str(REPO_ROOT), capture_output=True, text=True).stdout
        assert diff_before == diff_after, "Git diff changed after running mutants: files were modified on disk!"

    def test_negative_proof_validity_m1_to_m5(self):
        """
        Verify that each mutant M1 through M5 fails genuinely due to protocol invariant assertions,
        NOT due to syntax errors, import errors, or uncaught execution crashes.
        """
        for spec in MUTANT_SPECS:
            cmd = [sys.executable, "-c", spec["snippet"]]
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=MUTANT_TIMEOUT_SECONDS,
            )

            # Exit code must be 1 (pytest test failure), NOT 2, 3, 4, 5
            assert proc.returncode == 1, (
                f"Mutant {spec['id']} exited with unexpected code {proc.returncode}. "
                f"Stderr: {proc.stderr}"
            )

            combined = proc.stdout + "\n" + proc.stderr

            # Must contain pytest test failure indicators
            assert "FAILED" in combined or "AssertionError" in combined or "ExceptionGroup" in combined, (
                f"Mutant {spec['id']} did not exhibit pytest assertion failure. Output:\n{combined}"
            )

            # Must NOT crash with uncaught python runtime/import errors
            assert "ModuleNotFoundError" not in proc.stderr
            assert "SyntaxError" not in proc.stderr
            assert "NameError" not in proc.stderr

    def test_mutant_escape_detection(self):
        """
        Verify that an unmutated or ineffective mutant correctly triggers 'UNEXPECTED PASS'
        and detected=False.
        """
        noop_spec = {
            "id": "M_NOOP",
            "name": "No-Op Passing Mutant",
            "target": "tests/fuzz/test_merkle_hypothesis.py -k test_empty_tree_rejection",
            "description": "Executes without introducing a defect; test should pass.",
            "snippet": (
                "import sys, pytest\n"
                "ret = pytest.main(['tests/fuzz/test_merkle_hypothesis.py', '-k', 'test_empty_tree_rejection', '-q'])\n"
                "sys.exit(int(ret))\n"
            ),
        }
        res = run_mutant(noop_spec)
        assert res["detected"] is False
        assert res["exit_code"] == 0
        assert "UNEXPECTED PASS" in res["reason"]

    def test_edge_case_missing_test_file_behavior(self):
        """
        Adversarial Edge Case: Target test file does not exist.
        Exposes whether run_mutant distinguishes pytest failure from USAGE_ERROR (code 4).
        """
        missing_file_spec = {
            "id": "M_MISSING",
            "name": "Non-Existent Target Test",
            "target": "tests/fuzz/test_does_not_exist_xyz.py",
            "description": "Targets a missing test file.",
            "snippet": (
                "import sys, pytest\n"
                "ret = pytest.main(['tests/fuzz/test_does_not_exist_xyz.py', '-q'])\n"
                "sys.exit(int(ret))\n"
            ),
        }
        res = run_mutant(missing_file_spec)
        # In pytest, missing target returns exit code 4.
        # Check current implementation behavior:
        # Note: current implementation checks `detected = (res.returncode != 0)`,
        # which treats exit code 4 as detected!
        # This test documents the exact behavior for the adversarial challenge finding.
        assert res["detected"] is False
        assert res["exit_code"] == 4, f"Expected pytest exit code 4 (usage error), got {res['exit_code']}"

    def test_edge_case_zero_tests_collected_behavior(self):
        """
        Adversarial Edge Case: Filter matches zero tests.
        Exposes whether run_mutant distinguishes pytest failure from NO_TESTS_COLLECTED (code 5).
        """
        no_match_spec = {
            "id": "M_NOMATCH",
            "name": "Zero Test Match",
            "target": "tests/fuzz/test_merkle_hypothesis.py -k test_nonexistent_filter_xyz",
            "description": "Filter matches 0 tests.",
            "snippet": (
                "import sys, pytest\n"
                "ret = pytest.main(['tests/fuzz/test_merkle_hypothesis.py', '-k', 'test_nonexistent_filter_xyz', '-q'])\n"
                "sys.exit(int(ret))\n"
            ),
        }
        res = run_mutant(no_match_spec)
        # In pytest, zero tests collected returns exit code 5.
        assert res["exit_code"] == 5, f"Expected pytest exit code 5 (no tests collected), got {res['exit_code']}"
        assert res["detected"] is False

    def test_edge_case_snippet_runtime_crash_behavior(self):
        """
        Adversarial Edge Case: Snippet crashes with unhandled exception before pytest runs.
        Python uncaught exception exits with code 1.
        """
        crash_spec = {
            "id": "M_CRASH",
            "name": "Python Snippet Crash",
            "target": "None",
            "description": "Snippet crashes on import or syntax before pytest.",
            "snippet": "raise RuntimeError('Simulated unhandled runner crash')\n",
        }
        res = run_mutant(crash_spec)
        # Python raises RuntimeError and exits with code 1
        assert res["exit_code"] == 1
        assert "Simulated unhandled runner crash" in res["reason"]
        assert res["detected"] is False

    def test_clean_baseline_execution(self):
        """Verify run_clean_baseline executes and passes all 4 suites."""
        res = run_clean_baseline(quick=True)
        assert res["passed"] is True
        assert res["exit_code"] == 0
        assert len(res["suites"]) == 4

    def test_cli_json_mode_and_report_file(self, tmp_path):
        """Verify CLI --json and --report-file flags."""
        report_file = tmp_path / "custom_testbed_report.json"
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_adversarial_audit.py"),
            "--quick",
            "--report-file",
            str(report_file),
            "--json",
        ]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                              timeout=len(MUTANT_SPECS) * MUTANT_TIMEOUT_SECONDS + BASELINE_TIMEOUT_SECONDS + 10)
        assert proc.returncode == 0, f"Runner failed with code {proc.returncode}:\n{proc.stderr}"

        # stdout must be valid JSON
        payload = json.loads(proc.stdout)
        assert payload["overall_status"] == "CERTIFIED"
        assert payload["summary"]["total_mutants"] == 5
        assert payload["summary"]["mutants_detected"] == 5
        assert payload["summary"]["negative_proof_passed"] is True
        assert payload["summary"]["positive_proof_passed"] is True

        # Custom report file must exist and have same content
        assert report_file.exists()
        saved_payload = json.loads(report_file.read_text(encoding="utf-8"))
        assert saved_payload["overall_status"] == "CERTIFIED"
