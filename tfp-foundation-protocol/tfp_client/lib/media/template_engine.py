# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Semantic Lexicon Template Presentation Engine for TFP v4.0.

Provides structured, low-bandwidth visual slide & presentation templates
with synchronized audio narration cues, enabling rich educational and medical
multimedia broadcasts over narrowband radio links in under 1.5 Kilobytes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure tfp roots are available
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.lexicon.adapter_real import RealLexiconAdapter, Content


@dataclass
class SlideElement:
    """Individual visual or auditory component on a presentation slide."""

    element_type: str  # "heading", "paragraph", "bullet_list", "triage_badge", "callout", "narration"
    content: Union[str, List[str]]
    properties: Dict[str, Any] = field(default_factory=dict)
    # Properties may contain: "level" (1-3), "color" ("red", "yellow", "green", "blue"),
    # "highlight": bool, "timing_ms": int (timestamp for local TTS synchronization)


@dataclass
class PresentationSlide:
    """A single structured presentation slide or display frame."""

    slide_id: str
    title: str
    layout: str  # "hero_card", "two_column", "triage_alert", "diagram_focus", "bullet_stack"
    elements: List[SlideElement] = field(default_factory=list)
    duration_ms: int = 5000  # suggested display duration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "title": self.title,
            "layout": self.layout,
            "duration_ms": self.duration_ms,
            "elements": [asdict(e) for e in self.elements],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PresentationSlide:
        elements = [
            SlideElement(
                element_type=e["element_type"],
                content=e["content"],
                properties=e.get("properties", {}),
            )
            for e in d.get("elements", [])
        ]
        return cls(
            slide_id=d["slide_id"],
            title=d["title"],
            layout=d.get("layout", "hero_card"),
            duration_ms=d.get("duration_ms", 5000),
            elements=elements,
        )


@dataclass
class PresentationManifest:
    """Complete multi-slide structured presentation package."""

    manifest_id: str
    title: str
    domain: str  # "medical", "disaster", "technical", "education"
    slides: List[PresentationSlide] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "title": self.title,
            "domain": self.domain,
            "slides": [s.to_dict() for s in self.slides],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PresentationManifest:
        slides = [PresentationSlide.from_dict(s) for s in d.get("slides", [])]
        return cls(
            manifest_id=d["manifest_id"],
            title=d["title"],
            domain=d.get("domain", "medical"),
            slides=slides,
            metadata=d.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_json(cls, json_str: str) -> PresentationManifest:
        return cls.from_dict(json.loads(json_str))

    def compress_with_lexicon(
        self,
        adapter: Optional[RealLexiconAdapter] = None,
    ) -> bytes:
        """Compress serialized presentation using specialized domain Zstandard lexicon."""
        adapter = adapter or RealLexiconAdapter()
        raw_bytes = self.to_json().encode("utf-8")
        return adapter.compress(raw_bytes, tags=[self.domain])

    @classmethod
    def decompress_with_lexicon(
        cls,
        compressed_bytes: bytes,
        domain: str = "medical",
        adapter: Optional[RealLexiconAdapter] = None,
    ) -> PresentationManifest:
        """Decompress bytes using domain dictionary back to PresentationManifest."""
        adapter = adapter or RealLexiconAdapter()
        decompressed_bytes, _ = adapter.decompress(compressed_bytes, tags=[domain])
        return cls.from_json(decompressed_bytes.decode("utf-8"))


class TemplateParser:
    """
    Parses human-readable educational or emergency Markdown into a structured
    PresentationManifest.
    """

    @classmethod
    def from_markdown(
        cls,
        markdown_text: str,
        manifest_id: str = "pres_01",
        title: str = "Educational Broadcast",
        domain: str = "medical",
    ) -> PresentationManifest:
        """
        Parse markdown sections separated by '---' or headings into presentation slides.
        """
        raw_sections = re.split(r"\n---\n", markdown_text.strip())
        slides: List[PresentationSlide] = []

        for idx, section in enumerate(raw_sections):
            lines = [line.strip() for line in section.strip().split("\n") if line.strip()]
            if not lines:
                continue

            slide_title = f"Slide {idx + 1}"
            layout = "hero_card"
            elements: List[SlideElement] = []
            bullet_acc: List[str] = []

            for line in lines:
                # Top-level heading
                if line.startswith("# "):
                    slide_title = line[2:].strip()
                elif line.startswith("## "):
                    elements.append(SlideElement(element_type="heading", content=line[3:].strip(), properties={"level": 2}))
                # Triage badge tags e.g. [RED], [YELLOW], [GREEN]
                elif re.match(r"^\[(RED|YELLOW|GREEN|CRITICAL)\]", line, re.IGNORECASE):
                    tag = re.findall(r"^\[(.*?)\]", line)[0].upper()
                    rest = line[len(tag) + 2:].strip()
                    layout = "triage_alert"
                    elements.append(SlideElement(
                        element_type="triage_badge",
                        content=tag,
                        properties={"color": "red" if tag in ("RED", "CRITICAL") else ("yellow" if tag == "YELLOW" else "green"), "description": rest},
                    ))
                # Alert callouts
                elif line.startswith("> "):
                    callout_text = line[2:].strip()
                    elements.append(SlideElement(
                        element_type="callout",
                        content=callout_text,
                        properties={"highlight": True},
                    ))
                # Bullets
                elif line.startswith("- ") or line.startswith("* "):
                    bullet_acc.append(line[2:].strip())
                # Narration speech script e.g. (Voice: text...)
                elif line.startswith("(") and line.endswith(")"):
                    elements.append(SlideElement(
                        element_type="narration",
                        content=line[1:-1].strip(),
                        properties={"for_tts": True},
                    ))
                # Standard paragraph
                else:
                    if bullet_acc:
                        elements.append(SlideElement(element_type="bullet_list", content=list(bullet_acc)))
                        bullet_acc.clear()
                    elements.append(SlideElement(element_type="paragraph", content=line))

            if bullet_acc:
                elements.append(SlideElement(element_type="bullet_list", content=list(bullet_acc)))

            slides.append(PresentationSlide(
                slide_id=f"slide_{idx + 1:02d}",
                title=slide_title,
                layout=layout,
                elements=elements,
            ))

        return PresentationManifest(
            manifest_id=manifest_id,
            title=title,
            domain=domain,
            slides=slides,
        )
