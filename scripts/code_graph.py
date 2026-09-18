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
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".dist_verify",
    ".pytest_cache",
    ".tox",
    "venv",
    ".venv",
    "env",
    "build",
    "dist",
    ".ast-grep",
    "egg-info",
}


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
        self._current_class: Optional[str] = None
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

        sym = SymbolNode(
            name=node.name,
            qualified_name=node.name,
            kind="class",
            file_path=self.rel_path,
            lineno=node.lineno,
            docstring=first_line_doc,
            bases=bases,
        )
        self.symbols.append(sym)

        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_func(node, is_async=True)

    def _process_func(self, node: Any, is_async: bool):
        qname = f"{self._current_class}.{node.name}" if self._current_class else node.name
        args = [a.arg for a in node.args.args if a.arg != "self"]
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
        self.generic_visit(node)
        self._current_func = old_func

    def visit_Call(self, node: ast.Call):
        if self._current_func:
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr

            if callee_name:
                self.calls.append({
                    "caller": self._current_func,
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
        for path in self.root_dir.rglob("*.py"):
            rel_parts = path.relative_to(self.root_dir).parts
            if any(part in EXCLUDED_DIRS for part in rel_parts):
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
            is_test = rel_str.startswith("tests/") or "tests" in rel_parts
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
                    self.tests_by_symbol[callee].add(f"{rel_str}::{call['caller']}")

        return self

    def repo_map(self, max_tokens: int = 3500) -> str:
        """Generates a compact, token-dense Repo Map for LLMs."""
        lines = ["# Repository Symbol Map (Auto-generated AST)", ""]
        
        # Sort files logically: core first, client second, cli third, tests last
        sorted_files = sorted(
            self.files.keys(),
            key=lambda f: (
                1 if f.startswith("tests/") else 0,
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

        result = "\n".join(lines)
        return result

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
        for rel_path, node in self.files.items():
            if rel_path.startswith("tests/"):
                continue
            parts = rel_path.split("/")
            pkg = parts[0] if len(parts) > 1 else "root"
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
        prod_files = [f for f in self.files.values() if not f.file_path.startswith("tests/")]
        test_files = [f for f in self.files.values() if f.file_path.startswith("tests/")]

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


def main():
    parser = argparse.ArgumentParser(description="AST Code Graph Harness for The Foundation Protocol")
    parser.add_argument("--root", type=str, default=".", help="Root directory to analyze")
    parser.add_argument("--map", action="store_true", help="Print token-dense symbol map")
    parser.add_argument("--mermaid", action="store_true", help="Print Mermaid flowchart DAG")
    parser.add_argument("--query", type=str, help="Search symbol definition, callers, and tests")
    parser.add_argument("--json", action="store_true", help="Export full graph as JSON")
    parser.add_argument("--stats", action="store_true", help="Print repository code metrics")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    graph = CodeGraph(root_dir).build()

    if args.query:
        result = graph.query(args.query)
        print(json.dumps(result, indent=2))
    elif args.mermaid:
        print(graph.mermaid())
    elif args.json:
        data = {
            "stats": graph.stats(),
            "files": {
                f: {
                    "loc": node.loc,
                    "symbols": [asdict(s) for s in node.symbols],
                    "imports": node.imports,
                }
                for f, node in graph.files.items()
            },
        }
        print(json.dumps(data, indent=2))
    elif args.stats:
        print(json.dumps(graph.stats(), indent=2))
    elif args.map:
        print(graph.repo_map())
    else:
        # Default behavior: print stats and brief repo map preview
        print(f"Foundation Protocol Code Graph: {len(graph.files)} Python files parsed.")
        print(json.dumps(graph.stats(), indent=2))
        print("\nUse --map, --query <Symbol>, or --mermaid for detailed views.")


if __name__ == "__main__":
    main()
