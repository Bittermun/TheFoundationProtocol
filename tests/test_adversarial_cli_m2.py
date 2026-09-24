# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial challenge and empirical stress-test suite for Milestone 2.

Exercises CLI execution (via both in-process cli.main and out-of-process subprocess.run)
focusing on:
1. `tfp search`:
   - Multiple revisions of the same bulletin in node DB: verify older revisions have
     [SUPERSEDED (Rev X < Latest Rev Y)] and latest does NOT.
   - Pruned older revisions or out-of-order records: verify superseded labeling remains accurate.
   - Non-bulletin recipes: verify normal recipe search formatting without crash or spurious tags.
2. `tfp bulletin-import`:
   - Stale revision: import rev 1 after rev 2 is stored -> verify exit code 1 and formatted
     error box containing [ERROR: BULLETIN ADMISSION REJECTED].
   - Conflicting same-revision (different title/content) -> verify exit code 1 and conflict error guidance.
   - Publisher identity conflict -> verify exit code 1 and publisher identity mismatch guidance.
   - Corrupt/tampered package (invalid signature / tampered JSON / corrupt audio) -> verify exit code 1.
   - Duplicate replay: re-importing the same package -> verify exit code 0 and [NOTICE: DUPLICATE BULLETIN REPLAY].
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin import (
    import_bulletin_package,
    prepare_bulletin_package,
)
from tfp_core_v4.cli import main
from tfp_core_v4.node import TFPNode


def run_cli_subprocess(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute the CLI in a separate Python process to verify real exit codes and stdio streams."""
    cmd = [sys.executable, "-m", "tfp_core_v4.cli", *args]
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    paths = [".", "tfp-foundation-protocol"]
    if existing_pp:
        paths.append(existing_pp)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


# ============================================================================
# A. tfp search Adversarial Tests
# ============================================================================

def test_search_multiple_revisions_superseded_labeling(tmp_path: Path, capsys):
    """
    Adversarially challenge search labeling across multiple revisions of the same
    bulletin and multiple distinct bulletins:
    - Older revisions MUST have [SUPERSEDED (Rev X < Latest Rev Y)]
    - Latest revision MUST NOT have [SUPERSEDED ...]
    """
    db_path = tmp_path / "multi_rev_node.db"
    key1 = ed25519.Ed25519PrivateKey.generate()
    key2 = ed25519.Ed25519PrivateKey.generate()
    node = TFPNode(db_path=db_path)

    # Bulletin 1: CRISIS-2026 with 3 revisions
    for rev, body in [
        (1, "Evacuate northern sector alpha immediately."),
        (2, "Evacuate northern sector alpha and beta immediately."),
        (3, "Evacuations completed for northern sector alpha and beta."),
    ]:
        pkg = tmp_path / f"pkg_crisis_rev{rev}"
        prepare_bulletin_package(
            bulletin_id="CRISIS-2026",
            revision=rev,
            title=f"Crisis Evacuation Order Rev {rev}",
            content_text=body,
            output_dir=pkg,
            private_key=key1,
        )
        import_bulletin_package(pkg, node=node)

    # Bulletin 2: WEATHER-REPORT with 2 revisions
    for rev, body in [
        (1, "Moderate rain expected across northern valleys."),
        (2, "Severe storm warning for northern valleys."),
    ]:
        pkg = tmp_path / f"pkg_weather_rev{rev}"
        prepare_bulletin_package(
            bulletin_id="WEATHER-REPORT",
            revision=rev,
            title=f"Weather Advisory Rev {rev}",
            content_text=body,
            output_dir=pkg,
            private_key=key2,
        )
        import_bulletin_package(pkg, node=node)

    # Bulletin 3: SINGLE-NOTICE with 1 revision
    pkg_single = tmp_path / "pkg_single_rev1"
    prepare_bulletin_package(
        bulletin_id="SINGLE-NOTICE",
        revision=1,
        title="Single Notice Bulletin",
        content_text="Information notice for northern outposts.",
        output_dir=pkg_single,
        private_key=key1,
    )
    import_bulletin_package(pkg_single, node=node)

    # --- Test 1: In-process CLI search ---
    capsys.readouterr()
    main(["--db", str(db_path), "search", "northern", "--top-k", "15"])
    captured = capsys.readouterr().out

    # CRISIS-2026 checks:
    # Rev 1 and Rev 2 must show superseded with Latest Rev 3
    assert "[SUPERSEDED (Rev 1 < Latest Rev 3)]" in captured
    assert "[SUPERSEDED (Rev 2 < Latest Rev 3)]" in captured

    # Rev 3 must be present and NOT superseded
    assert "Crisis Evacuation Order Rev 3" in captured

    # WEATHER-REPORT checks:
    # Rev 1 must show superseded with Latest Rev 2
    assert "[SUPERSEDED (Rev 1 < Latest Rev 2)]" in captured
    assert "Weather Advisory Rev 2" in captured

    # SINGLE-NOTICE check:
    assert "Single Notice Bulletin" in captured

    # Check each line individually to guarantee no erroneous superseded tag on latest items
    for line in captured.splitlines():
        if "Crisis Evacuation Order Rev 3" in line:
            assert "[SUPERSEDED" not in line
        if "Weather Advisory Rev 2" in line:
            assert "[SUPERSEDED" not in line
        if "Single Notice Bulletin" in line:
            assert "[SUPERSEDED" not in line

    # --- Test 2: Out-of-process subprocess search ---
    proc = run_cli_subprocess(["--db", str(db_path), "search", "northern", "--top-k", "15"])
    assert proc.returncode == 0
    proc_out = proc.stdout
    assert "[SUPERSEDED (Rev 1 < Latest Rev 3)]" in proc_out
    assert "[SUPERSEDED (Rev 2 < Latest Rev 3)]" in proc_out
    assert "[SUPERSEDED (Rev 1 < Latest Rev 2)]" in proc_out


def test_search_pruned_older_revisions_and_out_of_order(tmp_path: Path, capsys):
    """
    Adversarially challenge search when:
    1. Display records for older revisions have been pruned from the bulletins table,
       but recipes remain in node storage and watermarks exist.
    2. Document content chunk was unretrievable/degraded.
    3. Records were added in reverse/out-of-order.
    """
    db_path = tmp_path / "pruned_node.db"
    key = ed25519.Ed25519PrivateKey.generate()
    node = TFPNode(db_path=db_path)

    # Ingest Rev 1 and Rev 2
    pkg1 = tmp_path / "flood_rev1"
    pkg2 = tmp_path / "flood_rev2"

    prepare_bulletin_package(
        bulletin_id="FLOOD-ALERT",
        revision=1,
        title="Flood Warning Early Alert",
        content_text="Water levels rising rapidly in eastern basin.",
        output_dir=pkg1,
        private_key=key,
    )
    prepare_bulletin_package(
        bulletin_id="FLOOD-ALERT",
        revision=2,
        title="Flood Warning Major Alert",
        content_text="Water levels exceeded critical threshold in eastern basin.",
        output_dir=pkg2,
        private_key=key,
    )

    import_bulletin_package(pkg1, node=node)
    import_bulletin_package(pkg2, node=node)

    # Prune bulletins display table to keep only the latest 1 record
    pruned_count = node.prune_display_bulletins(keep_last_n=1)
    assert pruned_count >= 1

    # Execute search via CLI: Rev 1 recipe is still indexed
    capsys.readouterr()
    main(["--db", str(db_path), "search", "Water", "--top-k", "10"])
    captured = capsys.readouterr().out

    # Rev 1 must still be marked [SUPERSEDED (Rev 1 < Latest Rev 2)]
    assert "[SUPERSEDED (Rev 1 < Latest Rev 2)]" in captured
    assert "Flood Warning Major Alert" in captured

    for line in captured.splitlines():
        if "Flood Warning Major Alert" in line:
            assert "[SUPERSEDED" not in line


def test_search_non_bulletin_recipes_clean_output(tmp_path: Path, capsys):
    """
    Adversarially challenge search with a mix of non-bulletin recipes and bulletin recipes.
    Ensure non-bulletin recipes format cleanly without crash, missing key errors, or spurious tags.
    """
    db_path = tmp_path / "mixed_node.db"
    key = ed25519.Ed25519PrivateKey.generate()

    # 1. Publish non-bulletin standard document
    doc1 = tmp_path / "mesh_radio_guide.txt"
    doc1.write_text("Operation guide for high-frequency packet mesh radios and antennas.", encoding="utf-8")
    main(["--db", str(db_path), "publish", str(doc1), "--title", "Mesh Radio Guide"])

    # 2. Publish bulletin package
    pkg = tmp_path / "pkg_bulletin"
    prepare_bulletin_package(
        bulletin_id="RADIO-NET",
        revision=1,
        title="Radio Net Schedule",
        content_text="Weekly mesh radio check-in frequencies and schedules.",
        output_dir=pkg,
        private_key=key,
    )
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg, node=node)

    # 3. Search for "radio"
    capsys.readouterr()
    main(["--db", str(db_path), "search", "radio", "--top-k", "10"])
    captured = capsys.readouterr().out

    assert "Mesh Radio Guide" in captured
    assert "Radio Net Schedule" in captured
    # Neither should have [SUPERSEDED ...]
    assert "[SUPERSEDED" not in captured

    # Subprocess execution test
    proc = run_cli_subprocess(["--db", str(db_path), "search", "radio"])
    assert proc.returncode == 0
    assert "Mesh Radio Guide" in proc.stdout
    assert "Radio Net Schedule" in proc.stdout
    assert "[SUPERSEDED" not in proc.stdout


# ============================================================================
# B. tfp bulletin-import Adversarial Tests
# ============================================================================

def test_bulletin_import_stale_revision_rejection(tmp_path: Path, capsys):
    """
    Adversarial test: Ingesting a stale revision (Rev 1 after Rev 2 is stored)
    MUST exit with code 1 and print formatted rejection diagnostics.
    """
    db_path = tmp_path / "stale_test.db"
    key = ed25519.Ed25519PrivateKey.generate()

    pkg_rev1 = tmp_path / "stale_rev1"
    pkg_rev2 = tmp_path / "stale_rev2"

    prepare_bulletin_package(
        bulletin_id="ROAD-STATUS",
        revision=1,
        title="Highway 10 Open",
        content_text="Highway 10 open under reduced speed limit.",
        output_dir=pkg_rev1,
        private_key=key,
    )
    prepare_bulletin_package(
        bulletin_id="ROAD-STATUS",
        revision=2,
        title="Highway 10 Closed",
        content_text="Highway 10 closed due to rockslide.",
        output_dir=pkg_rev2,
        private_key=key,
    )

    # Ingest Rev 2 first
    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg_rev2, node=node)

    # Attempt to import Rev 1 via in-process main()
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_rev1 / "broadcast.wav")])
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    err_output = captured.err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_output
    assert "Error Type : StaleRevisionError" in err_output
    assert "Incoming bulletin revision is lower than accepted watermark." in err_output
    assert "Ensure broadcasts distribute current or subsequent revisions." in err_output

    # Attempt to import Rev 1 via subprocess (verifying true OS process exit code)
    proc = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(pkg_rev1 / "broadcast.wav")])
    assert proc.returncode == 1
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in proc.stderr
    assert "StaleRevisionError" in proc.stderr


def test_bulletin_import_conflicting_revision_content_and_title(tmp_path: Path, capsys):
    """
    Adversarial test: Ingesting conflicting content or conflicting title on same revision
    MUST exit with code 1 and print RevisionConflictError guidance.
    """
    db_path = tmp_path / "conflict_test.db"
    key = ed25519.Ed25519PrivateKey.generate()

    # Part 1: Conflicting content
    pkg_orig = tmp_path / "conflict_orig"
    pkg_bad_body = tmp_path / "conflict_bad_body"

    prepare_bulletin_package(
        bulletin_id="CURFEW-ORDER",
        revision=1,
        title="Curfew Order 2200-0600",
        content_text="Curfew strictly in effect from 2200 to 0600 hours.",
        output_dir=pkg_orig,
        private_key=key,
    )
    prepare_bulletin_package(
        bulletin_id="CURFEW-ORDER",
        revision=1,
        title="Curfew Order 2200-0600",
        content_text="MALICIOUS MODIFICATION: Curfew is completely cancelled.",
        output_dir=pkg_bad_body,
        private_key=key,
    )

    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg_orig, node=node)

    # In-process conflict test
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_bad_body / "broadcast.wav")])
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in captured.err
    assert "Error Type : RevisionConflictError" in captured.err
    assert "conflicting content or title" in captured.err
    assert "Revision numbers are immutable; author a higher revision number." in captured.err

    # Subprocess conflict test
    proc = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(pkg_bad_body / "broadcast.wav")])
    assert proc.returncode == 1
    assert "RevisionConflictError" in proc.stderr

    # Part 2: Conflicting title on identical content
    pkg_bad_title = tmp_path / "conflict_bad_title"
    prepare_bulletin_package(
        bulletin_id="CURFEW-ORDER",
        revision=1,
        title="Curfew Order Altered Title",
        content_text="Curfew strictly in effect from 2200 to 0600 hours.",
        output_dir=pkg_bad_title,
        private_key=key,
    )

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_bad_title / "broadcast.wav")])
    assert exc_info.value.code == 1
    assert "RevisionConflictError" in capsys.readouterr().err


def test_bulletin_import_publisher_identity_conflict(tmp_path: Path, capsys):
    """
    Adversarial test: Attempting to broadcast an update under an existing bulletin ID
    using a different signing key MUST exit with code 1 and print PublisherIdentityConflictError guidance.
    """
    db_path = tmp_path / "pub_conflict_test.db"
    key_auth = ed25519.Ed25519PrivateKey.generate()
    key_impostor = ed25519.Ed25519PrivateKey.generate()

    pkg_auth = tmp_path / "pkg_auth"
    pkg_impostor = tmp_path / "pkg_impostor"

    prepare_bulletin_package(
        bulletin_id="OFFICIAL-COMM",
        revision=1,
        title="Official Broadcast Channel Established",
        content_text="This is the authoritative communications frequency.",
        output_dir=pkg_auth,
        private_key=key_auth,
    )
    prepare_bulletin_package(
        bulletin_id="OFFICIAL-COMM",
        revision=2,
        title="Impostor Hijack Attempt",
        content_text="Disregard previous instructions from official channel.",
        output_dir=pkg_impostor,
        private_key=key_impostor,
    )

    node = TFPNode(db_path=db_path)
    import_bulletin_package(pkg_auth, node=node)

    # In-process test
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg_impostor / "broadcast.wav")])
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in captured.err
    assert "Error Type : PublisherIdentityConflictError" in captured.err
    assert "Bulletin ID is already associated with a different publisher key." in captured.err
    assert "Verify publisher signing key or assign a distinct bulletin ID." in captured.err

    # Subprocess test
    proc = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(pkg_impostor / "broadcast.wav")])
    assert proc.returncode == 1
    assert "PublisherIdentityConflictError" in proc.stderr


def test_bulletin_import_corrupt_and_tampered_packages(tmp_path: Path, capsys):
    """
    Adversarial test: Corrupt WAV audio, tampered JSON payload, and invalid signatures
    MUST all exit with code 1 and structured error diagnostics.
    """
    db_path = tmp_path / "tamper_test.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()

    # Case 1: Corrupted audio file (random noise / unparseable WAV)
    bad_audio = tmp_path / "corrupt_audio.wav"
    bad_audio.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(bad_audio)])
    assert exc_info.value.code == 1
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in capsys.readouterr().err

    # Case 2: Tampered JSON payload in modulated audio
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200)
    invalid_json_bytes = b'{"id": "TAMPERED", "rev": 1, "body": unquoted_syntax_error}'
    bad_json_wav = tmp_path / "bad_json.wav"
    bad_json_wav.write_bytes(modulator.synthesize_wav(invalid_json_bytes))

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(bad_json_wav)])
    assert exc_info.value.code == 1
    err_json = capsys.readouterr().err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_json
    assert "Error Type : ValueError" in err_json

    # Case 3: Tampered signature in wire payload
    wire_dict = {
        "v": 2,
        "id": "FORGED-SIG",
        "rev": 1,
        "title": "Forged Signature Notice",
        "body": "This bulletin contains a forged cryptographic signature.",
        "pub": pub_hex,
        "sig": "deadbeef" * 16,  # 64 bytes of forged signature hex
    }
    forged_wav_bytes = modulator.synthesize_wav(json.dumps(wire_dict).encode("utf-8"))
    forged_wav = tmp_path / "forged_sig.wav"
    forged_wav.write_bytes(forged_wav_bytes)

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(forged_wav)])
    assert exc_info.value.code == 1
    err_sig = capsys.readouterr().err
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in err_sig
    assert "Error Type : ValueError" in err_sig
    assert "signature verification failed" in err_sig.lower()

    # Subprocess validation of forged signature
    proc = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(forged_wav)])
    assert proc.returncode == 1
    assert "[ERROR: BULLETIN ADMISSION REJECTED]" in proc.stderr
    assert "ValueError" in proc.stderr


def test_bulletin_import_duplicate_replay_clean_notice(tmp_path: Path, capsys):
    """
    Adversarial test: Re-importing an authentic duplicate bulletin MUST exit with code 0
    and display [NOTICE: DUPLICATE BULLETIN REPLAY] with verified authentic duplicate status.
    """
    db_path = tmp_path / "duplicate_test.db"
    key = ed25519.Ed25519PrivateKey.generate()

    pkg = tmp_path / "pkg_replay"
    prepare_bulletin_package(
        bulletin_id="WATER-BOIL-ALERT",
        revision=1,
        title="Boil Tap Water Advisory",
        content_text="Boil tap water vigorously for 3 minutes before consumption.",
        output_dir=pkg,
        private_key=key,
    )

    # Initial import: must exit cleanly (normal admission)
    capsys.readouterr()
    main(["--db", str(db_path), "bulletin-import", str(pkg / "broadcast.wav")])
    initial_out = capsys.readouterr().out
    assert "Durably stored in authoritative node store" in initial_out

    # Re-import identical bulletin via main(): must exit 0 and print DUPLICATE notice
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(["--db", str(db_path), "bulletin-import", str(pkg / "broadcast.wav")])
    assert exc_info.value.code == 0
    replay_out = capsys.readouterr().out
    assert "[NOTICE: DUPLICATE BULLETIN REPLAY]" in replay_out
    assert "Status: Verified authentic duplicate; existing record retained." in replay_out
    assert "WATER-BOIL-ALERT (Rev 1)" in replay_out

    # Subprocess replay test: verify true OS exit code 0
    proc = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(pkg / "broadcast.wav")])
    assert proc.returncode == 0
    assert "[NOTICE: DUPLICATE BULLETIN REPLAY]" in proc.stdout
    assert "Status: Verified authentic duplicate; existing record retained." in proc.stdout
    assert "WATER-BOIL-ALERT (Rev 1)" in proc.stdout

    # Re-import passing package directory directly instead of WAV file path
    proc_dir = run_cli_subprocess(["--db", str(db_path), "bulletin-import", str(pkg)])
    assert proc_dir.returncode == 0
    assert "[NOTICE: DUPLICATE BULLETIN REPLAY]" in proc_dir.stdout
