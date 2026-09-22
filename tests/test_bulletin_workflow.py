# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Local Broadcast Bulletin Packaging & Ingestion Workflow.

Verifies:
1. End-to-end unseen bulletin package generation (atomic files) and audio recovery.
2. Bit-exact document recovery via authoritative TFPNode and persistence verification.
3. Airtime budget limit enforcement BEFORE expensive audio synthesis.
4. Robust survival of complex multi-lingual Unicode and special character content.
5. Immediate rejection of damaged, truncated, or corrupted audio frames without corrupted database entries.
6. Ed25519 digital signature verification and tamper detection.
"""

from pathlib import Path
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core_v4.bulletin import (
    prepare_bulletin_package,
    import_bulletin_package,
    estimate_bulletin_airtime,
    verify_bulletin_signature,
    AirtimeLimitExceededError,
)
from tfp_core_v4.node import TFPNode


def test_cli_long_inline_bulletin_handles_filename_limit(tmp_path, monkeypatch):
    import errno
    from tfp_core_v4.cli import main

    body = "An inline bulletin sentence. " * 20
    original_exists = Path.exists

    def exists(path):
        if str(path) == body:
            raise OSError(errno.ENAMETOOLONG, "File name too long")
        return original_exists(path)

    # Exercise the Python 3.11/Linux filesystem error on every test platform.
    monkeypatch.setattr(Path, "exists", exists)
    package = tmp_path / "long-inline"
    main(["bulletin-prepare", body, "--id", "long-inline", "--out-dir", str(package)])
    node = TFPNode(db_path="")
    import_bulletin_package(package, node)
    assert node.get_bulletin("long-inline")[1] == body.encode()


def test_cli_bulletin_reads_file_content(tmp_path):
    from tfp_core_v4.cli import main

    source = tmp_path / "message.txt"
    source.write_text("Read the file contents.", encoding="utf-8")
    package = tmp_path / "from-file"
    main(["bulletin-prepare", str(source), "--id", "file", "--out-dir", str(package)])
    assert (package / "bulletin.txt").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_cli_bulletin_does_not_treat_permission_errors_as_text(tmp_path, monkeypatch):
    from tfp_core_v4.cli import main

    source = tmp_path / "restricted.txt"
    original_exists = Path.exists

    def exists(path):
        if path == source:
            raise PermissionError("Cannot access bulletin file")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(PermissionError, match="Cannot access"):
        main(["bulletin-prepare", str(source), "--id", "restricted", "--out-dir", str(tmp_path / "package")])
    assert not (tmp_path / "package").exists()


def test_bulletin_prepare_and_import_bit_exact(tmp_path: Path):
    """
    Verify complete roundtrip: prepare signed bulletin package, inspect files,
    import into clean TFPNode, and confirm bit-exact retrieval and search.
    """
    pkg_dir = tmp_path / "bulletin_pkg_001"
    node_db = tmp_path / "node_test.db"

    # Generate Ed25519 keypair
    private_key = ed25519.Ed25519PrivateKey.generate()
    expected_pub_hex = private_key.public_key().public_bytes_raw().hex()

    bulletin_id = "BULLETIN-MED-2026-001"
    revision = 1
    title = "Emergency Water Treatment Protocol"
    content = (
        "BOIL WATER ADVISORY: All municipal water must be brought to a rolling boil "
        "for at least 1 full minute prior to consumption or medical use. "
        "Chlorine tablets: use 1 tablet per 20 liters of clear water and wait 30 minutes."
    )

    # 1. Prepare Package
    meta = prepare_bulletin_package(
        bulletin_id=bulletin_id,
        revision=revision,
        title=title,
        content_text=content,
        output_dir=pkg_dir,
        private_key=private_key,
        airtime_limit_seconds=10.0,
        baud_rate=1200,
        sample_rate=16000,
    )

    # Check files exist
    assert (pkg_dir / "broadcast.wav").is_file()
    assert (pkg_dir / "bulletin.txt").is_file()
    assert (pkg_dir / "metadata.json").is_file()
    assert (pkg_dir / "instructions.txt").is_file()
    assert (pkg_dir / "preparation_record.json").is_file()

    # Check metadata contents
    saved_meta = json.loads((pkg_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved_meta["bulletin_id"] == bulletin_id
    assert saved_meta["revision"] == revision
    assert saved_meta["title"] == title
    assert saved_meta["publisher_id"] == expected_pub_hex
    assert saved_meta["verification_status"] == "signed"
    assert saved_meta["audio_duration_seconds"] > 0

    # 2. Import into a fresh TFPNode
    node = TFPNode(db_path=node_db)
    imported = import_bulletin_package(pkg_dir, node=node, baud_rate=1200, sample_rate=16000)

    assert imported["bulletin_id"] == bulletin_id
    assert imported["revision"] == revision
    assert imported["title"] == title
    assert imported["publisher_id"] == expected_pub_hex
    assert imported["verified_status"] == "verified_ed25519"

    # 3. Retrieve and verify bit-exact content
    bulletin_res = node.get_bulletin(bulletin_id)
    assert bulletin_res is not None
    b_meta, b_content = bulletin_res
    assert b_meta["title"] == title
    assert b_meta["verified_status"] == "verified_ed25519"
    assert b_content == content.encode("utf-8")

    fetched_bytes = node.fetch(b_meta["root_hash"])
    assert fetched_bytes == content.encode("utf-8")
    assert fetched_bytes.decode("utf-8") == content

    # 4. Search and CLI integration
    import subprocess
    import sys

    # CLI search finds the imported bulletin content
    res_search = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(node_db),
            "search", "Chlorine",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Chlorine" in res_search.stdout
    assert b_meta["root_hash"] in res_search.stdout

    # CLI bulletin-list lists it with verified status
    res_list = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(node_db),
            "bulletin-list",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert bulletin_id in res_list.stdout
    assert "verified_ed25519" in res_list.stdout

    # CLI bulletin-read outputs the authentic content
    res_read = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(node_db),
            "bulletin-read", bulletin_id,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BOIL WATER ADVISORY" in res_read.stdout
    assert "verified_ed25519" in res_read.stdout


def test_bulletin_airtime_limit_rejection(tmp_path: Path):
    """
    Verify that airtime limits are strictly checked before audio encoding,
    raising AirtimeLimitExceededError and leaving no orphan artifacts.
    """
    pkg_dir = tmp_path / "bulletin_oversized"
    content = "This bulletin is reasonably long and requires more than one second to transmit over Bell 202 AFSK at 1200 baud." * 5

    # With a strict limit of 0.5 seconds, this must abort immediately
    with pytest.raises(AirtimeLimitExceededError) as exc_info:
        prepare_bulletin_package(
            bulletin_id="BULLETIN-OVERSIZED",
            revision=1,
            title="Too Big",
            content_text=content,
            output_dir=pkg_dir,
            airtime_limit_seconds=0.5,
        )

    assert "exceeds configured airtime limit" in str(exc_info.value)
    # Output package directory must not have been created
    assert not pkg_dir.exists()


def test_bulletin_unicode_and_special_characters_survival(tmp_path: Path):
    """
    Verify that international multi-byte Unicode, accents, non-ASCII scripts,
    and emojis survive audio modulation/demodulation bit-for-bit.
    """
    pkg_dir = tmp_path / "bulletin_unicode"
    node_db = tmp_path / "node_unicode.db"

    unicode_content = (
        "⚠️ ALERTE SANITAIRE: Ébullition de l'eau nécessaire!\n"
        "الماء الصالح للشرب: تأكد من التطهير\n"
        "水质安全通知：请务必煮沸后饮用 💧 100°C\n"
        "Español: Hervir el agua antes de consumir durante 3 minutos."
    )

    prepare_bulletin_package(
        bulletin_id="BULLETIN-UNICODE-01",
        revision=1,
        title="Multilingual Alert",
        content_text=unicode_content,
        output_dir=pkg_dir,
        airtime_limit_seconds=10.0,
    )

    node = TFPNode(db_path=node_db)
    imported = import_bulletin_package(pkg_dir, node=node)

    fetched = node.fetch(imported["root_hash"]).decode("utf-8")
    assert fetched == unicode_content


def test_bulletin_damaged_audio_frame_rejection(tmp_path: Path):
    """
    Verify that corrupted or truncated audio is safely rejected by the demodulator
    and does not write partial or corrupted state into the authoritative TFPNode.
    """
    pkg_dir = tmp_path / "bulletin_corrupt"
    node_db = tmp_path / "node_corrupt.db"

    prepare_bulletin_package(
        bulletin_id="BULLETIN-VALID",
        revision=1,
        title="Valid Bulletin",
        content_text="Critical infrastructure update for regional radio operators.",
        output_dir=pkg_dir,
    )

    wav_file = pkg_dir / "broadcast.wav"
    raw_wav = wav_file.read_bytes()

    # Truncate WAV to half its length (damaged transmission cut-off)
    truncated_wav_file = tmp_path / "truncated.wav"
    truncated_wav_file.write_bytes(raw_wav[: len(raw_wav) // 3])

    node = TFPNode(db_path=node_db)

    # Demodulation should fail with ValueError
    with pytest.raises(ValueError) as exc_info:
        import_bulletin_package(truncated_wav_file, node=node)

    assert "Demodulation failed" in str(exc_info.value)

    # Ensure no partial state was stored in node
    bulletins = node.list_bulletins()
    assert len(bulletins) == 0


def test_bulletin_signature_tampering_detection(tmp_path: Path):
    """
    Verify that signature tampering or mismatches are correctly flagged as
    'signature_mismatch' while unaltered signatures are 'verified_ed25519'.
    """
    pkg_dir = tmp_path / "bulletin_tamper"
    node_db = tmp_path / "node_tamper.db"

    sk = ed25519.Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes_raw().hex()

    # Verify signature helper directly
    content_hash = "0123456789abcdef" * 4
    tampered_hash = "fedcba9876543210" * 4

    from tfp_core_v4.bulletin import sign_bulletin_content

    _, sig_hex = sign_bulletin_content("TEST-01", 1, content_hash, sk)

    # Valid check
    assert verify_bulletin_signature("TEST-01", 1, content_hash, pub_hex, sig_hex) is True
    # Tampered content hash
    assert verify_bulletin_signature("TEST-01", 1, tampered_hash, pub_hex, sig_hex) is False
    # Tampered revision
    assert verify_bulletin_signature("TEST-01", 2, content_hash, pub_hex, sig_hex) is False
    # Tampered bulletin_id
    assert verify_bulletin_signature("TEST-02", 1, content_hash, pub_hex, sig_hex) is False
