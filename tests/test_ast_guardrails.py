# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and regression tests for AST Guardrails, AST linter features, and ast-grep rules.
Validates:
1. Complete removal of facade --fix flag from argparse and help.
2. Robust detection of aliased imports (random as rnd, asyncio as aio, time as tm).
3. Constant-time crypto comparison detection of sig and _sig identifiers.
4. Safe handling of external paths outside repository root (no ValueError).
5. Ast-grep YAML rules syntax and constraints.
"""

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from scripts.lint_ast_rules import ASTGuardrailVisitor, lint_file, REPO_ROOT


def _lint_snippet(code: str, file_name: str = "snippet.py"):
    tree = ast.parse(code, filename=file_name)
    visitor = ASTGuardrailVisitor(Path(file_name))
    visitor.visit(tree)
    return visitor.violations


class TestASTGuardrailRemediations:
    """Test suite for Milestone 3 Iteration 2 AST remediation items."""

    def test_no_fix_flag_in_cli_help(self):
        """Ensure --fix is not present in argparse help output."""
        res = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lint_ast_rules.py"), "--help"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "--fix" not in res.stdout
        assert "--fix" not in res.stderr

    def test_aliased_import_random_detected(self):
        """Ensure aliased random import 'import random as rnd' is flagged on call."""
        code = (
            "import random as rnd\n"
            "x = rnd.random()\n"
            "y = rnd.randint(1, 10)\n"
        )
        violations = _lint_snippet(code)
        rule_ids = [v.rule_id for v in violations]
        assert rule_ids.count("no-unshielded-random") == 2

    def test_aliased_import_asyncio_create_task_detected(self):
        """Ensure aliased asyncio import 'import asyncio as aio; aio.create_task(...)' is flagged."""
        code = (
            "import asyncio as aio\n"
            "aio.create_task(some_coroutine())\n"
        )
        violations = _lint_snippet(code)
        rule_ids = [v.rule_id for v in violations]
        assert "no-unhandled-async-task" in rule_ids

    def test_aliased_import_time_sleep_in_async_detected(self):
        """Ensure aliased time import 'import time as tm; tm.sleep(...)' inside async def is flagged."""
        code = (
            "import time as tm\n"
            "async def handle():\n"
            "    tm.sleep(1.0)\n"
        )
        violations = _lint_snippet(code)
        rule_ids = [v.rule_id for v in violations]
        assert "no-blocking-sleep-in-async" in rule_ids

    def test_crypto_compare_sig_and_underscore_sig_detected(self):
        """Ensure comparisons on 'sig', '_sig', 'expected_sig', etc. are flagged."""
        test_cases = [
            "def check(sig, other): return sig == other\n",
            "def check(self, expected): return self._sig == expected\n",
            "def check(expected_sig, actual): return expected_sig != actual\n",
            "def check(computed_sig, target): return computed_sig == target\n",
        ]
        for snippet in test_cases:
            violations = _lint_snippet(snippet)
            rule_ids = [v.rule_id for v in violations]
            assert "constant-time-crypto-compare" in rule_ids, f"Failed to flag: {snippet}"

    def test_external_path_does_not_crash_linter(self):
        """Ensure external path outside repository root does not trigger ValueError on relative_to."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write("x = 42\n")
            tmp_path = Path(tmp.name)

        try:
            res = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "lint_ast_rules.py"), "--path", str(tmp_path)],
                capture_output=True,
                text=True,
            )
            assert res.returncode == 0
            assert "ValueError" not in res.stderr
            assert "All AST guardrails PASSED" in res.stdout
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_constant_time_crypto_compare_yaml_rule_has_regex_constraints(self):
        """Ensure .ast-grep/rules/constant-time-crypto-compare.yml defines regex constraints."""
        rule_file = REPO_ROOT / ".ast-grep" / "rules" / "constant-time-crypto-compare.yml"
        assert rule_file.exists()
        content = rule_file.read_text(encoding="utf-8")
        assert "constraints:" in content
        assert "regex: (?i)(hash|digest|signature|sig|token|mac|root)" in content

    def test_no_blocking_sleep_in_async_yaml_rule_has_pattern_matcher(self):
        """Ensure .ast-grep/rules/no-blocking-sleep-in-async.yml uses pattern: async def."""
        rule_file = REPO_ROOT / ".ast-grep" / "rules" / "no-blocking-sleep-in-async.yml"
        assert rule_file.exists()
        content = rule_file.read_text(encoding="utf-8")
        assert 'pattern: "async def $FUNC($$$): $$$"' in content
        assert "field: async" not in content
