# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Integration test verifying persistent SQLite search via CLI:
Publish document -> process exit -> search by body term in fresh process -> match returned.
"""

import subprocess
import sys
from pathlib import Path


def test_cli_search_empty_db_fallback(tmp_path: Path):
    """Verify that search falls back to demo corpus if database is empty."""
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
    assert "[TFP SEARCH] Found" in res.stdout
    assert "doc1" in res.stdout
    assert "water purification and sanitation" in res.stdout


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
