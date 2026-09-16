#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Autonomous Adversarial Fault Injection & Invariant Sensitivity Runner for TFP.

Deliberately injects 5 protocol mutations into runtime fixtures to mathematically
prove that invariant test gates trigger detection (Negative Proof), and verifies
that unmutated production code passes all test gates (Positive Proof).

Mutants:
  M1: FastCDC Chunk Boundary Corruption (forces fixed-interval chunking)
  M2: Merkle Root Bit-Flip (corrupts root hash in Merkle levels)
  M3: Nostr Replay & Timestamp Tampering (disables timestamp window guard)
  M4: Excess Loss >40% Low-Redundancy Decode (silent buffer return on rank deficit)
  M5: Droplet Payload Bit-Flip / Forged Seed (bypasses O(1) anti-pollution filter)

Usage:
  python scripts/run_adversarial_audit.py [--quick] [--json] [--report-file <path>]
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
MUTANT_TIMEOUT_SECONDS = 30
BASELINE_TIMEOUT_SECONDS = 120

# Observe real pytest reports instead of trusting text printed by a crashed child.
# The snippets are trusted local audit code; this is not an untrusted-code sandbox.
_OBSERVED_RUNNER = r'''
import json, sys
from pathlib import Path
sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tfp-foundation-protocol")]
import pytest

report_path = Path(sys.argv[2])
state = {"collected": 0, "failures": [], "session_exit": None}

def is_assertion(exc):
    if isinstance(exc, AssertionError):
        return True
    children = getattr(exc, "exceptions", ())
    return bool(children) and all(is_assertion(child) for child in children)

class Observer:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.failed:
            state["failures"].append({
                "nodeid": report.nodeid, "phase": report.when,
                "assertion": call.excinfo is not None and is_assertion(call.excinfo.value),
            })

    def pytest_sessionfinish(self, session, exitstatus):
        state["collected"] = session.testscollected
        state["session_exit"] = int(exitstatus)
        report_path.write_text(json.dumps(state), encoding="utf-8")

original_main = pytest.main
def observed_main(args=None, plugins=None):
    return original_main(args, plugins=list(plugins or []) + [Observer()])
pytest.main = observed_main
exec(compile(sys.argv[1], "<audit-mutation>", "exec"))
'''

MUTANT_SPECS = [
    {
        "id": "M1",
        "name": "FastCDC Chunk Boundary Corruption",
        "target": "tests/fuzz/test_fastcdc_hypothesis.py -k test_boundary_shift_resistance",
        "description": "Forces fixed-interval chunking in FastCDC to break content-defined boundary shift resistance.",
        "snippet": (
            "import sys, pytest\n"
            "from tfp_core_v4 import cdc\n"
            "def fixed_chunk(self, data):\n"
            "    if not data: return []\n"
            "    return [data[i:i + self.target_size] for i in range(0, len(data), self.target_size)]\n"
            "cdc.ContentDefinedChunker.chunk = fixed_chunk\n"
            "ret = pytest.main(['tests/fuzz/test_fastcdc_hypothesis.py', '-k', 'test_boundary_shift_resistance', '-q'])\n"
            "sys.exit(int(ret))\n"
        ),
    },
    {
        "id": "M2",
        "name": "Merkle Root Bit-Flip",
        "target": "tests/fuzz/test_merkle_hypothesis.py -k test_audit_path_correctness_all_leaves",
        "description": "Flips a bit in the root hash level to invalidate all audit path proofs.",
        "snippet": (
            "import sys, pytest\n"
            "from tfp_core_v4 import merkle\n"
            "orig_init = merkle.MerkleTree.__init__\n"
            "def mutated_init(self, leaves):\n"
            "    orig_init(self, leaves)\n"
            "    r = self.levels[-1][0]\n"
            "    self.levels[-1][0] = bytes([r[0] ^ 0x01]) + r[1:]\n"
            "merkle.MerkleTree.__init__ = mutated_init\n"
            "ret = pytest.main(['tests/fuzz/test_merkle_hypothesis.py', '-k', 'test_audit_path_correctness_all_leaves', '-q'])\n"
            "sys.exit(int(ret))\n"
        ),
    },
    {
        "id": "M3",
        "name": "Nostr Signature & Replay Tampering",
        "target": "tests/fuzz/test_nostr_hypothesis.py -k test_replay_window_guard",
        "description": "Bypasses timestamp replay guard to allow events outside the 300s replay window.",
        "snippet": (
            "import sys, pytest\n"
            "from tfp_demo import server\n"
            "server._check_replay_window = lambda event: True\n"
            "ret = pytest.main(['tests/fuzz/test_nostr_hypothesis.py', '-k', 'test_replay_window_guard', '-q'])\n"
            "sys.exit(int(ret))\n"
        ),
    },
    {
        "id": "M4",
        "name": "Excess Loss >40% Low-Redundancy Matrix Inversion Deficit",
        "target": "tests/fuzz/test_fountain_hypothesis.py -k test_gf2_decodability_with_repair_droplets",
        "description": "Suppresses rank deficit ValueError and silently returns corrupted bytes instead of raising an error.",
        "snippet": (
            "import sys, pytest\n"
            "from tfp_core_v4 import fountain\n"
            "orig_decode = fountain.FountainDecoder.decode\n"
            "def silent_corrupt_decode(self, droplets, k, orig_len):\n"
            "    try:\n"
            "        return orig_decode(self, droplets, k, orig_len)\n"
            "    except ValueError:\n"
            "        return b'X' * orig_len\n"
            "fountain.FountainDecoder.decode = silent_corrupt_decode\n"
            "ret = pytest.main(['tests/fuzz/test_fountain_hypothesis.py', '-k', 'test_gf2_decodability_with_repair_droplets', '-q'])\n"
            "sys.exit(int(ret))\n"
        ),
    },
    {
        "id": "M5",
        "name": "Droplet Payload Bit-Flip / Forged Seed Injection",
        "target": "tests/fuzz/test_fountain_hypothesis.py -k test_anti_pollution_prefilter_o1_rejection",
        "description": "Disables O(1) anti-pollution pre-filter check, accepting arbitrary forged seeds and tampered degrees.",
        "snippet": (
            "import sys, pytest\n"
            "from tfp_core_v4 import fountain\n"
            "fountain.verify_droplet_seed_authenticity = lambda *args, **kwargs: True\n"
            "ret = pytest.main(['tests/fuzz/test_fountain_hypothesis.py', '-k', 'test_anti_pollution_prefilter_o1_rejection', '-q'])\n"
            "sys.exit(int(ret))\n"
        ),
    },
]


def extract_failure_reason(output: str) -> str:
    """Extract succinct failure reason from pytest output."""
    lines = output.splitlines()
    for line in lines:
        if line.startswith("E   AssertionError:") or line.startswith("E   ValueError:") or line.startswith("E   KeyError:"):
            return line.strip()
        if "AssertionError" in line or "FAILED" in line:
            if line.strip().startswith("FAILED"):
                return line.strip()
    # Fallback to last non-empty line
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return "Test failed with non-zero exit code"


def run_mutant(spec: Dict[str, Any], *, timeout: float = MUTANT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Execute a single mutation test in an isolated subprocess."""
    with tempfile.TemporaryDirectory(prefix="tfp-audit-") as directory:
        report_path = Path(directory) / "pytest-outcome.json"
        cmd = [sys.executable, "-c", _OBSERVED_RUNNER, spec["snippet"], str(report_path)]
        try:
            res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {
                **{key: spec[key] for key in ("id", "name", "target", "description")},
                "detected": False, "exit_code": None, "timed_out": True,
                "reason": f"EXECUTION TIMEOUT: child exceeded {timeout}s; no mutation detection established",
            }
        try:
            observed = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            observed = {}
    combined = (res.stdout or "") + "\n" + (res.stderr or "")
    failures = observed.get("failures", [])
    has_invariant_failure = bool(failures) and all(
        failure["phase"] == "call" and failure["assertion"] for failure in failures
    )
    detected = (res.returncode == 1 and observed.get("session_exit") == 1
                and observed.get("collected", 0) > 0 and has_invariant_failure)

    if res.returncode == 0:
        reason = "UNEXPECTED PASS: Mutant was not caught by test gate"
    elif res.returncode == 5:
        reason = "TEST COLLECTION FAILURE: Pytest exited with code 5 (no tests collected)"
    elif res.returncode != 1:
        reason = f"EXECUTION ERROR: Pytest exited with code {res.returncode} instead of code 1"
    elif not detected:
        reason = f"NO INVARIANT FAILURE: {extract_failure_reason(combined)}"
    else:
        reason = extract_failure_reason(combined)

    return {
        "id": spec["id"],
        "name": spec["name"],
        "target": spec["target"],
        "description": spec["description"],
        "detected": detected,
        "exit_code": res.returncode,
        "timed_out": False,
        "pytest_outcome": observed,
        "reason": reason,
    }


def run_clean_baseline(quick: bool = False, *, timeout: float = BASELINE_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Execute test suite on unmutated clean code (Positive Proof)."""
    test_files = [
        "tests/fuzz/test_fastcdc_hypothesis.py",
        "tests/fuzz/test_merkle_hypothesis.py",
        "tests/fuzz/test_nostr_hypothesis.py",
        "tests/fuzz/test_fountain_hypothesis.py",
    ]
    cmd = [sys.executable, "-m", "pytest"]
    cmd.extend(test_files)
    cmd.extend(["-q"])
    if quick:
        names = [spec["target"].split(" -k ", 1)[1] for spec in MUTANT_SPECS]
        cmd.extend(["-k", " or ".join(names)])

    try:
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"passed": False, "exit_code": None, "timed_out": True,
                "suites": test_files, "summary": f"Baseline exceeded {timeout}s"}
    passed = (res.returncode == 0)
    return {
        "passed": passed,
        "exit_code": res.returncode,
        "timed_out": False,
        "suites": test_files,
        "summary": (res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "Completed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autonomous Adversarial Fault Injection & Invariant Sensitivity Runner"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run targeted test cases for faster feedback",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON results to stdout",
    )
    parser.add_argument(
        "--report-file",
        type=str,
        default="TESTBED_REPORT.json",
        help="Destination JSON report file (default: TESTBED_REPORT.json)",
    )

    args = parser.parse_args()

    if not args.json:
        print("=" * 75)
        print("TFP Autonomous Adversarial Verification & Mutation Audit Gate")
        print("Protocol Requirement: R3 | Invariant Testing & Fault Injection")
        print("=" * 75)

    mutant_results: List[Dict[str, Any]] = []
    all_mutants_detected = True

    for spec in MUTANT_SPECS:
        if not args.json:
            print(f"[*] Injecting Mutant {spec['id']}: {spec['name']}...")
        res = run_mutant(spec)
        mutant_results.append(res)
        if not res["detected"]:
            all_mutants_detected = False
            if not args.json:
                print(f"    [FAIL] Mutant {spec['id']} escaped detection! Test unexpectedly passed.")
        else:
            if not args.json:
                print(f"    [PASS] Detected (exit code {res['exit_code']}): {res['reason']}")

    if not args.json:
        print("-" * 75)
        print("[*] Running Clean Baseline Verification (Positive Proof)...")

    baseline_res = run_clean_baseline(quick=args.quick)
    clean_passed = baseline_res["passed"]

    if not args.json:
        if clean_passed:
            print(f"    [PASS] Clean Baseline: All invariant suites passed ({baseline_res['summary']})")
        else:
            print(f"    [FAIL] Clean Baseline failed! Exit code: {baseline_res['exit_code']}")
        print("=" * 75)

    overall_status = "CERTIFIED" if (all_mutants_detected and clean_passed) else "REJECTED"

    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "milestone": "Milestone 3 (Requirement R3)",
        "audit_gate": "Autonomous Adversarial Fault Injection",
        "overall_status": overall_status,
        "summary": {
            "total_mutants": len(MUTANT_SPECS),
            "mutants_detected": sum(1 for m in mutant_results if m["detected"]),
            "negative_proof_passed": all_mutants_detected,
            "positive_proof_passed": clean_passed,
        },
        "mutant_results": mutant_results,
        "clean_baseline": baseline_res,
    }

    # Write report file
    try:
        report_path = REPO_ROOT / args.report_file
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        if not args.json:
            print(f"[+] Audit Report written to: {report_path}")
    except Exception as exc:
        overall_status = "REJECTED"
        report_data["overall_status"] = overall_status
        report_data["report_error"] = str(exc)
        if not args.json:
            print(f"[!] Failed to write required audit report: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(report_data, indent=2))
        return 0 if overall_status == "CERTIFIED" else 1
    else:
        if overall_status == "CERTIFIED":
            print(f"[SUCCESS] Adversarial Audit CERTIFIED: {len(mutant_results)}/{len(MUTANT_SPECS)} Mutants Caught + Clean Baseline PASSED.")
            print("=" * 75)
            return 0
        else:
            print("[FAILURE] Adversarial Audit REJECTED: One or more audit gates failed.")
            print("=" * 75)
            return 1


if __name__ == "__main__":
    sys.exit(main())
