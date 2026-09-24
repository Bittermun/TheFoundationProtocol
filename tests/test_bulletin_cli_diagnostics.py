# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive tests for Release Reproducibility & Operator Diagnostics (Milestone 2).

Verifies:
1. CI Asset Path Resolution:
   - Validates resolution of acoustic_receiver.html both within checkout and in isolated directories.
2. Cross-Platform Payload Determinism & Newline Normalization:
   - Inputs with CRLF (\\r\\n) and LF (\\n) produce byte-identical bulletin packages,
     identical SHA3-256 hashes, identical Ed25519 signatures, and exact content_bytes.
3. Superseded Search Labeling:
   - 'tfp search' identifies older bulletin revisions and marks them clearly with
     [SUPERSEDED (Rev X < Latest Rev Y)], while active revisions and generic documents
     remain untagged.
4. User-Facing Rejection Diagnostics:
   - 'tfp bulletin-import' prints formatted terminal diagnostic boxes on StaleRevisionError,
     RevisionConflictError, PublisherIdentityConflictError, and ValueError with exit code 1.
   - Authentic duplicate replays print clean duplicate notices with exit code 0.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

import sys
_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
from test_browser_acoustic_receiver import get_receiver_html_path
from tfp_core_v4.bulletin import (
    import_bulletin_package,
    prepare_bulletin_package,
)
from tfp_core_v4.cli import main
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import get_static_assets_dir


# ============================================================================
# 1. CI Asset Path Resolution Tests
# ============================================================================

def test_ci_asset_path_resolution_checkout():
    """Verify that get_static_assets_dir and get_receiver_html_path locate valid assets in checkout."""
    static_dir = get_static_assets_dir()
    assert static_dir.exists(), f"Static assets directory not found at {static_dir}"
    receiver_file = static_dir / "acoustic_receiver.html"
    assert receiver_file.is_file(), f"acoustic_receiver.html not found in {static_dir}"

    html_path = get_receiver_html_path()
    assert html_path is not None
    assert html_path.is_file()
    assert html_path.name == "acoustic_receiver.html"
    content = html_path.read_text(encoding="utf-8")
    assert "packetCount" in content
    assert "tfp_bulletin_watermarks" in content
    assert "tfp_transmissions" in content


def test_ci_asset_path_resolution_fallback(monkeypatch, tmp_path):
    """Verify that get_receiver_html_path falls back cleanly if get_static_assets_dir fails."""
    # Simulate an environment where get_static_assets_dir raises an error
    def _failing_get_static_assets_dir():
        raise RuntimeError("Simulated missing package resources")

    monkeypatch.setattr(
        "tfp_core_v4.visualizer_server.get_static_assets_dir",
        _failing_get_static_assets_dir,
    )

    resolved = get_receiver_html_path()
    assert resolved is not None
    assert resolved.exists()
    assert resolved.name == "acoustic_receiver.html"


# ============================================================================
# 2. Cross-Platform Payload Determinism & Newline Normalization Tests
# ============================================================================

def test_newline_normalization_determinism_prepare_package(tmp_path: Path):
    """
    Inputs with \\r\\n and \\n must produce byte-identical bulletin packages,
    identical SHA3-256 hashes, identical Ed25519 signatures, and exact content_bytes.
    """
    key = ed25519.Ed25519PrivateKey.generate()

    crlf_content = "URGENT WEATHER ADVISORY\r\nSector 4 Flash Flood Warning.\r\nEvacuate immediately.\r\n"
    lf_content = "URGENT WEATHER ADVISORY\nSector 4 Flash Flood Warning.\nEvacuate immediately.\n"

    pkg_crlf = tmp_path / "pkg_crlf"
    pkg_lf = tmp_path / "pkg_lf"

    meta_crlf = prepare_bulletin_package(
        bulletin_id="FLOOD-2026",
        revision=1,
        title="Flash Flood Warning",
        content_text=crlf_content,
        output_dir=pkg_crlf,
        private_key=key,
    )

    meta_lf = prepare_bulletin_package(
        bulletin_id="FLOOD-2026",
        revision=1,
        title="Flash Flood Warning",
        content_text=lf_content,
        output_dir=pkg_lf,
        private_key=key,
    )

    # 1. Compare in-memory metadata
    assert meta_crlf["content_hash"] == meta_lf["content_hash"]
    assert meta_crlf["content_bytes"] == meta_lf["content_bytes"]
    assert meta_crlf["signature_hex"] == meta_lf["signature_hex"]
    assert meta_crlf["payload_bytes"] == meta_lf["payload_bytes"]

    # 2. Compare on-disk bulletin.txt files
    file_bytes_crlf = (pkg_crlf / "bulletin.txt").read_bytes()
    file_bytes_lf = (pkg_lf / "bulletin.txt").read_bytes()
    assert file_bytes_crlf == file_bytes_lf
    assert b"\r\n" not in file_bytes_crlf
    assert len(file_bytes_crlf) == meta_crlf["content_bytes"]
    assert hashlib.sha3_256(file_bytes_crlf).hexdigest() == meta_crlf["content_hash"]

    # 3. Compare synthesized audio WAV bytes
    wav_bytes_crlf = (pkg_crlf / "broadcast.wav").read_bytes()
    wav_bytes_lf = (pkg_lf / "broadcast.wav").read_bytes()
    assert wav_bytes_crlf == wav_bytes_lf


def test_newline_normalization_cli_prepare_string_and_file(tmp_path: Path):
    """CLI 'bulletin-prepare' must normalize CRLF newlines whether provided via inline string or file."""
    key_hex = ed25519.Ed25519PrivateKey.generate().private_bytes_raw().hex()

    content_text_raw = "MEDICAL DISPATCH\r\nInsulin supplies arriving at Depot 3.\r\n"
    source_file = tmp_path / "crlf_source.txt"
    source_file.write_bytes(content_text_raw.encode("utf-8"))

    pkg_from_file = tmp_path / "cli_pkg_file"
    pkg_from_str = tmp_path / "cli_pkg_str"

    main([
        "bulletin-prepare",
        str(source_file),
        "--id", "MED-03",
        "--revision", "1",
        "--title", "Medical Supply Update",
        "--out-dir", str(pkg_from_file),
        "--key", key_hex,
    ])

    main([
        "bulletin-prepare",
        content_text_raw,
        "--id", "MED-03",
        "--revision", "1",
        "--title", "Medical Supply Update",
        "--out-dir", str(pkg_from_str),
        "--key", key_hex,
    ])

    file_bytes1 = (pkg_from_file / "bulletin.txt").read_bytes()
    file_bytes2 = (pkg_from_str / "bulletin.txt").read_bytes()
    assert file_bytes1 == file_bytes2
    assert b"\r\n" not in file_bytes1
    assert (pkg_from_file / "broadcast.wav").read_bytes() == (pkg_from_str / "broadcast.wav").read_bytes()


def test_newline_normalization_import_package(tmp_path: Path):
    """import_bulletin_package must normalize content and persist bit-exact LF text."""
    key = ed25519.Ed25519PrivateKey.generate()
    pkg_dir = tmp_path / "pkg_nl"
    prepare_bulletin_package(
        bulletin_id="TEST-NL",
        revision=1,
        title="Newline Normalization",
        content_text="Line 1\r\nLine 2\r\n",
        output_dir=pkg_dir,
        private_key=key,
    )

    node = TFPNode(db_path=tmp_path / "node.db")
    imported = import_bulletin_package(pkg_dir, node=node)
    assert imported["bulletin_id"] == "TEST-NL"

    meta, content_bytes = node.get_bulletin("TEST-NL", revision=1)
    assert b"\r\n" not in content_bytes
    assert content_bytes == b"Line 1\nLine 2\n"


# ============================================================================
# 3. Superseded Search Labeling Tests
# ============================================================================

def test_search_superseded_bulletin_labeling(tmp_path: Path, capsys):
    """Older bulletin revisions must be clearly marked [SUPERSEDED (Rev X < Latest Rev Y)]."""
    db_path = tmp_path / "search_node.db"
    key = ed25519.Ed25519PrivateKey.generate()

    # 1. Author and import Revision 1
    pkg1 = tmp_path / "rev1_pkg"
    prepare_bulletin_package(
        bulletin_id="WILDFIRE-2026",
        revision=1,
        title="Wildfire Warning Sector West",
        content_text="Containment at 10%. Evacuate perimeter zone immediately.",
        output_dir=pkg1,
        private_key=key,
    )
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg1, node=node)

    # Search query when only Rev 1 exists
    capsys.readouterr()  # Clear buffers
    main(["--db", str(db_path), "search", "Wildfire"])
    out1 = capsys.readouterr().out
    assert "Wildfire Warning Sector West" in out1
    assert "[SUPERSEDED" not in out1

    # 2. Author and import Revision 2 (superseding Rev 1)
    pkg2 = tmp_path / "rev2_pkg"
    prepare_bulletin_package(
        bulletin_id="WILDFIRE-2026",
        revision=2,
        title="Wildfire Warning Sector West (Update)",
        content_text="Containment increased to 60%. Perimeter evacuation lifted.",
        output_dir=pkg2,
        private_key=key,
    )
    import_bulletin_package(pkg2, node=node)

    # 3. Publish an unrelated non-bulletin document matching query
    doc_path = tmp_path / "fire_safety_manual.txt"
    doc_path.write_text("General Wildfire prevention techniques and defensible space guide.", encoding="utf-8")
    main(["--db", str(db_path), "publish", str(doc_path), "--title", "Wildfire Manual"])

    # Search again
    capsys.readouterr()  # Clear buffers
    main(["--db", str(db_path), "search", "Wildfire", "--top-k", "10"])
    out2 = capsys.readouterr().out

    # Rev 1 must be marked as SUPERSEDED with exact revision numbers
    assert "[SUPERSEDED (Rev 1 < Latest Rev 2)]" in out2

    # Rev 2 must NOT be marked superseded
    assert "Wildfire Warning Sector West (Update)" in out2

    # Generic article must NOT be marked superseded
    assert "Wildfire Manual" in out2
    lines = out2.splitlines()
    for line in lines:
        if "Wildfire Manual" in line:
            assert "[SUPERSEDED" not in line
        if "(Update)" in line:
            assert "[SUPERSEDED" not in line


# ============================================================================
# 4. User-Facing Rejection Diagnostics Tests
# ============================================================================

def test_cli_diagnostics_stale_revision(tmp_path: Path, capsys):
    """Attempting to import a stale bulletin revision via CLI must exit 1 with structured diagnostic block."""
    db_path = tmp_path / "diag_node.db"
    key = ed25519.Ed25519PrivateKey.generate()

    pkg1 = tmp_path / "pkg_stale_1"
    pkg2 = tmp_path / "pkg_stale_2"

    prepare_bulletin_package(
        bulletin_id="CASCADE-ALERT",
        revision=1,
        title="Bridge Inspection (Rev 1)",
        content_text="Bridge passable with caution.",
        output_dir=pkg1,
        private_key=key,
    )
    prepare_bulletin_package(
        bulletin_id="CASCADE-ALERT",
        revision=2,
        title="Bridge Closed (Rev 2)",
        content_text="Bridge impassable due to structural failure.",
        output_dir=pkg2,
        private_key=key,
    )

    # First import Rev 2
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg2, node=node)

    # Attempt to import Rev 1 via CLI: must reject with exit code 1
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg1 / "broadcast.wav")])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    err_text = captured.err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_text
    assert "Error Type : StaleRevisionError" in err_text
    assert "Incoming bulletin revision is lower than accepted watermark" in err_text
    assert "Ensure broadcasts distribute current or subsequent revisions" in err_text


def test_cli_diagnostics_revision_conflict(tmp_path: Path, capsys):
    """Attempting to import a conflicting same-revision bulletin via CLI must exit 1 with diagnostic block."""
    db_path = tmp_path / "diag_node.db"
    key = ed25519.Ed25519PrivateKey.generate()

    pkg_orig = tmp_path / "pkg_orig"
    pkg_conflict = tmp_path / "pkg_conflict"

    prepare_bulletin_package(
        bulletin_id="WATER-NOTICE",
        revision=1,
        title="Water Boil Advisory (Rev 1)",
        content_text="Boil tap water for 3 minutes before drinking.",
        output_dir=pkg_orig,
        private_key=key,
    )
    prepare_bulletin_package(
        bulletin_id="WATER-NOTICE",
        revision=1,
        title="Water Safe to Drink (Rev 1)",  # Conflicting title & body on same revision
        content_text="Water is completely safe to drink without boiling.",
        output_dir=pkg_conflict,
        private_key=key,
    )

    # Import authentic original
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg_orig, node=node)

    # Attempt to import conflicting same-revision bulletin
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_conflict / "broadcast.wav")])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    err_text = captured.err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_text
    assert "Error Type : RevisionConflictError" in err_text
    assert "conflicting content or title" in err_text
    assert "Revision numbers are immutable; author a higher revision number" in err_text


def test_cli_diagnostics_publisher_conflict(tmp_path: Path, capsys):
    """Attempting to re-issue a pinned bulletin ID with a different publisher key must exit 1 with diagnostic block."""
    db_path = tmp_path / "diag_node.db"
    key_legit = ed25519.Ed25519PrivateKey.generate()
    key_impostor = ed25519.Ed25519PrivateKey.generate()

    pkg_legit = tmp_path / "pkg_legit"
    pkg_impostor = tmp_path / "pkg_impostor"

    prepare_bulletin_package(
        bulletin_id="COMMUNITY-SHELTER",
        revision=1,
        title="Shelter Location Alpha",
        content_text="Shelter open at School Gym 1.",
        output_dir=pkg_legit,
        private_key=key_legit,
    )
    prepare_bulletin_package(
        bulletin_id="COMMUNITY-SHELTER",
        revision=2,
        title="Shelter Moved to Beta",
        content_text="Shelter moved to Warehouse 4.",
        output_dir=pkg_impostor,
        private_key=key_impostor,
    )

    # Ingest legitimate bulletin
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg_legit, node=node)

    # Impostor attempts to broadcast correction under same bulletin ID
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_impostor / "broadcast.wav")])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    err_text = captured.err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_text
    assert "Error Type : PublisherIdentityConflictError" in err_text
    assert "different publisher key" in err_text
    assert "Verify publisher signing key or assign a distinct bulletin ID" in err_text


def test_cli_duplicate_replay_clean_notice(tmp_path: Path, capsys):
    """Replaying an authentic duplicate bulletin must print a clean duplicate notice and exit 0."""
    db_path = tmp_path / "diag_node.db"
    key = ed25519.Ed25519PrivateKey.generate()

    pkg = tmp_path / "pkg_replay"
    prepare_bulletin_package(
        bulletin_id="COMMUNITY-UPDATE",
        revision=1,
        title="Food Bank Hours",
        content_text="Food bank open Saturdays 9AM - 1PM.",
        output_dir=pkg,
        private_key=key,
    )

    # First import: fresh admission
    capsys.readouterr()
    main(["--db", str(db_path), "bulletin-import", str(pkg / "broadcast.wav")])
    out1 = capsys.readouterr().out
    assert "Durably stored in authoritative node store" in out1

    # Second import: authentic duplicate replay
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg / "broadcast.wav")])

    assert exc_info.value.code == 0
    out2 = capsys.readouterr().out
    assert "[NOTICE: DUPLICATE BULLETIN REPLAY]" in out2
    assert "Status: Verified authentic duplicate; existing record retained." in out2
    assert "COMMUNITY-UPDATE (Rev 1)" in out2


def test_cli_diagnostics_corrupted_audio(tmp_path: Path, capsys):
    """Corrupted WAV audio must exit 1 with formatted diagnostic error."""
    db_path = tmp_path / "diag_node.db"
    corrupt_wav = tmp_path / "broken.wav"
    corrupt_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(corrupt_wav)])

    assert exc_info.value.code == 1
    err_text = capsys.readouterr().err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_text
    assert "Error Type : ValueError" in err_text
    assert "Action     : Verify audio source quality" in err_text
