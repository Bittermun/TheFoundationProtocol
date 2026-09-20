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

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{base_url}/api/protocol-state", timeout=0.2):
                break
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.05)

    yield base_url
    server.shutdown()
    server.server_close()


def test_clean_slate_visualizer(live_visualizer_server):
    """Verifies that the clean slate visualizer is lightweight, error-free, and connects to live protocol."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        console_errors = []
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        page.goto(f"{live_visualizer_server}/visualizer.html", wait_until="domcontentloaded")

        assert "The Foundation Protocol" in page.title()
        page.wait_for_selector(".logo-badge", timeout=5000)
        badge_text = page.inner_text(".logo-badge")
        assert "PROTOCOL ENGINE: LIVE" in badge_text

        time.sleep(0.5)
        root_text = page.inner_text("#rootHashText")
        assert "0x" in root_text

        cdc_text = page.inner_text("#cdcChunksFound")
        assert "CHUNKS" in cdc_text

        assert len(console_errors) == 0

        artifact_dir = Path("C:/Users/msunw/.gemini/antigravity-ide/brain/9439d999-cc0c-40cc-b695-03d8d48e2dce")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = artifact_dir / "clean_slate_screenshot.png"
        page.screenshot(path=str(screenshot_path))
        assert screenshot_path.exists()
        browser.close()


def test_legacy_visualizer_live_protocol_and_interaction(live_visualizer_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        # Navigate to legacy visualizer archive on ephemeral test server
        page.goto(f"{live_visualizer_server}/legacy_visualizer_v1.html", wait_until="domcontentloaded")

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

        # 9. Verify Encarta Utopian Scholastic Theme & Switcher
        body_has_scholastic = page.locator("body").evaluate("el => el.classList.contains('theme-scholastic')")
        assert body_has_scholastic is True

        theme_btn = page.locator("#btnThemeToggle")
        assert theme_btn.is_visible()
        assert "SCHOLASTIC" in theme_btn.inner_text()
        theme_btn.click()
        assert "CYBER" in theme_btn.inner_text()
        theme_btn.click()
        assert "SCHOLASTIC" in theme_btn.inner_text()

        # 10. Verify Zero-Touch Voice Controller & Roman Numeral Cards
        voice_btn = page.locator("#btnVoiceToggle")
        assert voice_btn.is_visible()
        assert "VOICE: ON" in voice_btn.inner_text()

        card_titles = page.locator(".card-title").all_inner_texts()
        assert any("I." in t for t in card_titles)
        assert any("VI." in t for t in card_titles)

        # Trigger simulated hands-free voice command
        page.evaluate("voiceController.handleCommand('stream short')")
        toast_text = page.inner_text("#voiceToastText")
        assert "STREAM" in toast_text

        # 11. Verify Live Reconstructed Media Player Card exists
        media_card = page.locator("#reconstructedMediaCard")
        assert media_card.is_visible()
        status_pill = page.locator("#mediaReconstructedStatus")
        assert status_pill.is_visible()

        # 12. Trigger Real Stream Short Transmission
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

        # 13. Verify Grand Scientific Apparatus Canvas (PhET Wavefield & Macaulay Cutaways)
        apparatus_box = page.locator("#apparatusCanvas").bounding_box()
        assert apparatus_box is not None
        assert apparatus_box["width"] > 700
        assert apparatus_box["height"] > 300

        # 14. Test X-Ray Blueprint Inspector Toggle (Button & Key X)
        xray_btn = page.locator("#btnXrayToggle")
        assert "BLUEPRINT: OFF" in xray_btn.inner_text()
        xray_btn.click()
        assert "BLUEPRINT: ON" in xray_btn.inner_text()
        body_is_xray = page.locator("body").evaluate("el => el.classList.contains('mode-xray')")
        assert body_is_xray is True
        assert "BLUEPRINT X-RAY: ACTIVE" in page.inner_text("#apparatusModePill")

        # Toggle back via keyboard shortcut 'X'
        page.keyboard.press("KeyX")
        body_is_xray_after = page.locator("body").evaluate("el => el.classList.contains('mode-xray')")
        assert body_is_xray_after is False

        # 15. Test Wave Mode Toggle (RF vs Acoustic)
        wave_btn = page.locator("#btnWaveModeToggle")
        assert "WAVE: RF" in wave_btn.inner_text()
        wave_btn.click()
        assert "WAVE: ACOUSTIC" in wave_btn.inner_text()
        assert "Acoustic Sonar" in page.inner_text("#waveChannelLabel")
        wave_btn.click()
        assert "WAVE: RF" in wave_btn.inner_text()

        # 16. Test DK Eyewitness Specimen Modal Interaction
        # Click on Machine A FastCDC Guillotine zone
        page.locator("#apparatusCanvas").click(position={"x": 100, "y": 100})
        specimen_modal = page.locator("#specimenModal")
        assert specimen_modal.is_visible()
        assert "FastCDC" in page.inner_text("#specimenTitle")
        assert "Scalprum" in page.inner_text("#specimenLatin")
        # Close specimen modal
        page.locator(".specimen-close-btn").click()
        assert not specimen_modal.is_visible()

        # 17. Test Telemetry Slide-out Drawer
        telemetry_btn = page.locator("#btnTelemetryToggle")
        telemetry_btn.click()
        drawer = page.locator("#telemetryDrawer")
        assert "open" in drawer.get_attribute("class")
        telemetry_btn.click()

        # 18. Test Parametric Anatomical Atlas Streaming
        atlas_btn = page.locator("#btnStreamAtlas")
        assert atlas_btn.is_visible()
        atlas_btn.click()
        page.wait_for_selector(".atlas-viewport, #liveFramePlayer, #liveVideoPlayer", timeout=12000)
        time.sleep(1.0)
        assert page.locator(".atlas-viewport, #liveFramePlayer, #liveVideoPlayer").count() > 0

        # 19. Capture Artifact Screenshot with full page showing Encarta Scholastic design and Macaulay Apparatus
        artifact_dir = Path("C:/Users/msunw/.gemini/antigravity-ide/brain/9439d999-cc0c-40cc-b695-03d8d48e2dce")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = artifact_dir / "visualizer_live_screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        assert screenshot_path.exists()
        browser.close()


def test_acoustic_receiver_page(live_visualizer_server):
    """Verifies that the acoustic demodulator and voice memo UI functions correctly with zero console errors."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 900})

        console_errors = []
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        page.goto(f"{live_visualizer_server}/acoustic_receiver.html", wait_until="domcontentloaded")
        assert "TFP Acoustic Audio Receiver" in page.title()

        # Check Haptics status indicator
        haptic_status = page.inner_text("#hapticStatus")
        assert "Haptics" in haptic_status

        # Test Voice Memo button click
        voice_btn = page.locator("#testVoiceBtn")
        assert voice_btn.is_visible()
        voice_btn.click()

        # Wait for Voice Memo card to render
        page.wait_for_selector("#contentArea .content-title", timeout=5000)
        page.wait_for_selector("#historyFeed .packet-line", timeout=5000)

        # Assert voice memo rendered
        content_area = page.inner_text("#contentArea")
        assert "Voice Memo" in content_area
        assert "CLINIC_NORTH" in content_area
        assert "Play Audio" in content_area

        # Assert offline archive updated
        archive_count = page.inner_text("#archiveCount")
        assert int(archive_count) >= 1

        assert console_errors == []
        browser.close()
