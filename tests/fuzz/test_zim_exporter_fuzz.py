# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Property-Based Fuzz Testing for Kiwix / ZIM Directory Exporter.

Verifies invariants:
1. Path Traversal & Slug Sandboxing: Arbitrary title strings (including traversal sequences,
   slashes, null bytes, and non-ASCII) can NEVER escape the target ZIM 'A/' directory.
2. Manifest Integrity: JSON manifest is always strictly valid, well-formed JSON across arbitrary inputs.
3. Index Resiliency: index.html is generated without unhandled formatting or template injection crashes.
"""

import json
from pathlib import Path
from hypothesis import given, settings, strategies as st
import pytest

from tfp_client.lib.ingest.article_packager import PackagedArticleBundle
from tfp_client.lib.ingest.zim_exporter import ZimDirectoryExporter, slugify


class TestZimExporterHypothesisFuzz:
    """Property-based verification of ZimDirectoryExporter."""

    @settings(max_examples=50, deadline=None)
    @given(raw_title=st.text(min_size=0, max_size=200))
    def test_slugify_path_traversal_immunity(self, raw_title: str):
        """Invariant: slugify output cannot traverse directories or contain path separators."""
        slug = slugify(raw_title)
        assert "/" not in slug
        assert "\\" not in slug
        assert ".." not in slug
        assert "\x00" not in slug
        assert len(slug) > 0

    @settings(max_examples=30, deadline=None)
    @given(
        title=st.text(min_size=1, max_size=80),
        category=st.text(min_size=0, max_size=30),
        html_payload=st.text(min_size=0, max_size=2_000),
    )
    def test_export_bundles_arbitrary_metadata_safety(
        self, tmp_path_factory, title: str, category: str, html_payload: str
    ):
        """Invariant: export_bundles safely creates valid ZIM directory hierarchy."""
        tmp_dir = tmp_path_factory.mktemp("zim_fuzz")
        bundle = PackagedArticleBundle(
            title=title,
            category=category,
            merkle_root="a" * 64,
            raw_size_bytes=len(html_payload),
            compressed_size_bytes=len(html_payload),
            savings_pct=0.0,
            chunk_count=1,
            standalone_html=html_payload,
            metadata={"source": "fuzz"},
        )

        exporter = ZimDirectoryExporter()
        index_path = exporter.export_bundles([bundle], target_dir=tmp_dir)

        # 1. Index file must exist
        assert index_path.exists()
        assert (tmp_dir / "index.html").exists()

        # 2. Manifest file must be valid JSON
        manifest_file = tmp_dir / "manifest.json"
        assert manifest_file.exists()
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert "articles" in manifest_data
        assert len(manifest_data["articles"]) == 1

        # 3. All files in A/ must be inside tmp_dir / "A"
        articles_dir = tmp_dir / "A"
        for article_file in articles_dir.glob("*.html"):
            resolved = article_file.resolve()
            assert str(resolved).startswith(str(articles_dir.resolve()))
