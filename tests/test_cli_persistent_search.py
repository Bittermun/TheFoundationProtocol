# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Integration test verifying persistent SQLite search via CLI:
Publish document -> process exit -> search by body term in fresh process -> match returned.
"""

import subprocess
import sys
from pathlib import Path


def test_cli_search_empty_db_honest_report(tmp_path: Path):
    """Verify that search honestly reports 0 published articles and marks demonstration corpus."""
    empty_db = tmp_path / "empty_node.db"

    res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(empty_db),
            "search", "sanitation",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "0 published articles found" in res.stdout
    assert "Searching built-in emergency demonstration corpus:" in res.stdout
    assert "[DEMO] doc1:" in res.stdout


def test_cli_search_empty_db_unmatched_query(tmp_path: Path):
    """Verify that unmatched queries on empty db report no matching content."""
    empty_db = tmp_path / "empty_node.db"

    res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(empty_db),
            "search", "unmatched_quantum_telemetry",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "0 published articles found" in res.stdout
    assert "Searching built-in emergency demonstration corpus:" in res.stdout
    assert "No matching content found for 'unmatched_quantum_telemetry'" in res.stdout


def test_cli_search_degraded_document_explicit_warning(tmp_path: Path):
    """Verify that documents whose body cannot be retrieved are visibly tagged as degraded."""
    import sqlite3
    from tfp_core_v4.node import TFPNode

    db_file = tmp_path / "degraded_node.db"
    node = TFPNode(db_path=db_file)
    recipe = node.publish(
        b"Sensitive emergency triage instructions for radiation burns.",
        metadata={"title": "Radiation Triage Field Guide"},
    )

    # Corrupt/delete chunk data to force retrieval failure
    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM droplets")
    conn.commit()
    conn.close()

    # Search by body term that cannot be searched
    body_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "search", "burns",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "Warning: 1 document(s) could not be fully searched" in body_res.stdout
    assert "could not be searched because content body was unavailable" in body_res.stdout

    # Search by title term: result should be returned with [DEGRADED: BODY UNAVAILABLE] tag
    title_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "search", "Radiation",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "[DEGRADED: BODY UNAVAILABLE]" in title_res.stdout
    assert "Radiation Triage Field Guide" in title_res.stdout
    assert recipe.root_hash in title_res.stdout


def test_cli_publish_then_persistent_body_search(tmp_path: Path):
    """
    Verify full offline journey:
    1. Subprocess A publishes document with unique body term to SQLite.
    2. Subprocess B (fresh process) executes search matching that body term.
    3. Output returns the document root hash and content snippet.
    """
    db_file = tmp_path / "search_node.db"
    doc_file = tmp_path / "water_guide.txt"
    doc_text = (
        "Emergency Field Manual: Comprehensive Guidelines for Desalination and Solar Distillation. "
        "Specific focus on bio-sand filtration membranes and chlorine dioxide dosing in disaster zones."
    )
    doc_file.write_text(doc_text, encoding="utf-8")

    # Step 1: Publish document
    pub_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "publish", str(doc_file),
            "--title", "Solar Desalination Field Manual",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "File Published & Persisted Successfully" in pub_res.stdout
    root_hash = None
    for line in pub_res.stdout.splitlines():
        if "Root Hash" in line:
            root_hash = line.split(":")[-1].strip()
            break
    assert root_hash is not None

    # Step 2: Fresh process search by a unique body term ("chlorine dioxide")
    search_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "search", "chlorine dioxide",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "[TFP SEARCH] Found" in search_res.stdout
    assert root_hash in search_res.stdout
    assert "chlorine dioxide" in search_res.stdout.lower()

    # Step 3: Fresh process search by title term ("desalination")
    title_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "search", "desalination",
            "--top-k", "3",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "[TFP SEARCH] Found" in title_res.stdout
    assert root_hash in title_res.stdout
