# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Kiwix / ZIM Offline Knowledge Exporter.

Packages verified Foundation Protocol articles and FastCDC bundles into standard
ZIM directory structures compatible with `zimwriterfs` and open-source offline
readers (Kiwix on Android, iOS, Windows, Linux, and e-readers).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from .article_packager import PackagedArticleBundle


def slugify(text: str) -> str:
    """Converts title to a safe URL and filesystem slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text or "article"


INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{library_title} - Kiwix Offline Archive</title>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px;
    max-width: 800px;
    margin: 0 auto;
    line-height: 1.6;
  }}
  header {{
    text-align: center;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 20px;
  }}
  .badge {{
    background: rgba(56, 189, 248, 0.15);
    color: var(--accent);
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
    display: inline-block;
    margin-bottom: 8px;
  }}
  h1 {{ margin: 0 0 6px 0; font-size: 1.75rem; }}
  p.sub {{ color: var(--muted); margin: 0; font-size: 14px; }}
  .search-box {{
    width: 100%;
    padding: 12px 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: #fff;
    font-size: 15px;
    margin-bottom: 24px;
    box-sizing: border-box;
  }}
  .category-group {{ margin-bottom: 24px; }}
  .category-title {{
    color: var(--accent);
    font-size: 1.1rem;
    margin-bottom: 12px;
    border-bottom: 1px solid #1e293b;
    padding-bottom: 4px;
  }}
  .article-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
    display: block;
    text-decoration: none;
    color: inherit;
    transition: transform 0.1s, border-color 0.1s;
  }}
  .article-card:hover {{
    border-color: var(--accent);
    transform: translateY(-1px);
  }}
  .article-card h2 {{
    margin: 0 0 6px 0;
    font-size: 1.1rem;
    color: #fff;
  }}
  .article-meta {{
    font-size: 12px;
    color: var(--muted);
    display: flex;
    gap: 16px;
  }}
  footer {{
    text-align: center;
    font-size: 12px;
    color: var(--muted);
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }}
</style>
<script>
function filterArticles() {{
  const query = document.getElementById('search').value.toLowerCase();
  const cards = document.querySelectorAll('.article-card');
  cards.forEach(c => {{
    const title = c.getAttribute('data-title').toLowerCase();
    const cat = c.getAttribute('data-category').toLowerCase();
    if (title.includes(query) || cat.includes(query)) {{
      c.style.display = 'block';
    }} else {{
      c.style.display = 'none';
    }}
  }});
}}
</script>
</head>
<body>
  <header>
    <span class="badge">Kiwix / ZIM Compatible Archive</span>
    <h1>{library_title}</h1>
    <p class="sub">Delivered via The Foundation Protocol resilient radio & airgap mesh</p>
  </header>

  <input type="text" id="search" class="search-box" placeholder="Search offline articles..." onkeyup="filterArticles()">

  <div id="articleCatalog">
    {article_listings}
  </div>

  <footer>
    Generated on {generated_date} • Standard ZIM Layout for Kiwix Offline Readers
  </footer>
</body>
</html>
"""


class ZimDirectoryExporter:
    """
    Exports Foundation Protocol articles into standard ZIM directory hierarchies.
    """

    def __init__(self, publisher: str = "The Foundation Protocol", language: str = "eng"):
        self.publisher = publisher
        self.language = language

    def export_bundles(
        self,
        bundles: List[PackagedArticleBundle],
        target_dir: Path,
        library_title: str = "Emergency Medical & Triage Library",
        description: str = "Airgap radio-delivered offline encyclopedia articles.",
    ) -> Path:
        """
        Exports a collection of PackagedArticleBundles into a ZIM directory tree.
        """
        target_dir = Path(target_dir)
        articles_dir = target_dir / "A"
        metadata_dir = target_dir / "M"
        articles_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)

        catalog_by_category: Dict[str, List[Dict[str, Any]]] = {}
        manifest_entries: List[Dict[str, Any]] = []

        for bundle in bundles:
            slug = slugify(bundle.title)
            article_filename = f"{slug}.html"
            article_path = articles_dir / article_filename

            # Write self-contained HTML
            html_content = bundle.standalone_html
            if not html_content:
                html_content = f"<!DOCTYPE html><html><head><title>{bundle.title}</title></head><body><h1>{bundle.title}</h1><p>Category: {bundle.category}</p></body></html>"

            with open(article_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            cat = bundle.category or "General"
            if cat not in catalog_by_category:
                catalog_by_category[cat] = []

            catalog_by_category[cat].append({
                "title": bundle.title,
                "slug": slug,
                "href": f"A/{article_filename}",
                "category": cat,
                "raw_size": bundle.raw_size_bytes,
                "merkle_root": bundle.merkle_root,
            })

            manifest_entries.append({
                "title": bundle.title,
                "slug": slug,
                "category": cat,
                "merkle_root": bundle.merkle_root,
                "raw_size_bytes": bundle.raw_size_bytes,
                "compressed_size_bytes": bundle.compressed_size_bytes,
                "chunk_count": bundle.chunk_count,
            })

        # Build article listings HTML
        listing_html_parts = []
        for cat, items in sorted(catalog_by_category.items()):
            listing_html_parts.append(f'<div class="category-group"><div class="category-title">{cat}</div>')
            for item in items:
                listing_html_parts.append(
                    f'<a href="{item["href"]}" class="article-card" data-title="{item["title"]}" data-category="{item["category"]}">'
                    f'<h2>{item["title"]}</h2>'
                    f'<div class="article-meta"><span>Size: {item["raw_size"]} B</span><span>Root: {item["merkle_root"][:12]}...</span></div>'
                    f'</a>'
                )
            listing_html_parts.append('</div>')

        # Write root index.html
        index_html = INDEX_HTML_TEMPLATE.format(
            library_title=library_title,
            article_listings="\n".join(listing_html_parts),
            generated_date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        with open(target_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)

        # Write ZIM Metadata (Standard M/ namespace)
        meta_items = {
            "Title": library_title,
            "Description": description,
            "Creator": self.publisher,
            "Publisher": self.publisher,
            "Language": self.language,
            "Date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        for k, v in meta_items.items():
            with open(metadata_dir / k, "w", encoding="utf-8") as f:
                f.write(v)

        # Write TFP cryptographic manifest
        tfp_manifest = {
            "library_title": library_title,
            "publisher": self.publisher,
            "language": self.language,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "article_count": len(bundles),
            "articles": manifest_entries,
        }
        with open(target_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(tfp_manifest, f, indent=2)

        return target_dir
