# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Article Packager for Weak Mobile Phones.

Packages extracted articles into ultra-compact bundles (< 15 KB)
compressed with domain .zdict dictionaries, sliced with FastCDC,
and self-contained in a zero-dependency offline HTML mobile reader.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tfp_client.lib.lexicon.adapter_real import RealLexiconAdapter
from tfp_client.lib.media.stream_packager import MediaStreamPackager

from .article_ingester import ExtractedArticle


@dataclass
class PackagedArticleBundle:
    title: str
    category: str
    merkle_root: str
    raw_size_bytes: int
    compressed_size_bytes: int
    savings_pct: float
    chunk_count: int
    standalone_html: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "merkle_root": self.merkle_root,
            "raw_size_bytes": self.raw_size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "savings_pct": round(self.savings_pct, 2),
            "chunk_count": self.chunk_count,
            "metadata": self.metadata,
        }


class ArticlePackager:
    """Packages structured articles for distribution over constrained wireless links."""

    def __init__(self, lexicons_dir: Path | None = None):
        if lexicons_dir is None:
            # Default to repo root / lexicons
            root = Path(__file__).resolve().parent.parent.parent.parent.parent
            lexicons_dir = root / "lexicons"
        self.lexicons_dir = lexicons_dir
        self.packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=4096)

    def package_article(self, article: ExtractedArticle) -> PackagedArticleBundle:
        """Converts an ExtractedArticle into an ultra-compact, compressed offline bundle."""
        standalone_html = self.generate_offline_mobile_reader(article)
        raw_bytes = standalone_html.encode("utf-8")
        raw_size = len(raw_bytes)

        # Select domain dictionary based on article category
        dict_name = f"{article.category}.zdict"
        dict_path = self.lexicons_dir / dict_name
        if not dict_path.exists():
            dict_path = self.lexicons_dir / "technical.zdict"

        lexicon = RealLexiconAdapter(lexicon_dir=str(self.lexicons_dir))
        compressed_bytes = lexicon.compress(raw_bytes, tags=[article.category])
        compressed_size = len(compressed_bytes)

        savings_pct = (1.0 - (compressed_size / max(1, raw_size))) * 100.0

        # Run FastCDC chunking and build Merkle tree over the compressed payload
        manifest, chunks, _merkle = self.packager.package(
            media_data=compressed_bytes,
            media_type="application/tfp-article-bundle",
            metadata={"title": article.title[:32]},
        )

        metadata = {
            "title": article.title,
            "summary": article.summary,
            "category": article.category,
            "reading_time_minutes": article.reading_time_minutes,
            "word_count": article.word_count,
            "source_url": article.source_url,
            "dictionary_used": dict_path.name if dict_path.exists() else "generic",
        }

        return PackagedArticleBundle(
            title=article.title,
            category=article.category,
            merkle_root=manifest.merkle_root,
            raw_size_bytes=raw_size,
            compressed_size_bytes=compressed_size,
            savings_pct=savings_pct,
            chunk_count=len(chunks),
            standalone_html=standalone_html,
            metadata=metadata,
        )

    @classmethod
    def generate_offline_mobile_reader(cls, article: ExtractedArticle) -> str:
        """Generates a zero-dependency, ultra-lightweight standalone HTML reader for weak phones."""
        sections_html = []
        full_text_for_tts = [article.title, article.summary]

        for s in article.sections:
            if s.heading and s.heading != article.title:
                sections_html.append(f"<h2 class='sec-title'>{cls._escape_html(s.heading)}</h2>")
                full_text_for_tts.append(s.heading)
            for p in s.paragraphs:
                sections_html.append(f"<p class='para'>{cls._escape_html(p)}</p>")
                full_text_for_tts.append(p)
            if s.bullets:
                sections_html.append("<ul class='bullet-list'>")
                for b in s.bullets:
                    sections_html.append(f"<li>{cls._escape_html(b)}</li>")
                    full_text_for_tts.append(b)
                sections_html.append("</ul>")

        body_html = "\n".join(sections_html)
        tts_script = "\\n".join(full_text_for_tts).replace("'", "\\'").replace('"', '\\"')

        category_colors = {
            "medical": "#ef4444",
            "disaster": "#f59e0b",
            "education": "#10b981",
            "technical": "#3b82f6",
        }
        badge_color = category_colors.get(article.category, "#8b5cf6")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{cls._escape_html(article.title)}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif;
  background: #0f172a;
  color: #f8fafc;
  line-height: 1.6;
  padding: 16px;
  font-size: 16px;
}}
.container {{ max-width: 680px; margin: 0 auto; }}
.badge {{
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  background: {badge_color};
  color: #ffffff;
  margin-bottom: 8px;
}}
h1 {{ font-size: 1.6rem; line-height: 1.25; margin-bottom: 10px; color: #ffffff; }}
.meta-bar {{ font-size: 13px; color: #94a3b8; margin-bottom: 16px; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
.summary-box {{
  background: #1e293b;
  border-left: 4px solid {badge_color};
  padding: 12px;
  border-radius: 0 6px 6px 0;
  margin-bottom: 20px;
  font-size: 0.95rem;
  color: #e2e8f0;
}}
.sec-title {{ font-size: 1.25rem; margin: 24px 0 10px 0; color: #38bdf8; }}
.para {{ margin-bottom: 14px; color: #cbd5e1; text-align: justify; }}
.bullet-list {{ margin: 10px 0 16px 24px; color: #cbd5e1; }}
.bullet-list li {{ margin-bottom: 6px; }}
.audio-bar {{
  position: sticky;
  bottom: 16px;
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 30px;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  margin-top: 30px;
}}
.play-btn {{
  background: #38bdf8;
  color: #0f172a;
  border: none;
  padding: 8px 16px;
  border-radius: 20px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
}}
.offline-tag {{ font-size: 12px; color: #10b981; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
  <span class="badge">{article.category}</span>
  <h1>{cls._escape_html(article.title)}</h1>
  <div class="meta-bar">
    ⏱ ~{article.reading_time_minutes} min read &bull; 📝 {article.word_count} words &bull; 📡 Offline Verified
  </div>
  {f'<div class="summary-box"><strong>Key Takeaway:</strong> {cls._escape_html(article.summary)}</div>' if article.summary else ''}
  {body_html}
  <div class="audio-bar">
    <button class="play-btn" id="ttsBtn" onclick="toggleAudioNarration()">🔊 Read Aloud</button>
    <span class="offline-tag">✓ Stored Offline</span>
  </div>
</div>
<script>
let speaking = false;
const textToSpeak = "{tts_script}";

function toggleAudioNarration() {{
  const btn = document.getElementById('ttsBtn');
  if (!('speechSynthesis' in window)) {{
    alert('Offline Voice is not supported on this browser.');
    return;
  }}
  if (speaking) {{
    window.speechSynthesis.cancel();
    speaking = false;
    btn.innerText = '🔊 Read Aloud';
  }} else {{
    const utter = new SpeechSynthesisUtterance(textToSpeak);
    utter.rate = 0.95;
    utter.onend = () => {{ speaking = false; btn.innerText = '🔊 Read Aloud'; }};
    utter.onerror = () => {{ speaking = false; btn.innerText = '🔊 Read Aloud'; }};
    window.speechSynthesis.speak(utter);
    speaking = true;
    btn.innerText = '⏹ Stop Audio';
  }}
}}

// Automatically cache article locally in localStorage with quota safety guard
try {{
  localStorage.setItem('tfp_article_' + encodeURIComponent("{cls._escape_html(article.title[:24])}"), document.documentElement.outerHTML);
}} catch(e) {{
  console.warn('TFP Offline Storage: quota exceeded or storage unavailable.', e);
}}
</script>
</body>
</html>"""

    @staticmethod
    def _escape_html(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
