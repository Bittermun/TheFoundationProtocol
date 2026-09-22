# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Playwright Automated Integration Test for Browser Acoustic Demodulator.

Verifies:
1. Loading the zero-install acoustic receiver interface in headless Chromium.
2. Initial telemetry: 0 packets, 0 valid CRC.
3. Simulation decoupling: Simulation demo button renders explicit amber [SIMULATION DEMO]
   banner and does NOT inflate real CRC or packet counters.
4. Web Audio demodulation: Unseen AFSK WAV audio payload synthesized by
   Python AFSKModulator is decoded by the in-browser JavaScript quadrature demodulator,
   recovering bit-exact content, incrementing real packet & CRC counters, displaying
   CRC VALID and UNSIGNED labels, and persisting to offline localStorage archive.
"""

import base64
import json
from pathlib import Path
import pytest

from tfp_client.lib.audio.afsk_modulator import AFSKModulator

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def test_browser_acoustic_receiver_end_to_end(tmp_path: Path):
    """
    Test real in-browser demodulation and simulation telemetry decoupling in Chromium.
    """
    html_path = Path(__file__).resolve().parent.parent / "tfp-foundation-protocol" / "tfp_demo" / "static" / "acoustic_receiver.html"
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Load receiver interface
        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        # 1. Verify Initial UI State
        assert "Packets: 0 | CRC Valid: 0" in page.locator("#packetCount").inner_text()
        assert "1200 baud text bulletin" in page.locator("#contentArea").inner_text()

        # 2. Verify Simulation Decoupling
        # Click [SIMULATION] Demo Bulletin button
        page.click("#testBtn")
        page.wait_for_timeout(1500)

        # Confirm amber simulation banner is rendered
        assert page.locator(".simulation-banner").is_visible()
        banner_text = page.locator(".simulation-banner").inner_text()
        assert "[SIMULATION DEMO]" in banner_text

        # Real telemetry counters MUST remain at 0 (un-inflated)
        telemetry_text = page.locator("#packetCount").inner_text()
        assert telemetry_text == "Packets: 0 | CRC Valid: 0", f"Simulation inflated telemetry: {telemetry_text}"

        # 3. Real In-Browser Demodulation of Unseen Over-the-Air Payload
        unseen_bulletin = {
            "id": "UNSEEN-EMERGENCY-2026",
            "rev": 1,
            "title": "Hospital Diesel Generator Restoration",
            "body": "Power grid restored in Sector B. Pediatric oxygen concentrators operational.",
        }
        wire_payload = json.dumps(unseen_bulletin).encode("utf-8")

        # Synthesize standard Bell 202 1200-baud AFSK WAV audio
        modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
        wav_bytes = modulator.synthesize_wav(wire_payload)
        b64_audio = base64.b64encode(wav_bytes).decode("ascii")

        # Pass audio into the in-browser decoder
        result = page.evaluate("b64 => window.decodeAcousticWav(b64)", b64_audio)
        assert result["count"] == 1, f"Browser decoder recovered {result['count']} packets (expected 1)"
        decoded_text = result["packets"][0]
        decoded_obj = json.loads(decoded_text)
        assert decoded_obj["id"] == unseen_bulletin["id"]
        assert decoded_obj["body"] == unseen_bulletin["body"]

        # 4. Verify Real Telemetry and UI Updates
        # Real telemetry counters MUST now be incremented
        updated_telemetry = page.locator("#packetCount").inner_text()
        assert "Packets: 1 | CRC Valid: 1" in updated_telemetry

        # Content area must display authentic title and body
        content_text = page.locator("#contentArea").inner_text()
        assert "Hospital Diesel Generator Restoration" in content_text
        assert "Pediatric oxygen concentrators operational." in content_text

        # Authentic badge must be present, and NO simulation banner for authentic transmission
        assert "CRC VALID" in content_text
        assert "UNSIGNED" in content_text
        assert "AUTHENTIC" not in content_text
        # The contentArea should not contain the amber simulation banner for this authentic packet
        assert page.locator("#contentArea .simulation-banner").count() == 0

        # Offline storage archive must record the decoded bulletin
        archive_items = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        titles = [item.get("title") for item in archive_items]
        assert "Hospital Diesel Generator Restoration" in titles

        browser.close()
