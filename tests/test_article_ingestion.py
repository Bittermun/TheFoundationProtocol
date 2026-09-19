# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import pytest
from pathlib import Path

from tfp_client.lib.ingest.article_ingester import ArticleIngester, ExtractedArticle
from tfp_client.lib.ingest.article_packager import ArticlePackager


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Cholera Prevention and Water Treatment Protocols - Wikipedia</title>
  <style>body { color: red; }</style>
  <script>console.log("tracking script");</script>
</head>
<body>
  <nav><a href="/home">Home</a> | <a href="/login">Login</a></nav>
  <div class="ad-banner">Buy Cheap Medicine Online!</div>
  
  <h1>Cholera Prevention and Water Treatment Protocols</h1>
  <p>Cholera is an acute diarrheal infection caused by ingestion of food or water contaminated with the bacterium Vibrio cholerae.</p>
  
  <h2>Emergency Water Treatment</h2>
  <p>Providing safe water and proper sanitation is critical to prevent and control the transmission of cholera and other waterborne diseases.</p>
  <ul>
    <li>Boil water vigorously for at least one minute before drinking.</li>
    <li>Use chlorine tablets or household bleach (3 to 5 drops per liter) when boiling is not possible.</li>
    <li>Store treated water in clean, covered containers with narrow necks.</li>
  </ul>

  <h2>Oral Rehydration Therapy</h2>
  <p>Patients should be administered oral rehydration salts (ORS) immediately upon showing signs of severe dehydration.</p>
  
  <footer>Copyright &copy; 2026 Emergency Health Organization. All rights reserved.</footer>
</body>
</html>
"""


def test_article_ingester_html_sanitization():
    article = ArticleIngester.ingest_html(SAMPLE_HTML, source_url="https://health.org/cholera")
    
    assert article.title == "Cholera Prevention and Water Treatment Protocols"
    assert "Cholera is an acute diarrheal infection" in article.summary
    assert article.category == "medical"
    assert article.reading_time_minutes >= 1
    assert article.word_count > 40
    
    # Assert unwanted elements were stripped
    combined_text = " ".join([p for s in article.sections for p in s.paragraphs] + [b for s in article.sections for b in s.bullets])
    assert "tracking script" not in combined_text
    assert "Home" not in combined_text
    assert "Buy Cheap Medicine" not in combined_text
    assert "All rights reserved" not in combined_text
    
    # Assert sections and bullets preserved
    section_headings = [s.heading for s in article.sections]
    assert "Emergency Water Treatment" in section_headings
    assert "Oral Rehydration Therapy" in section_headings
    
    treatment_sec = next(s for s in article.sections if s.heading == "Emergency Water Treatment")
    assert len(treatment_sec.bullets) == 3
    assert any("Boil water vigorously" in b for b in treatment_sec.bullets)


def test_article_ingester_markdown():
    md = """# Rapid Flood Evacuation Guide
> Emergency guidelines for flash floods in river valleys.

## High Ground Movement
Immediately move to designated community shelters on ridges or reinforced school roofs.
- Avoid walking or driving through moving water.
- Bring emergency go-bags with dry rations and flashlight.

## Signal Protocol
Flash mirrors or whistle 3 short bursts repeatedly to signal emergency aerial rescue teams.
"""
    article = ArticleIngester.ingest_markdown(md, source_url="offline/flood.md")
    assert article.title == "Rapid Flood Evacuation Guide"
    assert article.category == "disaster"
    assert len(article.sections) >= 2


def test_article_packager_compression_and_reader():
    article = ArticleIngester.ingest_html(SAMPLE_HTML)
    packager = ArticlePackager()
    bundle = ArticlePackager.package_article(packager, article)
    
    assert bundle.title == "Cholera Prevention and Water Treatment Protocols"
    assert bundle.category == "medical"
    assert bundle.raw_size_bytes > 0
    assert bundle.compressed_size_bytes > 0
    assert bundle.compressed_size_bytes < bundle.raw_size_bytes
    assert bundle.savings_pct > 30.0  # Lexicon compression yields substantial savings
    assert len(bundle.merkle_root) == 64  # SHA3-256 root hex
    assert bundle.chunk_count >= 1
    
    # Verify standalone mobile HTML
    assert "<!DOCTYPE html>" in bundle.standalone_html
    assert "speechSynthesis" in bundle.standalone_html
    assert "Cholera Prevention" in bundle.standalone_html
    assert "localStorage.setItem" in bundle.standalone_html
