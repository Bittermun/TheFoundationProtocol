#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Deterministic AST Code Graph & AI Search Harness for The Foundation Protocol.

Zero-dependency repository topology and symbol graph extractor using Python's
standard library `ast`. Provides instant, token-dense structural context for
AI agents and developers without requiring vector stores or heavy ML frameworks.

Features:
  --map        Generate a compact, token-dense symbol outline (Repo Map)
  --mermaid    Emit a GitHub Flavored Markdown Mermaid flowchart DAG
  --query <S>  Bidirectional symbol search (definitions, callers, callees, tests)
  --json       Export full structured graph (nodes & edges)
  --stats      Report codebase structural metrics

Usage:
  python scripts/code_graph.py --map
  python scripts/code_graph.py --query RealLexiconAdapter
  python scripts/code_graph.py --mermaid
"""

import argparse
import ast
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set


EXCLUDED_DIRS = {
    ".git",
    ".agents",
    "__pycache__",
    ".dist_verify",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    ".tox",
    "venv",
    ".venv",
    "env",
    "build",
    "dist",
    ".ast-grep",
    "egg-info",
}

PACKAGE_ROLES = {
    "tfp_core_v4": "Core protocol engine: TFPNode storage engine, durable bulletin watermarks, ContentDefinedChunker, SQLite recipe store, and visualizer server",
    "tfp_client": "Client library: article ingest, Bell 202 AFSK audio modulation/demodulation, vocoder, hybrid BM25/LSH search, and fountain codecs",
    "tfp_transport": "Physical transport layer: KISS TNC serial framing, UDP broadcast, and LoRa interfaces",
    "tfp_security": "Cryptographic security layer: Post-quantum crypto wrappers, BIP39 root-of-trust, and Ed25519 signing",
    "tfp_simulator": "Offline Wi-Fi mesh network simulator, latency/jitter injection, and community swarm modeling",
    "tfp_testbed": "Adversarial fault injection fixtures, mutant runners, and stress test harnesses",
    "tests": "Comprehensive test battery spanning unit, state-sequence, hypothesis fuzzing, Playwright browser acceptance, and adversarial verification",
    "scripts": "Developer automation tooling: AST code graph generator, station-to-listener operator rehearsal harness, and adversarial audit runners",
    "tfp_cli": "Legacy CLI entrypoint maintained for backward compatibility",
    "tfp_core": "Legacy protocol core v1-v3 components",
    "tfp_ui": "User interface assets and web components",
    "tfp_demo": "Demonstration dashboards, zero-install acoustic microphone receiver portals, and static web assets",
    "tfp_plugins": "Extensible plugin subsystem for protocol extensions",
    "tfp_plugin_sdk": "Software development kit for third-party transport and codec plugins",
    "tfp_common": "Shared protocol constants, schemas, and cross-module utilities",
    "tfp_broadcaster": "Station broadcast scheduling, transmission queuing, and acoustic/radio dispatch helpers",
    "tfp_pilots": "Field pilot deployment configurations and scenario scripts",
    "demo": "Standalone web and CLI demonstration assets",
    "root": "Top-level packaging (setup.py), benchmark suites, and profiling scripts",
}


def _is_excluded_path(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts:
        if part in EXCLUDED_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _is_test_file(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    name = parts[-1] if parts else ""
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _get_git_info(repo_root: Path) -> Dict[str, str]:
    commit = "unknown"
    branch = "unknown"
    try:
        res_c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=5)
        if res_c.returncode == 0:
            commit = res_c.stdout.strip()
        res_b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=5)
        if res_b.returncode == 0:
            branch = res_b.stdout.strip()
    except Exception:
        pass
    return {"commit": commit, "branch": branch}


@dataclass
class SymbolNode:
    """Represents a class, method, or function in the codebase."""
    name: str
    qualified_name: str
    kind: str  # 'class', 'function', 'async_function'
    file_path: str
    lineno: int
    args: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    docstring: Optional[str] = None
    bases: List[str] = field(default_factory=list)


@dataclass
class FileNode:
    """Represents a Python source file."""
    file_path: str
    module_name: str
    loc: int
    symbols: List[SymbolNode] = field(default_factory=list)
    imports: List[Dict[str, str]] = field(default_factory=list)
    calls: List[Dict[str, Any]] = field(default_factory=list)


class ASTVisitor(ast.NodeVisitor):
    """Visits Python AST nodes to extract symbols, calls, and imports."""

    def __init__(self, rel_path: str, module_name: str):
        self.rel_path = rel_path
        self.module_name = module_name
        self.symbols: List[SymbolNode] = []
        self.imports: List[Dict[str, str]] = []
        self.calls: List[Dict[str, Any]] = []
        self._scope_stack: List[str] = []
        self._current_func: Optional[str] = None

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append({
                "module": alias.name,
                "name": alias.name,
                "alias": alias.asname or alias.name,
                "lineno": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            self.imports.append({
                "module": mod,
                "name": alias.name,
                "alias": alias.asname or alias.name,
                "lineno": node.lineno,
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(f"{self._get_attr_name(base)}")
        doc = ast.get_docstring(node)
        first_line_doc = doc.split("\n")[0].strip() if doc else None

        qname = ".".join([*self._scope_stack, node.name]) if self._scope_stack else node.name
        sym = SymbolNode(
            name=node.name,
            qualified_name=qname,
            kind="class",
            file_path=self.rel_path,
            lineno=node.lineno,
            docstring=first_line_doc,
            bases=bases,
        )
        self.symbols.append(sym)

        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_func(node, is_async=True)

    @staticmethod
    def _extract_func_args(arguments: ast.arguments) -> List[str]:
        extracted: List[str] = []
        pos_args = list(getattr(arguments, "posonlyargs", [])) + list(arguments.args)
        for idx, a in enumerate(pos_args):
            if idx == 0 and a.arg in ("self", "cls"):
                continue
            extracted.append(a.arg)
        if arguments.vararg:
            extracted.append(f"*{arguments.vararg.arg}")
        for a in arguments.kwonlyargs:
            extracted.append(f"{a.arg}=")
        if arguments.kwarg:
            extracted.append(f"**{arguments.kwarg.arg}")
        return extracted

    def _process_func(self, node: Any, is_async: bool):
        qname = ".".join([*self._scope_stack, node.name]) if self._scope_stack else node.name
        args = self._extract_func_args(node.args)
        ret = None
        if node.returns:
            ret = ast.unparse(node.returns) if hasattr(ast, "unparse") else None

        doc = ast.get_docstring(node)
        first_line_doc = doc.split("\n")[0].strip() if doc else None

        sym = SymbolNode(
            name=node.name,
            qualified_name=qname,
            kind="async_function" if is_async else "function",
            file_path=self.rel_path,
            lineno=node.lineno,
            args=args,
            return_type=ret,
            docstring=first_line_doc,
        )
        self.symbols.append(sym)

        old_func = self._current_func
        self._current_func = qname
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()
        self._current_func = old_func

    def visit_Call(self, node: ast.Call):
        caller_scope = self._current_func or (".".join(self._scope_stack) if self._scope_stack else "<module>")
        callee_name = None
        if isinstance(node.func, ast.Name):
            callee_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee_name = node.func.attr

        if callee_name:
            self.calls.append({
                "caller": caller_scope,
                "callee": callee_name,
                "lineno": node.lineno,
                "file_path": self.rel_path,
            })
        self.generic_visit(node)

    def _get_attr_name(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            return f"{self._get_attr_name(node.value)}.{node.attr}"
        return node.attr


class CodeGraph:
    """Core code graph repository indexer."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.files: Dict[str, FileNode] = {}
        self.symbols_by_name: Dict[str, List[SymbolNode]] = defaultdict(list)
        self.symbols_by_qname: Dict[str, SymbolNode] = {}
        self.callers_by_callee: Dict[str, Set[str]] = defaultdict(set)
        self.callees_by_caller: Dict[str, Set[str]] = defaultdict(set)
        self.tests_by_symbol: Dict[str, Set[str]] = defaultdict(set)

    def build(self) -> "CodeGraph":
        """Scans the repository and parses all Python files."""
        for path in sorted(self.root_dir.rglob("*.py")):
            rel_parts = path.relative_to(self.root_dir).parts
            if _is_excluded_path(rel_parts):
                continue

            rel_str = str(path.relative_to(self.root_dir)).replace("\\", "/")
            try:
                content = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
                tree = ast.parse(content, filename=rel_str)
            except Exception as e:
                # Non-fatal syntax/encoding error
                print(f"[WARN] Failed to parse {rel_str}: {e}", file=sys.stderr)
                continue

            loc = len([line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")])
            module_name = ".".join(path.relative_to(self.root_dir).with_suffix("").parts)

            visitor = ASTVisitor(rel_str, module_name)
            visitor.visit(tree)

            file_node = FileNode(
                file_path=rel_str,
                module_name=module_name,
                loc=loc,
                symbols=visitor.symbols,
                imports=visitor.imports,
                calls=visitor.calls,
            )
            self.files[rel_str] = file_node

            # Index symbols
            is_test = _is_test_file(rel_str)
            for sym in visitor.symbols:
                self.symbols_by_name[sym.name].append(sym)
                self.symbols_by_qname[f"{rel_str}::{sym.qualified_name}"] = sym

            # Index calls
            for call in visitor.calls:
                caller = f"{rel_str}::{call['caller']}"
                callee = call["callee"]
                self.callers_by_callee[callee].add(caller)
                self.callees_by_caller[caller].add(callee)
                if is_test:
                    self.tests_by_symbol[callee].add(caller)

        return self

    def repo_map(self, max_tokens: int = 3500) -> str:
        """Generates a compact, token-dense Repo Map for LLMs."""
        lines = ["# Repository Symbol Map (Auto-generated AST)", ""]

        # Sort files logically: core first, client second, cli third, tests last
        sorted_files = sorted(
            self.files.keys(),
            key=lambda f: (
                1 if _is_test_file(f) else 0,
                0 if "core" in f else (1 if "client" in f else 2),
                f,
            ),
        )

        for rel_path in sorted_files:
            file_node = self.files[rel_path]
            if not file_node.symbols:
                continue

            lines.append(f"📁 {rel_path} ({file_node.loc} LOC)")
            for sym in file_node.symbols:
                if sym.kind == "class":
                    bases_str = f"({', '.join(sym.bases)})" if sym.bases else ""
                    doc = f" - {sym.docstring}" if sym.docstring else ""
                    lines.append(f"  ├─ class {sym.name}{bases_str}{doc}")
                else:
                    args_str = ", ".join(sym.args)
                    ret_str = f" -> {sym.return_type}" if sym.return_type else ""
                    prefix = "async def" if sym.kind == "async_function" else "def"
                    indent = "  │  └─" if "." in sym.qualified_name else "  ├─"
                    doc = f" - {sym.docstring}" if sym.docstring else ""
                    lines.append(f"{indent} {prefix} {sym.name}({args_str}){ret_str}{doc}")
            lines.append("")

        return "\n".join(lines)

    def query(self, symbol_name: str) -> Dict[str, Any]:
        """Performs bidirectional symbol lookup."""
        matching_symbols = self.symbols_by_name.get(symbol_name, [])
        if not matching_symbols:
            # Try case-insensitive or partial match
            lowered = symbol_name.lower()
            for name, syms in self.symbols_by_name.items():
                if lowered in name.lower():
                    matching_symbols.extend(syms)

        callers = sorted(list(self.callers_by_callee.get(symbol_name, [])))
        tests = sorted(list(self.tests_by_symbol.get(symbol_name, [])))

        # Callees called by any instance of this symbol
        callees = set()
        for sym in matching_symbols:
            key = f"{sym.file_path}::{sym.qualified_name}"
            callees.update(self.callees_by_caller.get(key, []))

        return {
            "query": symbol_name,
            "found": len(matching_symbols) > 0,
            "definitions": [
                {
                    "name": s.name,
                    "qualified_name": s.qualified_name,
                    "kind": s.kind,
                    "file": s.file_path,
                    "line": s.lineno,
                    "args": s.args,
                    "returns": s.return_type,
                    "docstring": s.docstring,
                }
                for s in matching_symbols
            ],
            "callers": callers,
            "callees": sorted(list(callees)),
            "covered_by_tests": tests,
        }

    def mermaid(self) -> str:
        """Generates a GitHub-renderable Mermaid architecture flowchart."""
        packages = defaultdict(list)
        for rel_path in self.files:
            if _is_test_file(rel_path):
                continue
            parts = rel_path.split("/")
            pkg = parts[1] if (parts[0] == "tfp-foundation-protocol" and len(parts) > 1) else (parts[0] if len(parts) > 1 else "root")
            packages[pkg].append(rel_path)

        lines = [
            "```mermaid",
            "flowchart TD",
            "    %% Architectural Snapshot Graph (Deterministic AST)",
        ]

        # Render subgraphs for packages
        node_ids = {}
        idx = 0
        for pkg, file_list in sorted(packages.items()):
            if len(file_list) > 10:
                file_list = file_list[:8]  # Bound diagram visual density
            lines.append(f"    subgraph {pkg}[\"{pkg}\"]")
            for f in file_list:
                stem = Path(f).stem
                nid = f"n{idx}"
                node_ids[f] = nid
                idx += 1
                lines.append(f"        {nid}[\"{stem}\"]")
            lines.append("    end")

        # Derive import edges between modules
        drawn_edges = set()
        for rel_path, node in self.files.items():
            src_id = node_ids.get(rel_path)
            if not src_id:
                continue
            for imp in node.imports:
                mod = imp["module"]
                # Match module to a known file
                for target_path, target_id in node_ids.items():
                    if target_id == src_id:
                        continue
                    target_mod = target_path.replace("/", ".").replace(".py", "")
                    if mod and (mod == target_mod or mod.endswith(Path(target_path).stem)):
                        edge_key = (src_id, target_id)
                        if edge_key not in drawn_edges and len(drawn_edges) < 40:
                            drawn_edges.add(edge_key)
                            lines.append(f"    {src_id} --> {target_id}")

        lines.append("```")
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        """Computes structural metrics across the repository."""
        prod_files = [f for f in self.files.values() if not _is_test_file(f.file_path)]
        test_files = [f for f in self.files.values() if _is_test_file(f.file_path)]

        prod_classes = sum(len([s for s in f.symbols if s.kind == "class"]) for f in prod_files)
        prod_funcs = sum(len([s for s in f.symbols if s.kind in ("function", "async_function")]) for f in prod_files)
        test_funcs = sum(len([s for s in f.symbols if s.name.startswith("test_")]) for f in test_files)

        return {
            "production_files": len(prod_files),
            "production_loc": sum(f.loc for f in prod_files),
            "production_classes": prod_classes,
            "production_functions": prod_funcs,
            "test_files": len(test_files),
            "test_functions": test_funcs,
            "total_symbols": sum(len(f.symbols) for f in self.files.values()),
        }

    def package_breakdown(self) -> List[Dict[str, Any]]:
        """Computes per-package metrics across the repository."""
        pkgs: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "files": 0, "loc": 0, "classes": 0, "functions": 0
        })
        for f, node in self.files.items():
            if _is_test_file(f):
                top = "tests"
            else:
                parts = f.split("/")
                if parts[0] == "tfp-foundation-protocol" and len(parts) > 1:
                    top = parts[1]
                elif "/" in f:
                    top = parts[0]
                else:
                    top = "root"
            pkgs[top]["files"] += 1
            pkgs[top]["loc"] += node.loc
            for s in node.symbols:
                if s.kind == "class":
                    pkgs[top]["classes"] += 1
                elif s.kind in ("function", "async_function"):
                    pkgs[top]["functions"] += 1

        result = []
        for pkg, data in sorted(pkgs.items(), key=lambda x: -x[1]["loc"]):
            result.append({
                "package": pkg,
                "role": PACKAGE_ROLES.get(pkg, "Subsystem module"),
                "files": data["files"],
                "loc": data["loc"],
                "classes": data["classes"],
                "functions": data["functions"],
            })
        return result

    def audit(self) -> Dict[str, Any]:
        """
        Performs a deterministic structural audit of the codebase graph:
        1. Detects duplicate/drifted files and shadowed package orphans between root and `tfp-foundation-protocol/`.
        2. Tracks test caller coverage for critical station-to-listener bulletin and storage symbols.
        3. Reports highest-fan-in protocol symbols.
        """
        prefix = "tfp-foundation-protocol/"
        sub_files = {f[len(prefix):]: f for f in self.files if f.startswith(prefix)}
        root_files = {f: f for f in self.files if not f.startswith(prefix)}

        root_top_pkgs = {
            f.split("/")[0]
            for f in root_files
            if "/" in f and not _is_test_file(f) and f.split("/")[0].startswith("tfp_")
        }

        drifted_duplicates = []
        identical_duplicates = []
        shadowed_orphans = []

        for rel_sub, full_sub in sorted(sub_files.items()):
            top_pkg = rel_sub.split("/")[0] if "/" in rel_sub else ""
            if rel_sub in root_files:
                root_path = self.root_dir / rel_sub
                sub_path = self.root_dir / full_sub
                try:
                    r_bytes = root_path.read_bytes()
                    s_bytes = sub_path.read_bytes()
                    if hashlib.sha3_256(r_bytes).digest() == hashlib.sha3_256(s_bytes).digest():
                        identical_duplicates.append({
                            "active_root_file": rel_sub,
                            "shadowed_sub_file": full_sub,
                            "bytes": len(r_bytes),
                        })
                    else:
                        drifted_duplicates.append({
                            "active_root_file": rel_sub,
                            "shadowed_sub_file": full_sub,
                            "root_bytes": len(r_bytes),
                            "sub_bytes": len(s_bytes),
                        })
                except OSError:
                    pass
            elif top_pkg in root_top_pkgs:
                shadowed_orphans.append({
                    "shadowed_sub_file": full_sub,
                    "shadowed_by_root_package": top_pkg,
                    "reason": f"setup.py maps package '{top_pkg}' to './{top_pkg}', excluding '{full_sub}' from built wheels.",
                })

        critical_bulletin_symbols = [
            "store_bulletin",
            "_check_watermark",
            "prune_display_bulletins",
            "get_bulletin_watermark",
            "get_max_bulletin_revision",
            "get_bulletin",
            "list_bulletins",
            "prepare_bulletin_package",
            "import_bulletin_package",
            "sign_bulletin_content",
            "verification_status",
            "check_revision",
            "rehearse_operator_workflow",
        ]
        bulletin_symbol_coverage = {}
        for sym_name in critical_bulletin_symbols:
            defs = self.symbols_by_name.get(sym_name, [])
            tests = sorted(list(self.tests_by_symbol.get(sym_name, set())))
            callers = sorted(list(self.callers_by_callee.get(sym_name, set())))
            bulletin_symbol_coverage[sym_name] = {
                "defined_in": [f"{d.file_path}:{d.lineno}" for d in defs],
                "total_call_sites": len(callers),
                "direct_test_callers": len(tests),
            }

        top_fan_in = [
            {"symbol": sym, "callers": len(callers), "test_callers": len(self.tests_by_symbol.get(sym, set()))}
            for sym, callers in sorted(self.callers_by_callee.items(), key=lambda x: -len(x[1]))
            if sym in self.symbols_by_name and not sym.startswith("test_")
        ][:15]

        return {
            "dual_tree_shadowing": {
                "drifted_duplicates": drifted_duplicates,
                "identical_duplicates": identical_duplicates,
                "shadowed_orphans": shadowed_orphans,
            },
            "bulletin_workflow_symbol_coverage": bulletin_symbol_coverage,
            "top_fan_in_symbols": top_fan_in,
        }

    def detailed_export(self) -> Dict[str, Any]:
        """Exports enriched code graph with metadata, package breakdown, test coverage, and architectural commentary."""
        git_info = _get_git_info(self.root_dir)
        now_utc = datetime.now(timezone.utc).isoformat()

        # Test coverage mapping for tested symbols
        test_coverage = {
            sym: sorted(list(tests))
            for sym, tests in sorted(self.tests_by_symbol.items())
            if tests
        }

        return {
            "metadata": {
                "protocol": "The Foundation Protocol (TFP)",
                "protocol_version": "v4.0.0",
                "schema_version": "2.1.0",
                "generated_at": now_utc,
                "git_commit": git_info["commit"],
                "git_branch": git_info["branch"],
                "repository": "https://github.com/Bittermun/TheFoundationProtocol",
                "ast_engine": "Python standard library ast (deterministic zero-dependency)",
            },
            "stats": self.stats(),
            "package_breakdown": self.package_breakdown(),
            "structural_findings": self.audit(),
            "architectural_commentary": {
                "mission": "Zero-infrastructure, physical-layer resilient knowledge dissemination for disaster recovery, grid failure, and off-grid triage.",
                "fountain_erasure_coding": "Dual-engine architecture: BinaryLinearErasureCodec (pure-Python systematic GF(2) XOR Cauchy linear erasure code with Gaussian elimination) and FountainStreamer (Luby Transform rateless Soliton code for broadcast loss recovery).",
                "content_defined_chunking": "FastCDC boundary-shift resistant chunking using a 256-entry 64-bit gear matrix and normalized sub-chunk masks (min: 512B, avg: 1-4KB, max: 8KB).",
                "cryptographic_integrity": "SHA3-256 Merkle audit path proofs, Ed25519 manifest digital signatures, and per-shard HMAC-SHA3-256 integrity checks.",
                "physical_modulation": "Bell 202 Audio Frequency Shift Keying (1200/2200 Hz Mark/Space) at 1200/300 baud with CRC-16 checksums for analog radios and audio cables.",
                "durable_persistence": "SQLite persistent database store (TFPNode) decoupling reader chunking configuration from on-disk Content Defined Chunk recipes.",
                "bulletin_lifecycle_and_watermarks": "Monotone revision watermarks (bulletin_watermarks) persisted independently of prunable display bulletins, enforcing publisher key pinning, full-identity (title + content hash) revision conflict rejection, and atomic upgrade backfilling.",
                "decoupled_receiver_trust_boundary": "Zero-install browser acoustic receiver (acoustic_receiver.html) verifies CRC-16 transport integrity and local revision watermarks while explicitly marking publisher signatures as unverified, preventing spoofed wire metadata from claiming cryptographic authentication.",
                "operator_rehearsal_harness": "End-to-end station-to-listener simulation harness (scripts/rehearse_operator_workflow.py) validating notice authoring, Ed25519 signing, AFSK modulation, missed-broadcast gap detection, correction distribution, and stale replay rejection.",
                "modular_visualizer": "Isolated multi-threaded visualizer server (visualizer_server.py) providing real-time Server-Sent Events (SSE) telemetry and 60 FPS GPU-accelerated canvas visualization.",
                "zero_touch_appliances": "Audio Scholar headless triage daemon (UDP/sound) and zero-install browser acoustic microphone receiver for broken-screen and weak mobile devices.",
                "adversarial_certification": "Autonomous adversarial fault injection runner (scripts/run_adversarial_audit.py) verifying invariants across mutants M1-M5 with certified negative proof.",
            },
            "test_coverage_index": {
                "tested_symbol_count": len(test_coverage),
                "coverage_map": test_coverage,
            },
            "files": {
                f: {
                    "loc": node.loc,
                    "symbols": [asdict(s) for s in node.symbols],
                    "imports": node.imports,
                    "calls": node.calls,
                }
                for f, node in self.files.items()
            },
        }


def main():
    parser = argparse.ArgumentParser(description="AST Code Graph Harness for The Foundation Protocol")
    parser.add_argument("--root", type=str, default=".", help="Root directory to analyze")
    parser.add_argument("--map", action="store_true", help="Print token-dense symbol map")
    parser.add_argument("--mermaid", action="store_true", help="Print Mermaid flowchart DAG")
    parser.add_argument("--query", type=str, help="Search symbol definition, callers, and tests")
    parser.add_argument("--audit", action="store_true", help="Run structural audit (shadowed files, duplicate drift, bulletin test coverage)")
    parser.add_argument("--json", action="store_true", help="Export full graph as JSON")
    parser.add_argument("--stats", action="store_true", help="Print repository code metrics")
    parser.add_argument("--output", "-o", type=str, help="Write output to specified file path (UTF-8)")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    graph = CodeGraph(root_dir).build()

    out_content: str | None = None
    if args.query:
        result = graph.query(args.query)
        out_content = json.dumps(result, indent=2)
    elif args.audit:
        out_content = json.dumps(graph.audit(), indent=2)
    elif args.mermaid:
        out_content = graph.mermaid()
    elif args.json:
        data = graph.detailed_export()
        out_content = json.dumps(data, indent=2)
    elif args.stats:
        out_content = json.dumps(graph.stats(), indent=2)
    elif args.map:
        out_content = graph.repo_map()

    if out_content is not None:
        if args.output:
            out_path = Path(args.output).resolve()
            out_path.write_text(out_content, encoding="utf-8")
            print(f"Code graph output written to {out_path} ({len(out_content)} bytes)")
        else:
            print(out_content)
    else:
        # Default behavior: print stats and brief repo map preview
        print(f"Foundation Protocol Code Graph: {len(graph.files)} Python files parsed.")
        print(json.dumps(graph.stats(), indent=2))
        print("\nUse --map, --query <Symbol>, --audit, or --mermaid for detailed views.")


if __name__ == "__main__":
    main()

