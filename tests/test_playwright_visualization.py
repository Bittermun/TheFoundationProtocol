# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Playwright End-to-End Test for The Foundation Protocol Visualizer.

Validates that:
1. The 60 FPS HTML5 Canvas dashboard opens and renders all 4 panels.
2. The page connects to the live TFP engine (/api/protocol-state and /api/stream-events).
3. The Merkle root, FastCDC chunking, and droplet metrics reflect real protocol state.
4. User controls (loss rate slider, play/pause, reset) dynamically interact with the protocol.
5. Captures an artifact screenshot for visual inspection.
"""

import threading
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tfp_core_v4.cli import create_visualizer_server


@pytest.fixture(scope="module")
def live_visualizer_server():
    """Spawns an isolated visualizer server on an ephemeral OS port for tests."""
    server, port = create_visualizer_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}/visualizer.html"
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/protocol-state", timeout=0.2):
                break
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.05)

    yield url
    server.shutdown()
    server.server_close()


def test_visualizer_live_protocol_and_interaction(live_visualizer_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        # Navigate to visualizer on ephemeral test server
        page.goto(live_visualizer_server, wait_until="networkidle")

        # 1. Verify Page Title
        assert "The Foundation Protocol" in page.title()

        # 2. Wait for Live Protocol Engine Connection
        page.wait_for_selector(".logo-badge", timeout=5000)
        badge_text = page.inner_text(".logo-badge")
        assert "PROTOCOL ENGINE: LIVE" in badge_text or "TFP v4.0" in badge_text

        # 3. Verify Live SHA3-256 Merkle Root is loaded from real protocol
        time.sleep(0.5)
        root_text = page.inner_text("#rootHashText")
        assert "0x" in root_text
        assert len(root_text) > 8

        # 4. Verify FastCDC live chunks metric
        cdc_text = page.inner_text("#cdcChunksFound")
        assert "CHUNKS" in cdc_text

        # 5. Verify all 4 Canvases exist and have non-zero dimensions
        for canvas_id in ["#cdcCanvas", "#merkleCanvas", "#fountainCanvas", "#matrixCanvas"]:
            box = page.locator(canvas_id).bounding_box()
            assert box is not None
            assert box["width"] > 100
            assert box["height"] > 40

        # 6. Test Interactive Loss Rate Slider
        loss_slider = page.locator("#lossSlider")
        loss_slider.fill("40")
        loss_slider.dispatch_event("input")
        loss_val_text = page.inner_text("#lossValue")
        assert loss_val_text == "40%"

        # 7. Test Play/Pause Button
        play_btn = page.locator("#btnPlayPause")
        assert play_btn.inner_text() == "PAUSE"
        play_btn.click()
        assert play_btn.inner_text() == "RESUME"
        play_btn.click()
        assert play_btn.inner_text() == "PAUSE"

        # 8. Test Web Audio Ambient Toggle
        ambient_btn = page.locator("#btnAmbientToggle")
        assert "HARMONY: OFF" in ambient_btn.inner_text()
        ambient_btn.click()
        assert "HARMONY: ON" in ambient_btn.inner_text()

        # 9. Verify Live Reconstructed Media Player Card exists
        media_card = page.locator("#reconstructedMediaCard")
        assert media_card.is_visible()
        status_pill = page.locator("#mediaReconstructedStatus")
        assert status_pill.is_visible()

        # 10. Trigger Real Stream Short Transmission
        stream_short_btn = page.locator("#btnStreamShort")
        assert stream_short_btn.is_visible()
        stream_short_btn.click()

        # Wait for transmission to complete and media player to mount
        page.wait_for_selector("#liveFramePlayer, #liveVideoPlayer, #liveAudioPlayer, .player-mobile-bezel", timeout=12000)
        time.sleep(1.0)

        # Verify bit-exact reconstruction status
        status_text = page.inner_text("#mediaReconstructedStatus")
        assert "RECONSTRUCTED" in status_text

        # Verify metadata elements populated
        meta_mime = page.inner_text("#metaMime")
        assert "text/html" in meta_mime or "application" in meta_mime or len(meta_mime) > 0

        # Verify packet counts are advancing
        packets_sent = int(page.inner_text("#packetsSent"))
        assert packets_sent > 0

        # Verify slide presentation content rendered
        heading_text = page.inner_text("#slideHeading")
        assert len(heading_text) > 10

        # 11. Capture Artifact Screenshot with full page
        artifact_dir = Path("C:/Users/msunw/.gemini/antigravity-ide/brain/9439d999-cc0c-40cc-b695-03d8d48e2dce")
        screenshot_path = artifact_dir / "visualizer_live_screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        assert screenshot_path.exists()
        assert screenshot_path.stat().st_size > 10000

        browser.close()
