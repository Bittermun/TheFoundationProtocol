# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Test Suite for Kiwix / ZIM Offline Knowledge Exporter.

Verifies:
1. Standard ZIM directory layout (index.html, A/ articles, M/ metadata).
2. Client-side search and responsive styling in index.html.
3. Preservation of cryptographic Merkle roots and FastCDC metadata in manifest.json.
4. Slugification and HTML generation integrity.
"""

import json
from pathlib import Path
import tempfile
import pytest

from tfp_client.lib.ingest.article_packager import PackagedArticleBundle
from tfp_client.lib.ingest.zim_exporter import ZimDirectoryExporter, slugify


def test_slugify():
    assert slugify("Cholera Field Triage (2026)") == "cholera-field-triage-2026"
    assert slugify("Solar Still: Water Purification") == "solar-still-water-purification"
    assert slugify("   Clean   Water   ") == "clean-water"


def test_zim_directory_export_layout():
    exporter = ZimDirectoryExporter(publisher="Foundation Health", language="eng")

    bundles = [
        PackagedArticleBundle(
            title="Cholera Field Triage & Oral Rehydration",
            category="Medical",
            merkle_root="a1b2c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596",
            raw_size_bytes=4500,
            compressed_size_bytes=1200,
            savings_pct=73.3,
            chunk_count=5,
            standalone_html="<html><body><h1>Cholera Triage</h1><p>Rehydrate with ORS salts.</p></body></html>",
            metadata={"tags": ["cholera", "triage"]},
        ),
        PackagedArticleBundle(
            title="Solar Still Water Purification",
            category="Survival",
            merkle_root="f6e5d4c3b2a107182930415263748596f6e5d4c3b2a107182930415263748596",
            raw_size_bytes=3200,
            compressed_size_bytes=950,
            savings_pct=70.3,
            chunk_count=3,
            standalone_html="<html><body><h1>Solar Still</h1><p>Distill potable water.</p></body></html>",
            metadata={"tags": ["water", "solar"]},
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp) / "zim_archive"
        exporter.export_bundles(bundles, export_path, library_title="Disaster Survival Manual")

        # 1. Verify root index.html
        index_file = export_path / "index.html"
        assert index_file.exists()
        index_content = index_file.read_text(encoding="utf-8")
        assert "Disaster Survival Manual" in index_content
        assert "Kiwix / ZIM Compatible Archive" in index_content
        assert "filterArticles()" in index_content
        assert "Medical" in index_content
        assert "Survival" in index_content

        # 2. Verify A/ namespace articles
        articles_dir = export_path / "A"
        assert articles_dir.is_dir()
        art1 = articles_dir / "cholera-field-triage-oral-rehydration.html"
        art2 = articles_dir / "solar-still-water-purification.html"
        assert art1.exists()
        assert art2.exists()
        assert "Rehydrate with ORS salts." in art1.read_text(encoding="utf-8")

        # 3. Verify M/ metadata namespace
        metadata_dir = export_path / "M"
        assert metadata_dir.is_dir()
        assert (metadata_dir / "Title").read_text(encoding="utf-8") == "Disaster Survival Manual"
        assert (metadata_dir / "Creator").read_text(encoding="utf-8") == "Foundation Health"
        assert (metadata_dir / "Language").read_text(encoding="utf-8") == "eng"
        assert (metadata_dir / "Date").exists()

        # 4. Verify manifest.json
        manifest_file = export_path / "manifest.json"
        assert manifest_file.exists()
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest_data["article_count"] == 2
        assert manifest_data["articles"][0]["merkle_root"] == bundles[0].merkle_root
        assert manifest_data["articles"][1]["merkle_root"] == bundles[1].merkle_root


def test_slug_collision_disambiguation_zero_data_loss(tmp_path: Path):
    """
    Regression test: Exporting articles titled 'A B' and 'A-B' must generate
    unique filenames and preserve both articles without data loss.
    """
    exporter = ZimDirectoryExporter()
    bundles = [
        PackagedArticleBundle(
            title="A B",
            category="Test",
            merkle_root="1" * 64,
            raw_size_bytes=100,
            compressed_size_bytes=50,
            savings_pct=50.0,
            chunk_count=1,
            standalone_html="<html><body>FIRST ARTICLE A B</body></html>",
            metadata={},
        ),
        PackagedArticleBundle(
            title="A-B",
            category="Test",
            merkle_root="2" * 64,
            raw_size_bytes=100,
            compressed_size_bytes=50,
            savings_pct=50.0,
            chunk_count=1,
            standalone_html="<html><body>SECOND ARTICLE A-B</body></html>",
            metadata={},
        ),
    ]

    export_path = tmp_path / "zim_collision"
    exporter.export_bundles(bundles, export_path)

    articles_dir = export_path / "A"
    art1_file = articles_dir / "a-b.html"
    art2_file = articles_dir / "a-b-1.html"

    # Both HTML files must exist with their respective distinct content
    assert art1_file.exists(), "First article 'a-b.html' must exist"
    assert art2_file.exists(), "Colliding second article 'a-b-1.html' must exist"
    assert "FIRST ARTICLE" in art1_file.read_text(encoding="utf-8")
    assert "SECOND ARTICLE" in art2_file.read_text(encoding="utf-8")

    # Manifest must list both articles with their distinct filenames
    manifest = json.loads((export_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["article_count"] == 2
    assert len(list(articles_dir.glob("*.html"))) == 2
