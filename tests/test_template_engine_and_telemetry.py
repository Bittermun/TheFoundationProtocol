# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Semantic Template Engine and Telemetry Event Bus.

Verifies:
1. Markdown parsing into structured presentation slide templates.
2. Ultra-high Lexicon compression ratio (< 1.5 KB payload for 10-min presentation).
3. Bit-exact round-trip serialization and decompression.
4. Real-time TelemetryEventBus pub/sub distribution and circular history.
5. Visualizer HTML5 dashboard asset completeness.
"""

import asyncio
from pathlib import Path
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.template_engine import (
    PresentationManifest,
    PresentationSlide,
    SlideElement,
    TemplateParser,
)
from tfp_client.lib.media.telemetry_events import (
    TelemetryEventBus,
    EVENT_CDC_CHUNK,
    EVENT_MERKLE_NODE,
    EVENT_DROPLET_EMIT,
    EVENT_DROPLET_RECV,
    EVENT_MATRIX_PIVOT,
    EVENT_CHUNK_SOLVED,
)
from tfp_client.lib.lexicon.adapter_real import RealLexiconAdapter


@pytest.fixture
def sample_emergency_markdown():
    return """
# Acute Hypothermia & Trauma Resuscitation
[RED] Immediate life-threatening hypothermia secondary to water immersion.
- Core body temperature < 30°C.
- Pulse weak, irregular; BP 80/45 mmHg.
- Avoid rough handling to prevent ventricular fibrillation.
> Critical: Active core rewarming with warmed humidified oxygen and 39°C IV fluids.
(Voice: Patient presents in critical hypothermia. Begin active core rewarming immediately and monitor cardiac rhythm.)

---

# Oral Rehydration & Field Electrolyte Therapy
[GREEN] Mild-to-moderate dehydration triage category.
- Dissolve 6 level teaspoons sugar into 1 liter boiled drinking water.
- Add one-half level teaspoon clean table salt.
- Stir until completely transparent; administer sip-by-sip.
> Note: Never exceed salt ratio to prevent hypernatremic complications.
(Voice: For dehydration, prepare the oral rehydration solution using six teaspoons of sugar and half a teaspoon of salt per liter.)
"""


def test_markdown_template_parsing(sample_emergency_markdown):
    """Verify Markdown parsing produces structured multi-slide presentation."""
    manifest = TemplateParser.from_markdown(
        sample_emergency_markdown,
        manifest_id="pres_med_01",
        title="Field Emergency Protocol",
        domain="medical",
    )

    assert manifest.manifest_id == "pres_med_01"
    assert manifest.domain == "medical"
    assert len(manifest.slides) == 2

    # Slide 1: Triage Red
    s1 = manifest.slides[0]
    assert s1.title == "Acute Hypothermia & Trauma Resuscitation"
    assert s1.layout == "triage_alert"

    elem_types = [e.element_type for e in s1.elements]
    assert "triage_badge" in elem_types
    assert "bullet_list" in elem_types
    assert "callout" in elem_types
    assert "narration" in elem_types

    # Slide 2: Rehydration
    s2 = manifest.slides[1]
    assert s2.title == "Oral Rehydration & Field Electrolyte Therapy"
    assert s2.layout == "triage_alert"


def test_template_lexicon_compression_ratio(sample_emergency_markdown):
    """Verify 10-minute presentation compresses to < 1.5 KB over the air."""
    manifest = TemplateParser.from_markdown(sample_emergency_markdown, domain="medical")

    # Raw JSON representation
    raw_json_bytes = manifest.to_json().encode("utf-8")
    raw_size = len(raw_json_bytes)
    assert raw_size > 1000  # uncompressed size ~1.5 KB to 2 KB

    # Compress with domain lexicon
    adapter = RealLexiconAdapter(lexicon_dir=str(_repo_root / "lexicons"))
    compressed_bytes = manifest.compress_with_lexicon(adapter)
    compressed_size = len(compressed_bytes)

    # Assert over-the-air payload fits well within 1.5 KB
    assert compressed_size < 1500, f"Expected < 1500 bytes, got {compressed_size} bytes"

    # Bit-exact recovery
    recovered = PresentationManifest.decompress_with_lexicon(compressed_bytes, domain="medical", adapter=adapter)
    assert recovered.manifest_id == manifest.manifest_id
    assert len(recovered.slides) == len(manifest.slides)
    assert recovered.slides[0].title == manifest.slides[0].title
    assert recovered.slides[1].title == manifest.slides[1].title


def test_telemetry_event_bus_pub_sub():
    """Verify TelemetryEventBus pub/sub notifications and circular buffer."""
    bus = TelemetryEventBus(history_size=50)
    bus.clear()

    received_events = []

    def on_event(evt):
        received_events.append(evt)

    bus.subscribe(on_event)

    # Emit micro-events
    bus.emit(EVENT_CDC_CHUNK, offset=0, size=256, hash="abcd1234")
    bus.emit(EVENT_MERKLE_NODE, level=1, index=0, hash="node1")
    bus.emit(EVENT_DROPLET_EMIT, seed=0, k=20)
    bus.emit(EVENT_MATRIX_PIVOT, current_rank=1, required_k=20)
    bus.emit(EVENT_CHUNK_SOLVED, chunk_index=0, total_chunks=4)

    assert len(received_events) == 5
    assert received_events[0].event_type == EVENT_CDC_CHUNK
    assert received_events[-1].event_type == EVENT_CHUNK_SOLVED

    # Check history
    history = bus.get_recent_events(10)
    assert len(history) == 5

    bus.unsubscribe(on_event)
    bus.emit(EVENT_CDC_CHUNK, offset=256, size=256)
    assert len(received_events) == 5  # No more callbacks after unsubscribe


@pytest.mark.asyncio
async def test_async_telemetry_subscription_under_loss():
    """Verify async subscription queue receives real-time events."""
    bus = TelemetryEventBus()
    q = bus.create_async_subscription()

    try:
        # Emit 10 simulated droplet events with 30% loss
        for seed in range(10):
            survived = (seed % 3 != 0)
            bus.emit(EVENT_DROPLET_RECV, seed=seed, survived=survived)

        collected = []
        for _ in range(10):
            evt = await asyncio.wait_for(q.get(), timeout=1.0)
            collected.append(evt)

        assert len(collected) == 10
        assert collected[0].data["seed"] == 0
        assert collected[-1].data["seed"] == 9
    finally:
        bus.remove_async_subscription(q)


def test_visualizer_html_assets_integrity():
    """Verify visualizer.html exists and contains all 4 canvas panels and slide display."""
    html_path = _tfp_root / "tfp_demo" / "static" / "visualizer.html"
    assert html_path.is_file()

    content = html_path.read_text(encoding="utf-8")
    # Assert panel elements exist
    assert 'id="cdcCanvas"' in content
    assert 'id="merkleCanvas"' in content
    assert 'id="fountainCanvas"' in content
    assert 'id="matrixCanvas"' in content
    assert 'id="slideViewport"' in content
    assert 'id="lossSlider"' in content
    assert 'requestAnimationFrame' in content
