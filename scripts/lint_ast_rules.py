#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Cross-Platform AST Linter for The Foundation Protocol Architectural Guardrails.

Validates 5 structural invariants across protocol packages:
1. no-unshielded-random: flags module-level unshielded random calls.
2. no-unhandled-async-task: flags unassigned/untracked asyncio.create_task expression statements.
3. no-blocking-sleep-in-async: flags time.sleep inside async def.
4. constant-time-crypto-compare: flags direct (== / !=) comparison on digests/signatures/MACs.
5. no-unshielded-network-timeout: flags network/HTTP calls lacking explicit timeout argument.

Usage:
  python scripts/lint_ast_rules.py [--path <dir>] [--json]
"""

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGETS = ["tfp_core_v4", "tfp_core", "tfp_transport"]

BANNED_RANDOM_FUNCS = {
    "random",
    "choice",
    "randint",
    "randrange",
    "sample",
    "shuffle",
    "uniform",
    "choices",
    "gauss",
    "betavariate",
    "expovariate",
    "gammavariate",
    "lognormvariate",
    "normalvariate",
    "vonmisesvariate",
    "paretovariate",
    "weibullvariate",
}

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "request"}


@dataclass
class Violation:
    file_path: str
    line: int
    col: int
    rule_id: str
    message: str


class ASTGuardrailVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.violations: List[Violation] = []
        self.async_depth = 0
        self.random_modules: Set[str] = {"random"}
        self.time_modules: Set[str] = {"time"}
        self.asyncio_modules: Set[str] = {"asyncio"}
        self.http_modules: Set[str] = {"requests", "httpx"}
        self.imported_random_funcs: Set[str] = set()
        self.imported_time_sleep: Set[str] = set()
        self.imported_asyncio_create_task: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "random":
                self.random_modules.add(alias.asname or alias.name)
            elif alias.name == "time":
                self.time_modules.add(alias.asname or alias.name)
            elif alias.name == "asyncio":
                self.asyncio_modules.add(alias.asname or alias.name)
            elif alias.name in ("requests", "httpx"):
                self.http_modules.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "random":
            for alias in node.names:
                if alias.name in BANNED_RANDOM_FUNCS:
                    self.imported_random_funcs.add(alias.asname or alias.name)
        elif node.module == "time":
            for alias in node.names:
                if alias.name == "sleep":
                    self.imported_time_sleep.add(alias.asname or alias.name)
        elif node.module == "asyncio":
            for alias in node.names:
                if alias.name == "create_task":
                    self.imported_asyncio_create_task.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.async_depth += 1
        self.generic_visit(node)
        self.async_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # A sync function defined inside an async function resets async depth for its body
        prev_depth = self.async_depth
        self.async_depth = 0
        self.generic_visit(node)
        self.async_depth = prev_depth

    def visit_Expr(self, node: ast.Expr) -> None:
        # Check rule 2: no-unhandled-async-task
        # An expression statement whose value is asyncio.create_task(...)
        if isinstance(node.value, ast.Call):
            call = node.value
            is_create_task = False
            if isinstance(call.func, ast.Attribute):
                if getattr(call.func.value, "id", None) in self.asyncio_modules and call.func.attr == "create_task":
                    is_create_task = True
            elif isinstance(call.func, ast.Name):
                if call.func.id in self.imported_asyncio_create_task:
                    is_create_task = True

            if is_create_task:
                self.violations.append(
                    Violation(
                        file_path=str(self.file_path),
                        line=node.lineno,
                        col=node.col_offset,
                        rule_id="no-unhandled-async-task",
                        message=(
                            "Unhandled asyncio.create_task expression statement. "
                            "Task must be tracked in an active task set with add_done_callback."
                        ),
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check rule 1: no-unshielded-random
        is_unshielded_random = False
        if isinstance(node.func, ast.Attribute):
            # random.random(), rnd.random(), random.choice(), etc.
            if getattr(node.func.value, "id", None) in self.random_modules:
                if node.func.attr in BANNED_RANDOM_FUNCS:
                    is_unshielded_random = True
        elif isinstance(node.func, ast.Name):
            if node.func.id in self.imported_random_funcs:
                is_unshielded_random = True

        if is_unshielded_random:
            func_name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            self.violations.append(
                Violation(
                    file_path=str(self.file_path),
                    line=node.lineno,
                    col=node.col_offset,
                    rule_id="no-unshielded-random",
                    message=(
                        f"Unshielded call to random.{func_name}(). "
                        "Use secrets or deterministic cryptographic PRKs instead of module-level random."
                    ),
                )
            )

        # Check rule 3: no-blocking-sleep-in-async
        if self.async_depth > 0:
            is_time_sleep = False
            if isinstance(node.func, ast.Attribute):
                if getattr(node.func.value, "id", None) in self.time_modules and node.func.attr == "sleep":
                    is_time_sleep = True
            elif isinstance(node.func, ast.Name):
                if node.func.id in self.imported_time_sleep:
                    is_time_sleep = True

            if is_time_sleep:
                self.violations.append(
                    Violation(
                        file_path=str(self.file_path),
                        line=node.lineno,
                        col=node.col_offset,
                        rule_id="no-blocking-sleep-in-async",
                        message="Blocking time.sleep detected inside async def. Use await asyncio.sleep(...) instead.",
                    )
                )

        # Check rule 5: no-unshielded-network-timeout
        is_http_call = False
        if isinstance(node.func, ast.Attribute):
            base_mod = getattr(node.func.value, "id", None)
            if base_mod in self.http_modules and node.func.attr in HTTP_METHODS:
                is_http_call = True
            elif base_mod == "request" and node.func.attr == "urlopen":
                is_http_call = True
            elif (
                isinstance(node.func.value, ast.Attribute)
                and getattr(node.func.value.value, "id", None) == "urllib"
                and node.func.value.attr == "request"
                and node.func.attr == "urlopen"
            ):
                is_http_call = True

        if is_http_call:
            has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
            if not has_timeout:
                self.violations.append(
                    Violation(
                        file_path=str(self.file_path),
                        line=node.lineno,
                        col=node.col_offset,
                        rule_id="no-unshielded-network-timeout",
                        message="Network/HTTP request without explicit timeout keyword argument.",
                    )
                )

        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        # Check rule 4: constant-time-crypto-compare
        # Direct comparison (== or !=) on digests, signatures, tokens, or MACs
        has_eq_or_neq = any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        if has_eq_or_neq:
            operands = [node.left] + node.comparators
            # Check if any operand is a length comparison (e.g. len(sig) == 64)
            is_length_check = any(
                isinstance(op, ast.Call) and getattr(op.func, "id", None) == "len"
                for op in operands
            )
            # Check if any operand is a type check (type(x) == bytes) or bool/int/None check
            is_type_or_none_or_num = any(
                (isinstance(op, ast.Constant) and (op.value is None or isinstance(op.value, (int, float, bool))))
                for op in operands
            )

            if not is_length_check and not is_type_or_none_or_num:
                if self._has_crypto_operand(operands):
                    self.violations.append(
                        Violation(
                            file_path=str(self.file_path),
                            line=node.lineno,
                            col=node.col_offset,
                            rule_id="constant-time-crypto-compare",
                            message=(
                                "Direct comparison (== or !=) used on cryptographic digest/signature/mac/token. "
                                "Use hmac.compare_digest() for constant-time verification."
                            ),
                        )
                    )

        self.generic_visit(node)

    def _is_crypto_name(self, name: str) -> bool:
        lower = name.lower()
        # Avoid false positives on algorithm / format names
        if "algorithm" in lower or "version" in lower or "type" in lower:
            return False
        crypto_suffixes = (
            "_digest",
            "_signature",
            "_sig",
            "_mac",
            "_hash",
            "_token",
            "_root",
            "root_hash",
            "merkle_root",
            "expected_signature",
            "computed_signature",
            "expected_sig",
            "computed_sig",
            "expected_mac",
            "computed_mac",
            "expected_root",
            "computed_root",
            "recovered_root",
            "current_hash",
        )
        crypto_exact = {
            "digest",
            "signature",
            "sig",
            "_sig",
            "mac",
            "token",
            "auth_tag",
            "root_hash",
            "merkle_root",
        }
        if lower in crypto_exact:
            return True
        return any(lower.endswith(sfx) for sfx in crypto_suffixes)

    def _has_crypto_operand(self, operands: List[ast.AST]) -> bool:
        for op in operands:
            if isinstance(op, ast.Name):
                if self._is_crypto_name(op.id):
                    return True
            elif isinstance(op, ast.Attribute):
                if self._is_crypto_name(op.attr):
                    return True
            elif isinstance(op, ast.Call):
                if isinstance(op.func, ast.Attribute) and op.func.attr in ("hexdigest", "digest"):
                    return True
        return False


def lint_file(file_path: Path) -> List[Violation]:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception as exc:
        return [
            Violation(
                file_path=str(file_path),
                line=1,
                col=1,
                rule_id="ast-parse-error",
                message=f"Failed to parse AST: {exc}",
            )
        ]
    visitor = ASTGuardrailVisitor(file_path)
    visitor.visit(tree)
    return visitor.violations


def lint_paths(paths: List[Path]) -> List[Violation]:
    violations: List[Violation] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            violations.extend(lint_file(path))
        elif path.is_dir():
            for py_file in sorted(path.rglob("*.py")):
                # Skip test directories, virtual environments, caches
                parts = py_file.parts
                if any(p in (".venv", "venv", ".git", "__pycache__", ".pytest_cache") for p in parts):
                    continue
                violations.extend(lint_file(py_file))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-Platform AST Linter for TFP Architectural Guardrails"
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Target file or directory to lint (default: tfp_core_v4, tfp_core, tfp_transport)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output violations in JSON format",
    )
    args = parser.parse_args()

    target_paths: List[Path] = []
    if args.paths:
        for p in args.paths:
            target_paths.append(REPO_ROOT / p if not Path(p).is_absolute() else Path(p))
    else:
        for p in DEFAULT_TARGETS:
            target_paths.append(REPO_ROOT / p)

    violations = lint_paths(target_paths)

    if args.json:
        out = [asdict(v) for v in violations]
        print(json.dumps(out, indent=2))
    else:
        print("=" * 70)
        print("TFP Architectural Guardrails AST Linter")
        target_strs = []
        for p in target_paths:
            try:
                target_strs.append(str(p.relative_to(REPO_ROOT)))
            except ValueError:
                target_strs.append(str(p))
        print(f"Scanning target directories: {', '.join(target_strs)}")
        print("=" * 70)
        if not violations:
            print("[OK] All AST guardrails PASSED (0 violations).")
            print("=" * 70)
            return 0

        print(f"[FAIL] Found {len(violations)} architectural guardrail violation(s):\n")
        for v in violations:
            rel_path = v.file_path
            try:
                rel_path = str(Path(v.file_path).relative_to(REPO_ROOT))
            except Exception:
                pass
            print(f"  {rel_path}:{v.line}:{v.col} [{v.rule_id}]")
            print(f"    -> {v.message}\n")
        print("=" * 70)
        print("FAIL: Please resolve the above guardrail violations.")
        print("=" * 70)

    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
