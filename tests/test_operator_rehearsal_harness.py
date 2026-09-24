# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Test Suite for Station-to-Listener Operator Rehearsal Harness.

Verifies:
1. Programmatic invocation of rehearse_operator_workflow() returning expected
   metrics dictionary with all 8 operational stages passing.
2. Metrics reporting: timing (duration > 0), airtime footprint (bytes, samples,
   airtime seconds, efficiency > 0), authentic recovery bit-exactness,
   gap detection (Rev 1 -> Rev 3), and replay protection (rejection of Rev 1 & 2).
3. CLI execution via subprocess with --json flag and structured output parsing.
4. CLI execution with standard formatted terminal banner and summary output.
5. Presence and correctness of UI flags in acoustic_receiver.html:
   - superseded notices ([SUPERSEDED] badge and .superseded styling),
   - authenticated Ed25519 signer identity display ([VERIFIED ED25519]),
   - missed broadcast / revision gap warning banner.
6. In-browser Playwright verification of gap warning and superseded badges.
"""

import base64
import json
from pathlib import Path
import subprocess
import sys
import pytest

from scripts.rehearse_operator_workflow import rehearse_operator_workflow
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.visualizer_server import get_static_assets_dir

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def get_receiver_html_path() -> Path:
    try:
        html_path = get_static_assets_dir() / "acoustic_receiver.html"
    except Exception:
        html_path = None
    if not html_path or not html_path.exists():
        html_path = (
            Path(__file__).resolve().parent.parent
            / "tfp-foundation-protocol"
            / "tfp_demo"
            / "static"
            / "acoustic_receiver.html"
        )
    return html_path


def test_rehearsal_workflow_programmatic_execution(tmp_path: Path):
    """
    Test programmatic invocation of rehearse_operator_workflow(), verifying
    that all 8 stages complete with PASS and all required artifacts are written.
    """
    metrics = rehearse_operator_workflow(output_dir=tmp_path, seed=42, verbose=False)

    assert metrics["success"] is True
    assert len(metrics["stages"]) == 8

    expected_stages = [
        "Notice Authoring",
        "Ed25519 Signing",
        "Acoustic Modulation",
        "Audio Transmission",
        "Receiver Capture & Ingestion",
        "Simulated Missed Broadcast",
        "Correction Distribution & Revision Gap Detection",
        "Replay Rejection Validation",
    ]

    for idx, (stage_entry, expected_name) in enumerate(zip(metrics["stages"], expected_stages, strict=True), start=1):
        assert stage_entry["stage"] == idx
        assert stage_entry["name"] == expected_name
        assert stage_entry["status"] == "PASS"
        assert stage_entry["duration_seconds"] >= 0.0

    # Verify atomic artifacts generated in output directory
    assert (tmp_path / "broadcast_rev1.wav").is_file()
    assert (tmp_path / "received_rev1.wav").is_file()
    assert (tmp_path / "broadcast_rev2.wav").is_file()
    assert (tmp_path / "received_rev2.wav").is_file()
    assert (tmp_path / "broadcast_rev3.wav").is_file()
    assert (tmp_path / "received_rev3.wav").is_file()
    assert (tmp_path / "rehearsal_metrics.json").is_file()
    assert (tmp_path / "isolated_listener.db").is_file()


def test_rehearsal_metrics_and_airtime_footprint(tmp_path: Path):
    """
    Verify operator metrics: timing, airtime footprint (bytes, samples, duration, efficiency).
    """
    metrics = rehearse_operator_workflow(output_dir=tmp_path, seed=123, verbose=False)

    # Timing metrics
    timing = metrics["timing"]
    assert timing["total_duration_seconds"] > 0.0
    for stage_idx in range(1, 9):
        assert f"stage_{stage_idx}_duration_seconds" in timing
        assert timing[f"stage_{stage_idx}_duration_seconds"] >= 0.0

    # Airtime footprint metrics
    footprint = metrics["airtime_footprint"]
    assert footprint["total_wire_bytes"] > 0
    assert footprint["total_payload_bytes"] > 0
    assert footprint["total_audio_samples"] > 0
    assert footprint["total_audio_duration_seconds"] > 0.0
    assert footprint["transmission_efficiency_bytes_per_sec"] > 0.0

    # 3 broadcasts (rev 1, rev 2, rev 3)
    per_bc = footprint["per_broadcast"]
    assert len(per_bc) == 3
    assert per_bc[0]["revision"] == 1
    assert per_bc[1]["revision"] == 2
    assert per_bc[2]["revision"] == 3

    for item in per_bc:
        assert item["wire_bytes"] > 0
        assert item["audio_samples"] > 0
        assert item["audio_duration_seconds"] > 0.0

    # Top-level convenience accessors
    assert metrics["total_duration_seconds"] > 0.0
    assert metrics["airtime_duration_seconds"] > 0.0
    assert metrics["total_wire_bytes"] == footprint["total_wire_bytes"]
    assert metrics["transmission_efficiency"] == footprint["transmission_efficiency_bytes_per_sec"]


def test_rehearsal_recovery_and_gap_detection(tmp_path: Path):
    """
    Verify bit-exact authentic notice recovery, Ed25519 signature verification,
    and revision gap detection (Rev 1 -> Rev 3).
    """
    metrics = rehearse_operator_workflow(output_dir=tmp_path, seed=42, verbose=False)

    # Recovery verification
    rec = metrics["recovery_verification"]
    assert rec["bit_exact"] is True
    assert rec["recovered_revision"] == 3
    assert rec["recovered_bulletin_id"] == "NOTICE-WILDFIRE-2026"
    assert "WILDFIRE FINAL CLEARANCE" in rec["recovered_title"]
    assert "FINAL ALL-CLEAR" in rec["recovered_body"]
    assert rec["verified_ed25519"] is True
    assert rec["node_watermark"] == 3
    assert len(rec["publisher_id"]) == 64

    # Revision gap detection
    gap = metrics["gap_detection"]
    assert gap["gap_detected"] is True
    assert gap["previous_watermark"] == 1
    assert gap["incoming_revision"] == 3
    assert gap["missed_revisions"] == [2]
    assert "[MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 3)]" == gap["warning_message"]

    assert metrics["gap_detected"] is True
    assert metrics["recovery_verified"] is True
    assert metrics["latest_watermark"] == 3


def test_rehearsal_replay_protection_validation(tmp_path: Path):
    """
    Verify that replaying older revisions (Rev 1 and missed Rev 2) is strictly
    rejected with StaleRevisionError, and the node watermark remains at 3.
    """
    metrics = rehearse_operator_workflow(output_dir=tmp_path, seed=42, verbose=False)

    replay = metrics["replay_protection"]
    assert replay["replay_protection_confirmed"] is True
    assert replay["rev_1_rejected_stale"] is True
    assert replay["rev_2_rejected_stale"] is True
    assert replay["watermark_preserved"] == 3

    assert metrics["replay_protection_confirmed"] is True


def test_rehearsal_cli_json_subprocess(tmp_path: Path):
    """
    Verify CLI execution with --json produces valid parseable JSON output.
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "rehearse_operator_workflow.py"
    proc = subprocess.run(
        [sys.executable, str(script_path), "--json", "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"CLI failed with stderr:\n{proc.stderr}"

    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert data["total_duration_seconds"] > 0
    assert data["gap_detected"] is True
    assert data["replay_protection_confirmed"] is True
    assert data["recovery_verified"] is True
    assert data["latest_watermark"] == 3
    assert len(data["stages"]) == 8


def test_rehearsal_cli_text_output(tmp_path: Path):
    """
    Verify CLI execution without --json outputs human-readable banner,
    stage progression, and summary metrics.
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "rehearse_operator_workflow.py"
    proc = subprocess.run(
        [sys.executable, str(script_path), "--output-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"CLI failed with stderr:\n{proc.stderr}"
    out = proc.stdout

    assert "OPERATOR WORKFLOW REHEARSAL HARNESS" in out
    assert "[STAGE 1: NOTICE AUTHORING]" in out
    assert "[STAGE 2: ED25519 SIGNING]" in out
    assert "[STAGE 3: ACOUSTIC MODULATION]" in out
    assert "[STAGE 4: AUDIO TRANSMISSION]" in out
    assert "[STAGE 5: RECEIVER CAPTURE & INGESTION]" in out
    assert "[STAGE 6: SIMULATED MISSED BROADCAST]" in out
    assert "[STAGE 7: CORRECTION DISTRIBUTION & REVISION GAP DETECTION]" in out
    assert "[STAGE 8: REPLAY REJECTION VALIDATION]" in out
    assert "REHEARSAL SUMMARY METRICS" in out
    assert "RESULT: SUCCESS" in out


def test_acoustic_receiver_html_contains_required_ui_flags():
    """
    Verify that acoustic_receiver.html contains required UI flags:
    - [SUPERSEDED] badge and .superseded class styling
    - [VERIFIED ED25519] badge and authenticated signer display
    - [MISSED BROADCAST WARNING: Revision gap detected] alert banner
    - Received timestamp display
    """
    html_path = get_receiver_html_path()
    assert html_path.is_file(), f"Receiver HTML not found at {html_path}"

    content = html_path.read_text(encoding="utf-8")

    # 1. Superseded indicators
    assert "[SUPERSEDED]" in content
    assert "superseded" in content
    assert "superseded-badge" in content

    # 2. Authenticated Ed25519 signer identity display
    assert "[VERIFIED ED25519]" in content
    assert "Authenticated Ed25519 Signer Identity" in content
    assert "key-fingerprint" in content

    # 3. Missed broadcast / revision gap warning
    assert "[MISSED BROADCAST WARNING: Revision gap detected" in content
    assert "gap-warning-banner" in content

    # 4. Received timestamp
    assert "rx-timestamp" in content


@pytest.mark.playwright
def test_browser_acoustic_receiver_gap_and_superseded_ui(tmp_path: Path):
    """
    In-browser Playwright test:
    1. Ingest Rev 1 of a bulletin into the browser receiver.
    2. Ingest Rev 3 directly (simulating missed Rev 2).
    3. Verify that the UI displays the [MISSED BROADCAST WARNING] alert banner.
    4. Verify that Rev 1 in the archive feed is marked with the .superseded class and [SUPERSEDED] badge.
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    html_path = get_receiver_html_path()
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"

    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        # 1. Transmit Rev 1
        b1 = {
            "id": "WILDFIRE-GAP-TEST",
            "rev": 1,
            "pub": "station-alpha-001",
            "title": "Evacuation Warning (Rev 1)",
            "body": "Prepare for evacuation in Zone 1.",
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1

        # Confirm Rev 1 displayed
        assert "Evacuation Warning (Rev 1)" in page.locator("#contentArea").inner_text()
        assert "Prepare for evacuation in Zone 1." in page.locator("#contentArea").inner_text()
        assert page.locator("#contentArea .gap-warning-banner").count() == 0

        # 2. Transmit Rev 3 (skipping Rev 2 to trigger revision gap)
        b3 = {
            "id": "WILDFIRE-GAP-TEST",
            "rev": 3,
            "pub": "station-alpha-001",
            "title": "Final All-Clear (Rev 3)",
            "body": "Fire contained. Safe to return to Zone 1.",
        }
        wav3 = modulator.synthesize_wav(json.dumps(b3).encode("utf-8"))
        res3 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav3).decode("ascii"))
        assert res3["count"] == 1

        # 3. Verify Missed Broadcast Warning Alert Banner in active contentArea
        content_text = page.locator("#contentArea").inner_text()
        assert "MISSED BROADCAST WARNING" in content_text
        assert "Revision gap detected (jumped from Rev 1 to Rev 3)" in content_text
        assert page.locator("#contentArea .gap-warning-banner").is_visible()

        # 4. Verify Archive feed contains Rev 1 marked as [SUPERSEDED] with .superseded styling
        assert page.locator("#historyFeed .packet-line.superseded").count() >= 1
        history_text = page.locator("#historyFeed").inner_text()
        assert "[SUPERSEDED]" in history_text
        assert "Evacuation Warning (Rev 1)" in history_text

        # 5. LocalStorage Watermark should be 3
        watermarks = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        wm_key = "station-alpha-001:WILDFIRE-GAP-TEST"
        assert wm_key in watermarks
        assert watermarks[wm_key]["revision"] == 3

        browser.close()
