# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acceptance tests for Package Asset Resolution and Search Transparency.

Proves that:
1. get_static_assets_dir() resolves the valid static assets directory containing
   visualizer.html and acoustic_receiver.html across runtime environments.
2. tfp search on an empty database explicitly notifies the user of 0 published
   articles and prefixes demo results with [DEMO].
3. tfp search on a database with published articles searches and indexes the real
   database contents, reporting the exact number of indexed persisted documents.
"""

from io import StringIO
import sys
from unittest.mock import patch
from tfp_core_v4.cli import get_static_assets_dir, main
from tfp_core_v4.node import TFPNode


def test_get_static_assets_dir_resolves_files():
    """Verify that static assets directory resolves and contains required HTML files."""
    static_dir = get_static_assets_dir()
    assert static_dir.is_dir()
    assert (static_dir / "visualizer.html").is_file()
    assert (static_dir / "acoustic_receiver.html").is_file()


def test_cli_search_empty_database_transparency(tmp_path):
    """Verify that an empty database triggers the explicit demo fallback notice and prefixes."""
    empty_db = tmp_path / "empty.db"
    # Ensure database file exists
    node = TFPNode(db_path=empty_db)
    del node

    stdout_capture = StringIO()
    with patch("sys.stdout", stdout_capture):
        main(["search", "hypothermia", "--db", str(empty_db)])

    output = stdout_capture.getvalue()
    assert "0 published articles found" in output
    assert "Searching built-in emergency demonstration corpus:" in output
    assert "[DEMO] doc2:" in output


def test_cli_search_persisted_content_reporting(tmp_path):
    """Verify that a database with published articles reports real document search."""
    populated_db = tmp_path / "populated.db"
    node = TFPNode(db_path=populated_db)
    node.publish(
        b"Acute hypothermia field resuscitation protocols and rewarming guidelines.",
        metadata={"title": "Emergency Cold Weather Triage"},
    )

    stdout_capture = StringIO()
    with patch("sys.stdout", stdout_capture):
        main(["search", "hypothermia", "--db", str(populated_db)])

    output = stdout_capture.getvalue()
    assert "Indexed 1 persisted document(s)" in output
    assert "0 published articles found" not in output
    assert "Emergency Cold Weather Triage" in output
