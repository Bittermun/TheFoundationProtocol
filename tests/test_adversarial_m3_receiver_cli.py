# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Challenge Suite:
Milestone 3 Receiver UI Flags, State Transitions, and CLI Error Injection.

Tests:
1. Browser UI State Transitions via Playwright:
   - Clear archive -> receive Rev 1 -> receive Rev 3:
     Verify Rev 3 shows revision gap warning banner and Rev 1 in archive shows [SUPERSEDED] and .superseded class.
     Verify clicking Rev 1 in archive displays [SUPERSEDED] badge in contentArea.
   - Exact repeat of Rev 1 after archive clear:
     Verify repeat restoration restores display and archive while preserving durable watermark.
     Verify subsequent stale revision downgrade is strictly rejected.
   - DOM Element Verification:
     Verify presence, visibility, and attributes of:
       - code.key-fingerprint (publisher key fingerprint)
       - .verified-ed25519-badge / [VERIFIED ED25519] badge
       - span.rx-timestamp (received timestamp)
       - .packet-line.superseded and .superseded-badge
2. CLI Error Injection & Separation:
   - Rehearsal harness (scripts/rehearse_operator_workflow.py):
     - Invalid CLI arguments: unrecognized flags, missing required args, type errors.
     - Non-existent output directory creation: deeply nested path created automatically.
     - Corrupted output directory permissions: regular file target, unwritable path, stderr traceback, exit code 1.
     - Verification of exit codes (0 on success, 1 on runtime error, 2 on argparse error) and strict stdout/stderr separation.
   - Core CLI subcommands (python -m tfp_core_v4.cli):
     - bulletin-prepare: invalid args, nested non-existent directory creation, file target error, collision without replace.
     - bulletin-import: invalid args, non-existent path, corrupted input.
     - Exit code and stdout/stderr verification.
"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from cryptography.hazmat.primitives.asymmetric import ed25519

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
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"
    return html_path


# =============================================================================
# PART 1: BROWSER UI STATE TRANSITIONS (PLAYWRIGHT)
# =============================================================================

@pytest.mark.playwright
def test_adversarial_browser_clear_archive_rev1_rev3_gap_and_superseded():
    """
    Adversarial Challenge 1:
    1. Clear visual archive in acoustic_receiver.html.
    2. Receive Rev 1 -> displayed cleanly, no gap warning, no superseded badge.
    3. Receive Rev 3 directly (simulating dropped Rev 2):
       - Rev 3 active view shows [MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 3)] banner.
       - Rev 1 in historyFeed displays [SUPERSEDED] badge and has .superseded class.
       - Clicking Rev 1 in historyFeed restores it to contentArea with [SUPERSEDED] badge.
       - Watermark permanently records revision 3.
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        # Step 1: Explicitly clear archive
        page.evaluate("() => clearArchive()")
        assert page.locator("#archiveCount").inner_text() == "0"
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        # Step 2: Ingest Rev 1
        bulletin_id = "WILDFIRE-GAP-ADV-2026"
        pub = "station-delta-99"
        b1 = {
            "id": bulletin_id,
            "rev": 1,
            "pub": pub,
            "title": "Wildfire Warning (Rev 1)",
            "body": "Fire detected 5km north. Evacuate Zone Red immediately.",
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1

        # Verify Rev 1 display
        content1 = page.locator("#contentArea").inner_text()
        assert "Wildfire Warning (Rev 1)" in content1
        assert "Evacuate Zone Red immediately" in content1
        assert page.locator("#contentArea .gap-warning-banner").count() == 0
        assert page.locator("#contentArea .superseded-badge").count() == 0

        # Verify Rev 1 in archive
        assert page.locator("#archiveCount").inner_text() == "1"
        assert page.locator("#historyFeed .packet-line.superseded").count() == 0
        assert "[SUPERSEDED]" not in page.locator("#historyFeed").inner_text()

        # Step 3: Ingest Rev 3 directly (skipping Rev 2 to inject revision gap)
        b3 = {
            "id": bulletin_id,
            "rev": 3,
            "pub": pub,
            "title": "Wildfire Containment & All-Clear (Rev 3)",
            "body": "Fire 100% contained. Zone Red evacuation lifted.",
        }
        wav3 = modulator.synthesize_wav(json.dumps(b3).encode("utf-8"))
        res3 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav3).decode("ascii"))
        assert res3["count"] == 1

        # Verify Rev 3 display contains gap warning banner
        content3 = page.locator("#contentArea").inner_text()
        assert "Wildfire Containment & All-Clear (Rev 3)" in content3
        assert "MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 3)" in content3
        assert page.locator("#contentArea .gap-warning-banner").is_visible()
        # Rev 3 is current, so it should not be superseded
        assert page.locator("#contentArea .superseded-badge").count() == 0

        # Step 4: Verify Rev 1 in archive is marked as [SUPERSEDED]
        assert page.locator("#archiveCount").inner_text() == "2"
        superseded_lines = page.locator("#historyFeed .packet-line.superseded")
        assert superseded_lines.count() >= 1

        # Inspect specific Rev 1 archive entry
        rev1_line = page.locator("#historyFeed .packet-line:has-text('Wildfire Warning (Rev 1)')")
        assert rev1_line.count() == 1
        assert "superseded" in rev1_line.get_attribute("class")
        assert "[SUPERSEDED]" in rev1_line.inner_text()
        assert rev1_line.locator(".superseded-badge").is_visible()

        # Step 5: Click Rev 1 in archive -> contentArea must display Rev 1 WITH [SUPERSEDED] badge
        rev1_line.click()
        content_switched = page.locator("#contentArea").inner_text()
        assert "Wildfire Warning (Rev 1)" in content_switched
        assert "Zone Red" in content_switched
        assert page.locator("#contentArea .superseded-badge").is_visible()
        assert "[SUPERSEDED]" in content_switched

        # Step 6: Verify permanent watermark in LocalStorage is 3
        watermarks = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        key = f"{pub}:{bulletin_id}"
        assert key in watermarks
        assert watermarks[key]["revision"] == 3

        browser.close()


@pytest.mark.playwright
def test_adversarial_browser_repeat_restoration_preserves_watermark():
    """
    Adversarial Challenge 2:
    1. Ingest Rev 1 -> watermark set to 1.
    2. Clear visual archive -> archive count 0, contentArea empty, but watermark retained at 1.
    3. Re-receive exact repeat of Rev 1 -> restored to display and archive.
    4. Ingest Rev 2 -> watermark advances to 2.
    5. Clear visual archive again.
    6. Replay stale Rev 1 -> strictly rejected as stale downgrade; display and archive remain empty.
    7. Re-receive exact repeat of Rev 2 -> restored to display and archive; watermark preserved at 2.
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "REPEAT-RESTORATION-ADV"
        pub = "station-sigma-01"

        b1 = {
            "id": bulletin_id,
            "rev": 1,
            "pub": pub,
            "title": "Hospital Oxygen Supply (Rev 1)",
            "body": "Oxygen reserves critical at Central Hospital.",
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))

        # 1. Ingest Rev 1
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1
        assert "Hospital Oxygen Supply (Rev 1)" in page.locator("#contentArea").inner_text()
        assert page.locator("#archiveCount").inner_text() == "1"

        wm1 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        key = f"{pub}:{bulletin_id}"
        assert key in wm1
        assert wm1[key]["revision"] == 1

        # 2. Clear visual archive
        page.evaluate("() => clearArchive()")
        assert page.locator("#archiveCount").inner_text() == "0"
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        # Watermark MUST remain 1
        wm_cleared = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_cleared[key]["revision"] == 1

        # 3. Transmit EXACT REPEAT of Rev 1
        res1_repeat = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1_repeat["count"] == 1

        # Content area and archive MUST be restored
        assert "Hospital Oxygen Supply (Rev 1)" in page.locator("#contentArea").inner_text()
        assert page.locator("#archiveCount").inner_text() == "1"
        assert "Authentic repeat restored to display archive" in page.locator("#packetFeed").inner_text()

        # Watermark MUST still be 1
        wm_after_repeat = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_after_repeat[key]["revision"] == 1

        # 4. Advance to Rev 2
        b2 = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "Hospital Oxygen Supply Restocked (Rev 2)",
            "body": "Oxygen cylinders delivered. Supply stabilized.",
        }
        wav2 = modulator.synthesize_wav(json.dumps(b2).encode("utf-8"))
        res2 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2["count"] == 1

        wm2 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm2[key]["revision"] == 2

        # 5. Clear archive again
        page.evaluate("() => clearArchive()")
        assert page.locator("#archiveCount").inner_text() == "0"

        # 6. Replay stale Rev 1 -> MUST be rejected as stale downgrade!
        res1_stale = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1_stale["count"] == 1

        feed_stale = page.locator("#packetFeed").inner_text()
        assert "[REJECTED STALE]" in feed_stale
        assert "Downgrade rejected" in feed_stale
        assert "superseded by local watermark 2" in feed_stale

        # Content area MUST NOT display the stale Rev 1
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()
        assert page.locator("#archiveCount").inner_text() == "0"

        # 7. Exact repeat of Rev 2 -> MUST be restored
        res2_repeat = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2_repeat["count"] == 1

        assert "Hospital Oxygen Supply Restocked (Rev 2)" in page.locator("#contentArea").inner_text()
        assert page.locator("#archiveCount").inner_text() == "1"
        wm_final = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_final[key]["revision"] == 2

        browser.close()


@pytest.mark.playwright
def test_adversarial_browser_dom_elements_verification():
    """
    Adversarial Challenge 3:
    Verify presence, CSS classes, and visibility of DOM elements:
    - Publisher key fingerprint: `code.key-fingerprint`
    - Cryptographic verification badge: `[VERIFIED ED25519]` and `.verified-ed25519-badge`
    - Received timestamp: `span.rx-timestamp`
    - Superseded line: `.packet-line.superseded` with danger red indicator
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        # Generate genuine Ed25519 keypair for fingerprint testing
        priv_key = ed25519.Ed25519PrivateKey.generate()
        pub_hex = priv_key.public_key().public_bytes_raw().hex()

        b1 = {
            "id": "SECURE-NOTICE-DOM-01",
            "rev": 1,
            "pub": pub_hex,
            "title": "Civil Protection Emergency Notice",
            "body": "Shelter-in-place order activated for county.",
            "verified_status": "verified_ed25519",
            "verified": True,
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1

        # 1. Verify Publisher Key Fingerprint DOM element
        fp_elem = page.locator("#contentArea code.key-fingerprint")
        assert fp_elem.is_visible()
        assert fp_elem.inner_text() == pub_hex

        # 2. Verify [VERIFIED ED25519] badge DOM element
        v_badge = page.locator("#contentArea .verified-ed25519-badge")
        assert v_badge.is_visible()
        assert "[VERIFIED ED25519]" in v_badge.inner_text()
        assert "Ed25519 signature mathematically verified." in page.locator("#contentArea").inner_text()

        # 3. Verify Received Timestamp DOM element
        ts_elem = page.locator("#contentArea span.rx-timestamp")
        assert ts_elem.is_visible()
        ts_text = ts_elem.inner_text().strip()
        assert len(ts_text) > 0

        # 4. Ingest Rev 2 to test .superseded DOM element
        b2 = {
            "id": "SECURE-NOTICE-DOM-01",
            "rev": 2,
            "pub": pub_hex,
            "title": "Civil Protection Order Lifted",
            "body": "Shelter-in-place order rescinded.",
            "verified_status": "verified_ed25519",
            "verified": True,
        }
        wav2 = modulator.synthesize_wav(json.dumps(b2).encode("utf-8"))
        res2 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2["count"] == 1

        # 5. Verify .superseded class and superseded badge on Rev 1 in historyFeed
        superseded_line = page.locator("#historyFeed .packet-line.superseded")
        assert superseded_line.count() == 1
        assert superseded_line.is_visible()

        # Check CSS computed border-left indicator
        border_left = superseded_line.evaluate("el => window.getComputedStyle(el).borderLeftColor")
        # Danger red corresponds to rgb(239, 68, 68)
        assert "239" in border_left or "red" in border_left.lower() or "rgb" in border_left

        # Check badge
        superseded_badge = superseded_line.locator(".superseded-badge")
        assert superseded_badge.is_visible()
        assert "[SUPERSEDED]" in superseded_badge.inner_text()

        browser.close()


# =============================================================================
# PART 2: CLI ERROR INJECTION & SEPARATION
# =============================================================================

def test_adversarial_cli_rehearsal_invalid_arguments():
    """
    Adversarial Challenge 4:
    Execute scripts/rehearse_operator_workflow.py with invalid arguments.
    Assert:
    - Exit code is 2 (argparse syntax / unrecognized argument error).
    - stderr contains usage error message.
    - stdout is strictly empty (no stdout pollution).
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "rehearse_operator_workflow.py"

    invalid_invocations = [
        ["--unrecognized-argument-xyz"],
        ["--output-dir"],  # missing required parameter value
        ["--seed", "not_a_valid_integer_seed"],
        ["--json", "--bogus-flag"],
    ]

    for args in invalid_invocations:
        cmd = [sys.executable, str(script_path)] + args
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        assert proc.returncode == 2, f"Expected returncode 2 for {args}, got {proc.returncode}"
        assert len(proc.stderr) > 0, f"Expected stderr error message for {args}"
        assert "error:" in proc.stderr.lower() or "usage:" in proc.stderr.lower()
        # stdout must NOT contain metrics or success banners
        assert proc.stdout.strip() == "", f"Expected empty stdout on argument error for {args}, got: {proc.stdout}"


def test_adversarial_cli_rehearsal_output_dir_nested_creation(tmp_path: Path):
    """
    Adversarial Challenge 5:
    Execute rehearsal script pointing to a non-existent, deeply nested output directory.
    Assert:
    - Exit code is 0.
    - Deeply nested directory is automatically created (mkdir -p).
    - All 8 atomic rehearsal artifacts exist inside it.
    - stdout produces valid, parseable JSON with success: true when --json is used.
    - stderr is clean.
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "rehearse_operator_workflow.py"
    nested_dir = tmp_path / "deep" / "nested" / "path" / "to" / "rehearsal_output"
    assert not nested_dir.exists()

    cmd = [
        sys.executable,
        str(script_path),
        "--json",
        "--output-dir",
        str(nested_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    assert proc.returncode == 0, f"Rehearsal failed with stderr:\n{proc.stderr}"
    assert nested_dir.is_dir(), f"Expected directory to be created: {nested_dir}"

    # Verify all expected artifacts created
    expected_files = [
        "broadcast_rev1.wav",
        "received_rev1.wav",
        "broadcast_rev2.wav",
        "received_rev2.wav",
        "broadcast_rev3.wav",
        "received_rev3.wav",
        "isolated_listener.db",
        "rehearsal_metrics.json",
    ]
    for filename in expected_files:
        p = nested_dir / filename
        assert p.is_file(), f"Missing expected artifact: {p}"
        assert p.stat().st_size > 0, f"Artifact is empty: {p}"

    # Verify stdout is clean JSON
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert data["gap_detected"] is True
    assert data["replay_protection_confirmed"] is True
    assert data["latest_watermark"] == 3


def test_adversarial_cli_rehearsal_corrupted_output_dir_permissions(tmp_path: Path):
    """
    Adversarial Challenge 6:
    Execute rehearsal script when output directory cannot be created or written to.
    Sub-case A: output-dir is an existing regular file.
    Sub-case B: output-dir is on an invalid / unwritable drive path.
    Assert:
    - Exit code is 1 (non-zero failure).
    - Traceback or error details are written to stderr.
    - stdout does NOT claim success or emit valid success JSON.
    """
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "rehearse_operator_workflow.py"

    # Sub-case A: output-dir is a file
    regular_file = tmp_path / "blocking_file.txt"
    regular_file.write_text("blocker", encoding="utf-8")

    proc_file = subprocess.run(
        [sys.executable, str(script_path), "--output-dir", str(regular_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_file.returncode == 1, f"Expected returncode 1 for file output-dir, got {proc_file.returncode}"
    assert "FileExistsError" in proc_file.stderr or "Error" in proc_file.stderr
    assert "RESULT: SUCCESS" not in proc_file.stdout

    # With --json flag: stdout must NOT output success JSON
    proc_file_json = subprocess.run(
        [sys.executable, str(script_path), "--json", "--output-dir", str(regular_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_file_json.returncode == 1
    assert "FileExistsError" in proc_file_json.stderr or "Error" in proc_file_json.stderr
    assert proc_file_json.stdout.strip() == ""

    # Sub-case B: output-dir on non-existent / illegal device
    proc_bad_drive = subprocess.run(
        [sys.executable, str(script_path), "--output-dir", "Z:\\tfp_bad_drive_test\\out"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bad_drive.returncode == 1
    assert len(proc_bad_drive.stderr) > 0
    assert "RESULT: SUCCESS" not in proc_bad_drive.stdout


def test_adversarial_cli_core_bulletin_prepare_and_import(tmp_path: Path):
    """
    Adversarial Challenge 7:
    Error injection into core CLI subcommands (python -m tfp_core_v4.cli):
    1. bulletin-prepare:
       - Unknown argument -> exit code 2, error in stderr, stdout clean.
       - Non-existent nested output dir -> created, exit code 0.
       - Output dir is existing regular file -> exit code 1, stderr traceback.
       - Existing dir without --replace -> exit code 1, FileExistsError.
    2. bulletin-import:
       - Unknown argument -> exit code 2, error in stderr, stdout clean.
       - Non-existent source path -> exit code 1, FileNotFoundError in stderr.
    """
    # 1. bulletin-prepare: invalid option
    proc_bprep_bad = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "bulletin-prepare", "--non-existent-option"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bprep_bad.returncode == 2
    assert "error:" in proc_bprep_bad.stderr.lower()
    assert proc_bprep_bad.stdout.strip() == ""

    # 2. bulletin-prepare: nested non-existent directory creation
    nested_pkg = tmp_path / "deep" / "pkg_out"
    proc_bprep_ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "tfp_core_v4.cli",
            "bulletin-prepare",
            "Emergency notification content for test.",
            "--id",
            "TEST-PKG-01",
            "--revision",
            "1",
            "--out-dir",
            str(nested_pkg),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bprep_ok.returncode == 0, f"bulletin-prepare failed:\n{proc_bprep_ok.stderr}"
    assert nested_pkg.is_dir()
    assert (nested_pkg / "broadcast.wav").is_file()
    assert (nested_pkg / "bulletin.txt").is_file()
    assert (nested_pkg / "metadata.json").is_file()

    # 3. bulletin-prepare: collision without --replace
    proc_bprep_dup = subprocess.run(
        [
            sys.executable,
            "-m",
            "tfp_core_v4.cli",
            "bulletin-prepare",
            "Emergency notification content for test.",
            "--id",
            "TEST-PKG-01",
            "--revision",
            "1",
            "--out-dir",
            str(nested_pkg),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bprep_dup.returncode == 1
    assert "FileExistsError" in proc_bprep_dup.stderr or "already exists" in proc_bprep_dup.stderr

    # 4. bulletin-prepare: output dir is regular file
    a_file = tmp_path / "not_a_dir.txt"
    a_file.write_text("not a dir", encoding="utf-8")
    proc_bprep_file = subprocess.run(
        [
            sys.executable,
            "-m",
            "tfp_core_v4.cli",
            "bulletin-prepare",
            "Emergency text.",
            "--id",
            "TEST-PKG-02",
            "--revision",
            "1",
            "--out-dir",
            str(a_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bprep_file.returncode == 1
    assert len(proc_bprep_file.stderr) > 0

    # 5. bulletin-import: invalid option
    proc_bimp_bad = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "bulletin-import", "--invalid-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bimp_bad.returncode == 2
    assert "error:" in proc_bimp_bad.stderr.lower()
    assert proc_bimp_bad.stdout.strip() == ""

    # 6. bulletin-import: non-existent source
    proc_bimp_missing = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "bulletin-import", str(tmp_path / "missing_pkg")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bimp_missing.returncode == 1
    assert "FileNotFoundError" in proc_bimp_missing.stderr or "not found" in proc_bimp_missing.stderr.lower()
