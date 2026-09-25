# SPDX-License-Identifier: Apache-2.0
"""
Tests for scripts/code_graph.py AST Code Graph and AI Search Harness.
"""

from pathlib import Path
import pytest

from scripts.code_graph import CodeGraph, ASTVisitor, SymbolNode


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def shared_graph():
    """Builds the code graph once for read-only tests."""
    return CodeGraph(REPO_ROOT).build()


def test_code_graph_builds_and_populates_stats(shared_graph):
    stats = shared_graph.stats()
    assert stats["production_files"] > 100
    assert stats["production_loc"] > 10000
    assert stats["production_classes"] > 100
    assert stats["production_functions"] > 500
    assert stats["test_files"] > 20
    assert stats["total_symbols"] > 1000


def test_symbol_query_real_lexicon_adapter(shared_graph):
    result = shared_graph.query("RealLexiconAdapter")
    assert result["found"] is True
    assert len(result["definitions"]) >= 1
    
    definition = result["definitions"][0]
    assert definition["name"] == "RealLexiconAdapter"
    assert definition["kind"] == "class"
    assert "adapter_real.py" in definition["file"]
    assert definition["line"] > 0
    assert "Zstandard" in (definition["docstring"] or "")

    # Should have callers and test coverage
    assert len(result["callers"]) > 0
    assert any("test_real_lexicon_zstandard" in t for t in result["covered_by_tests"])


def test_symbol_query_manifest_signing(shared_graph):
    result = shared_graph.query("sign_manifest_ed25519")
    assert result["found"] is True
    assert len(result["definitions"]) >= 1

    definition = result["definitions"][0]
    assert definition["kind"] == "function"
    assert "manifest.py" in definition["file"]
    assert "private_key" in definition["args"]

    # Should be covered by the Ed25519 tests
    assert any("test_ed25519_manifest_crypto" in t for t in result["covered_by_tests"])


def test_symbol_query_unknown_returns_not_found(shared_graph):
    result = shared_graph.query("NonExistentFakeSymbolXYZ12345")
    assert result["found"] is False
    assert len(result["definitions"]) == 0
    assert len(result["callers"]) == 0


def test_mermaid_generation_syntax(shared_graph):
    mermaid_str = shared_graph.mermaid()
    assert mermaid_str.startswith("```mermaid")
    assert mermaid_str.strip().endswith("```")
    assert "flowchart TD" in mermaid_str
    assert "subgraph tfp_core" in mermaid_str
    assert "subgraph tfp_core_v4" in mermaid_str


def test_repo_map_token_density(shared_graph):
    repo_map = shared_graph.repo_map()
    assert "# Repository Symbol Map" in repo_map
    assert "tfp_core/governance/manifest.py" in repo_map
    assert "def sign_manifest_ed25519" in repo_map
    assert "class RealLexiconAdapter" in repo_map
    # Ensure it's structured and not empty
    lines = repo_map.splitlines()
    assert len(lines) > 500


def test_code_graph_stats_package_consistency_and_audit(shared_graph):
    stats = shared_graph.stats()
    breakdown = {p["package"]: p for p in shared_graph.package_breakdown()}
    assert "tests" in breakdown
    assert stats["test_files"] == breakdown["tests"]["files"]
    assert stats["production_files"] == sum(
        p["files"] for pkg, p in breakdown.items() if pkg != "tests"
    )

    audit = shared_graph.audit()
    assert "dual_tree_shadowing" in audit
    assert "bulletin_workflow_symbol_coverage" in audit
    assert "top_fan_in_symbols" in audit
    bw = audit["bulletin_workflow_symbol_coverage"]
    assert bw["store_bulletin"]["direct_test_callers"] >= 20
    assert bw["get_max_bulletin_revision"]["total_call_sites"] >= 2

