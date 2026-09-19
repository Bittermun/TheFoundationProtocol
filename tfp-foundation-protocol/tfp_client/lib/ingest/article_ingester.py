# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Web & Article Content Ingestion Adapter.

A zero-browser, pure-Python HTML/Markdown extractor and sanitizer.
Extracts structured headings, summaries, key takeaways, and paragraphs
from arbitrary web URLs, Wikipedia articles, or emergency bulletins
without requiring Chromium, Puppeteer, or heavy dependencies.
"""

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, ClassVar


@dataclass
class ArticleSection:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedArticle:
    title: str
    summary: str
    sections: list[ArticleSection]
    category: str
    reading_time_minutes: int
    word_count: int
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "reading_time_minutes": self.reading_time_minutes,
            "word_count": self.word_count,
            "source_url": self.source_url,
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_markdown(self) -> str:
        lines = [f"# {self.title}\n"]
        if self.summary:
            lines.append(f"> **Summary**: {self.summary}\n")
        lines.append(f"*Category: {self.category} | Reading Time: ~{self.reading_time_minutes} min*\n")
        lines.append("---\n")

        for sec in self.sections:
            if sec.heading and sec.heading != self.title:
                lines.append(f"## {sec.heading}\n")
            for p in sec.paragraphs:
                lines.append(f"{p}\n")
            for b in sec.bullets:
                lines.append(f"- {b}")
            if sec.bullets:
                lines.append("")

        return "\n".join(lines).strip()


class _HTMLSanitizerParser(HTMLParser):
    """Internal HTML parser that strips boilerplate and extracts structure."""

    SKIP_TAGS: ClassVar[set[str]] = {
        "script", "style", "noscript", "nav", "footer", "header",
        "aside", "iframe", "svg", "form", "button", "menu"
    }

    HEADING_TAGS: ClassVar[set[str]] = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__()
        self.skip_stack = 0
        self.in_title = False
        self.extracted_title = ""
        self.current_heading = "Overview"
        self.current_tag = None
        self.current_text = []

        self.sections: list[ArticleSection] = []
        self._curr_section = ArticleSection(heading="Overview")
        self.in_list_item = False

    SKIP_CLASS_KEYWORDS = ("ad-", "ad ", "ads ", "banner", "promo", "sponsor", "sidebar", "cookie", "social-share")

    def handle_starttag(self, tag: str, attrs: list[tuple]):
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "").lower() for k, v in attrs}
        class_or_id = f"{attr_dict.get('class', '')} {attr_dict.get('id', '')}"
        is_ad = any(kw in class_or_id for kw in self.SKIP_CLASS_KEYWORDS)

        if tag_lower in self.SKIP_TAGS or is_ad:
            self.skip_stack += 1
            return

        if self.skip_stack > 0:
            self.skip_stack += 1
            return

        self.current_tag = tag_lower
        if tag_lower == "title":
            self.in_title = True
        elif tag_lower in self.HEADING_TAGS:
            self._flush_text_to_section()
        elif tag_lower == "li":
            self.in_list_item = True
            self._flush_text_to_section()
        elif tag_lower == "p":
            self._flush_text_to_section()

    def handle_endtag(self, tag: str):
        if self.skip_stack > 0:
            self.skip_stack -= 1
            return

        tag_lower = tag.lower()

        if tag_lower == "title":
            self.in_title = False
            title_candidate = "".join(self.current_text).strip()
            if title_candidate and not self.extracted_title:
                self.extracted_title = title_candidate
            self.current_text = []
        elif tag_lower in self.HEADING_TAGS:
            heading_text = "".join(self.current_text).strip()
            self.current_text = []
            if heading_text:
                if not self.extracted_title and tag_lower in ("h1", "h2"):
                    self.extracted_title = heading_text
                # Commit current section if it has content
                if self._curr_section.paragraphs or self._curr_section.bullets:
                    self.sections.append(self._curr_section)
                self._curr_section = ArticleSection(heading=heading_text)
        elif tag_lower == "p":
            para_text = "".join(self.current_text).strip()
            self.current_text = []
            if para_text:
                self._curr_section.paragraphs.append(para_text)
        elif tag_lower == "li":
            bullet_text = "".join(self.current_text).strip()
            self.current_text = []
            if bullet_text:
                self._curr_section.bullets.append(bullet_text)
            self.in_list_item = False

    def handle_data(self, data: str):
        if self.skip_stack > 0:
            return
        if data:
            self.current_text.append(data)

    def _flush_text_to_section(self):
        text = "".join(self.current_text).strip()
        self.current_text = []
        if text:
            if self.in_list_item:
                self._curr_section.bullets.append(text)
            elif len(text) > 20:
                self._curr_section.paragraphs.append(text)

    def finalize(self):
        self._flush_text_to_section()
        if self._curr_section.paragraphs or self._curr_section.bullets:
            self.sections.append(self._curr_section)


class ArticleIngester:
    """Ingests raw HTML, Markdown, or web URLs into clean structured articles."""

    CATEGORY_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "medical": ["symptom", "disease", "treatment", "patient", "dose", "clinical", "virus", "infection", "vaccine", "health", "triage"],
        "disaster": ["flood", "earthquake", "cyclone", "evacuation", "shelter", "rescue", "emergency", "hazard", "relief", "warning"],
        "technical": ["protocol", "network", "packet", "algorithm", "software", "radio", "server", "hardware", "encryption", "interface"],
        "education": ["lesson", "student", "history", "geography", "mathematics", "science", "school", "learning", "curriculum"],
    }

    @classmethod
    def ingest_html(cls, html_str: str, source_url: str = "") -> ExtractedArticle:
        """Parses and sanitizes an HTML document."""
        parser = _HTMLSanitizerParser()
        parser.feed(html_str)
        parser.finalize()

        title = parser.extracted_title.strip() or "Untitled Document"
        # Clean title suffix (e.g. "Article Name - Wikipedia")
        title = re.sub(r"\s*[-|–—].*$", "", title).strip() or title

        all_paras = []
        for sec in parser.sections:
            all_paras.extend(sec.paragraphs)

        summary = ""
        for p in all_paras:
            if len(p) > 60:
                summary = p
                break
        if not summary and all_paras:
            summary = all_paras[0]

        full_text = " ".join(all_paras)
        words = re.findall(r"\w+", full_text)
        word_count = len(words)
        reading_time = max(1, word_count // 180)  # ~180 wpm on mobile

        category = cls._detect_category(full_text + " " + title)

        return ExtractedArticle(
            title=title,
            summary=summary,
            sections=parser.sections,
            category=category,
            reading_time_minutes=reading_time,
            word_count=word_count,
            source_url=source_url,
        )

    @classmethod
    def ingest_markdown(cls, md_str: str, source_url: str = "") -> ExtractedArticle:
        """Parses structured Markdown into an ExtractedArticle."""
        lines = md_str.splitlines()
        title = "Untitled Document"
        sections: list[ArticleSection] = []
        curr_section = ArticleSection(heading="Overview")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("# ") and title == "Untitled Document":
                title = stripped[2:].strip()
            elif stripped.startswith(("## ", "### ")):
                if curr_section.paragraphs or curr_section.bullets:
                    sections.append(curr_section)
                heading = stripped.lstrip("#").strip()
                curr_section = ArticleSection(heading=heading)
            elif stripped.startswith(("- ", "* ")):
                curr_section.bullets.append(stripped[2:].strip())
            elif not stripped.startswith("#"):
                curr_section.paragraphs.append(stripped)

        if curr_section.paragraphs or curr_section.bullets:
            sections.append(curr_section)

        all_paras = []
        for s in sections:
            all_paras.extend(s.paragraphs)

        summary = all_paras[0] if all_paras else ""
        full_text = " ".join(all_paras)
        words = re.findall(r"\w+", full_text)
        word_count = len(words)
        reading_time = max(1, word_count // 180)

        category = cls._detect_category(full_text + " " + title)

        return ExtractedArticle(
            title=title,
            summary=summary,
            sections=sections,
            category=category,
            reading_time_minutes=reading_time,
            word_count=word_count,
            source_url=source_url,
        )

    @classmethod
    def ingest_url(cls, url: str, timeout: float = 10.0) -> ExtractedArticle:
        """Fetches and cleans a web article over HTTP/HTTPS with proper headers."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError(
                f"Disallowed URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted."
            )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FoundationProtocol-Ingester/1.0 (Offline Education/Relief Reader)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                charset = resp.headers.get_content_charset() or "utf-8"
                html_data = resp.read().decode(charset, errors="replace")
            return cls.ingest_html(html_data, source_url=url)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return ExtractedArticle(
                title=f"Offline Cached Stub for {url}",
                summary=f"Ingestion notice: network source unreachable ({e}).",
                sections=[ArticleSection(heading="Notice", paragraphs=[f"Source URL: {url}"])],
                category="technical",
                reading_time_minutes=1,
                word_count=10,
                source_url=url,
            )

    @classmethod
    def _detect_category(cls, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for cat, kw_list in cls.CATEGORY_KEYWORDS.items():
            scores[cat] = sum(1 for kw in kw_list if kw in text_lower)

        best_cat = max(scores, key=scores.get)
        return best_cat if scores[best_cat] > 0 else "education"
