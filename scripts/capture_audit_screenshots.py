# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors
"""
Comprehensive Playwright visual audit script.
Captures high-definition screenshot artifacts across all major edutainment states:
1. Grand Scientific Apparatus (Encarta Utopian Scholastic Mode)
2. Architectural X-Ray Blueprint Inspector Mode (Key X)
3. DK Eyewitness Specimen Taxonomy Inspection Modal
4. Live Reconstructed Parametric Anatomical Atlas (98.4% Wire Reduction)
5. Live Reconstructed Scientific Motion Video Player
6. Real-Time Telemetry Event Stream Drawer
"""

import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_core_v4.cli import create_visualizer_server

artifact_dir = Path("C:/Users/msunw/.gemini/antigravity-ide/brain/9439d999-cc0c-40cc-b695-03d8d48e2dce")
artifact_dir.mkdir(parents=True, exist_ok=True)

def run_audit():
    print("Starting visualizer server on ephemeral port...")
    server, port = create_visualizer_server(port=0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.6)

    url = f"http://127.0.0.1:{port}/legacy_visualizer_v1.html"
    print(f"Visualizer server live at: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Wide 1440x900 viewport for museum-quality plate rendering
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.text}"))
        page.on("pageerror", lambda err: print(f"[BROWSER PAGEERROR] {err}"))
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".logo-badge", timeout=5000)

        # Allow canvas animation loop to initialize gears and wavefield
        page.wait_for_timeout(1200)

        # ----------------------------------------------------
        # Audit 1: Grand Scientific Apparatus (Encarta Scholastic Mode)
        # ----------------------------------------------------
        shot1 = artifact_dir / "audit_01_scholastic_apparatus.png"
        page.screenshot(path=str(shot1), full_page=False)
        print(f"[Audit 1/6] Saved Scholastic Apparatus: {shot1.name} ({shot1.stat().st_size} bytes)")

        # ----------------------------------------------------
        # Audit 2: Architectural X-Ray Blueprint Mode (Key X)
        # ----------------------------------------------------
        page.keyboard.press("KeyX")
        page.wait_for_timeout(800)
        shot2 = artifact_dir / "audit_02_xray_blueprint.png"
        page.screenshot(path=str(shot2), full_page=False)
        print(f"[Audit 2/6] Saved X-Ray Blueprint: {shot2.name} ({shot2.stat().st_size} bytes)")

        # Switch back to Scholastic theme
        page.keyboard.press("KeyX")
        page.wait_for_timeout(500)

        # ----------------------------------------------------
        # Audit 3: DK Eyewitness Specimen Taxonomy Modal
        # ----------------------------------------------------
        # Click on Machine A FastCDC gear guillotine zone
        page.locator("#apparatusCanvas").click(position={"x": 100, "y": 120})
        page.wait_for_selector("#specimenModal.show", timeout=3000)
        page.wait_for_timeout(500)
        shot3 = artifact_dir / "audit_03_specimen_inspection_modal.png"
        page.screenshot(path=str(shot3), full_page=False)
        print(f"[Audit 3/6] Saved Specimen Taxonomy Modal: {shot3.name} ({shot3.stat().st_size} bytes)")

        # Close specimen modal
        page.locator(".specimen-close-btn").click()
        page.wait_for_timeout(500)

        # ----------------------------------------------------
        # Audit 4: Live Reconstructed Parametric Anatomical Atlas
        # ----------------------------------------------------
        print("Triggering Parametric Anatomical Atlas transmission over fountain droplets...")
        page.locator("#btnStreamAtlas").click()
        page.wait_for_selector(".atlas-viewport", timeout=12000)
        page.wait_for_timeout(1000)
        # Scroll media card into view
        page.locator("#reconstructedMediaCard").scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        shot4 = artifact_dir / "audit_04_parametric_anatomical_atlas.png"
        page.screenshot(path=str(shot4), full_page=False)
        print(f"[Audit 4/6] Saved Parametric Anatomical Atlas: {shot4.name} ({shot4.stat().st_size} bytes)")

        # ----------------------------------------------------
        # Audit 5: Live Reconstructed Scientific Video Player
        # ----------------------------------------------------
        print("Triggering Scientific Motion Video transmission over fountain droplets...")
        page.locator("#btnStreamVideo").click()
        page.wait_for_selector("#liveVideoPlayer", timeout=12000)
        page.wait_for_timeout(1000)
        page.locator("#reconstructedMediaCard").scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        shot5 = artifact_dir / "audit_05_scientific_video_player.png"
        page.screenshot(path=str(shot5), full_page=False)
        print(f"[Audit 5/6] Saved Scientific Video Player: {shot5.name} ({shot5.stat().st_size} bytes)")

        # ----------------------------------------------------
        # Audit 6: Live Telemetry Event Stream Drawer
        # ----------------------------------------------------
        page.locator("body").scroll_into_view_if_needed()
        page.locator("#btnTelemetryToggle").click()
        page.wait_for_selector("#telemetryDrawer.open", timeout=3000)
        page.wait_for_timeout(600)
        shot6 = artifact_dir / "audit_06_telemetry_event_drawer.png"
        page.screenshot(path=str(shot6), full_page=False)
        print(f"[Audit 6/6] Saved Telemetry Event Drawer: {shot6.name} ({shot6.stat().st_size} bytes)")

        browser.close()

    server.shutdown()
    server.server_close()
    print("All 6 Playwright visual audit screenshots successfully captured!")

if __name__ == "__main__":
    run_audit()
