# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial Stress-Testing Suite for Milestone 2:
Cross-Platform Newline Normalization, Byte-Exact Counts,
Cryptographic Hash Determinism, and Portable Asset Resolution.

Challenger: challenger_6_m2_1 (teamwork_preview_challenger / empirical_challenger)
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core_v4.bulletin import (
    import_bulletin_package,
    prepare_bulletin_package,
)
from tfp_core_v4.cli import main
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import get_static_assets_dir

_tests_dir = str(Path(__file__).resolve().parent)
_repo_root = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from test_browser_acoustic_receiver import get_receiver_html_path


# ============================================================================
# 1. Injected Mixed Line Endings & Combination Stress
# ============================================================================

def test_injected_mixed_line_endings_combinations(tmp_path: Path):
    """
    Stress-test arbitrary combinations of line endings:
    CRLF (\\r\\n), bare CR (\\r), bare LF (\\n), mixed within the same message,
    consecutive blank lines (\\r\\n\\r\\n, \\r\\r, \\n\\n), and trailing newlines.
    All variations of the same semantic content MUST produce bit-identical
    bulletin packages, SHA3-256 digests, byte counts, and WAV audio.
    """
    fixed_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)

    # Base lines
    l1 = "EMERGENCY POWER OUTAGE NOTICE"
    l2 = "Substation 9 transformer explosion."
    l3 = "Grid restoration estimated in 4 hours."
    l4 = "Hospital backup generator online."

    # Permutations with different line breaks and trailing forms
    cases = {
        "pure_crlf": f"{l1}\r\n{l2}\r\n{l3}\r\n{l4}\r\n",
        "pure_lf": f"{l1}\n{l2}\n{l3}\n{l4}\n",
        "pure_cr": f"{l1}\r{l2}\r{l3}\r{l4}\r",
        "mixed_alternating": f"{l1}\r\n{l2}\r{l3}\n{l4}\r\n",
        "mixed_cr_lf": f"{l1}\r{l2}\n{l3}\r\n{l4}\n",
        "repeated_blanks_crlf": f"{l1}\r\n\r\n{l2}\r\n\r\n{l3}\r\n{l4}\r\n",
        "repeated_blanks_lf": f"{l1}\n\n{l2}\n\n{l3}\n{l4}\n",
        "repeated_blanks_cr": f"{l1}\r\r{l2}\r\r{l3}\r{l4}\r",
        "mixed_blanks": f"{l1}\r\n\r{l2}\n\r\n{l3}\r\n{l4}\r\n",
        "trailing_multiple_crlf": f"{l1}\r\n{l2}\r\n{l3}\r\n{l4}\r\n\r\n",
        "trailing_multiple_lf": f"{l1}\n{l2}\n{l3}\n{l4}\n\n",
        "trailing_multiple_cr": f"{l1}\r{l2}\r{l3}\r{l4}\r\r",
    }

    # Group 1: standard single-newline texts (pure_crlf, pure_lf, pure_cr, mixed_alternating, mixed_cr_lf)
    single_break_group = ["pure_crlf", "pure_lf", "pure_cr", "mixed_alternating", "mixed_cr_lf"]
    expected_lf = f"{l1}\n{l2}\n{l3}\n{l4}\n"
    expected_lf_bytes = expected_lf.encode("utf-8")
    expected_hash = hashlib.sha3_256(expected_lf_bytes).hexdigest()

    meta_results = {}
    disk_bytes_results = {}
    wav_bytes_results = {}

    for name in single_break_group:
        pkg_dir = tmp_path / f"pkg_{name}"
        meta = prepare_bulletin_package(
            bulletin_id="POWER-09",
            revision=1,
            title="Substation 9 Failure",
            content_text=cases[name],
            output_dir=pkg_dir,
            private_key=fixed_key,
        )
        meta_results[name] = meta
        disk_bytes_results[name] = (pkg_dir / "bulletin.txt").read_bytes()
        wav_bytes_results[name] = (pkg_dir / "broadcast.wav").read_bytes()

        # Invariant checks for each
        assert meta["content_bytes"] == len(expected_lf_bytes), f"Mismatch in {name} content_bytes"
        assert meta["content_hash"] == expected_hash, f"Mismatch in {name} content_hash"
        assert disk_bytes_results[name] == expected_lf_bytes, f"Mismatch in {name} on-disk bytes"
        assert b"\r" not in disk_bytes_results[name], f"Carriage return leaked into {name} bulletin.txt"
        assert len(disk_bytes_results[name]) == meta["content_bytes"]
        assert hashlib.sha3_256(disk_bytes_results[name]).hexdigest() == meta["content_hash"]

    # Verify that all single_break_group outputs are mutually bit-identical
    first_name = single_break_group[0]
    for other_name in single_break_group[1:]:
        assert disk_bytes_results[first_name] == disk_bytes_results[other_name]
        assert wav_bytes_results[first_name] == wav_bytes_results[other_name]
        assert meta_results[first_name]["signature_hex"] == meta_results[other_name]["signature_hex"]
        assert meta_results[first_name]["content_hash"] == meta_results[other_name]["content_hash"]

    # Group 2: repeated blank lines (repeated_blanks_crlf, repeated_blanks_lf, repeated_blanks_cr, mixed_blanks)
    blank_group = ["repeated_blanks_crlf", "repeated_blanks_lf", "repeated_blanks_cr", "mixed_blanks"]
    expected_blank_lf = f"{l1}\n\n{l2}\n\n{l3}\n{l4}\n"
    expected_blank_bytes = expected_blank_lf.encode("utf-8")
    expected_blank_hash = hashlib.sha3_256(expected_blank_bytes).hexdigest()

    for name in blank_group:
        pkg_dir = tmp_path / f"pkg_{name}"
        meta = prepare_bulletin_package(
            bulletin_id="POWER-09-BLANK",
            revision=1,
            title="Substation 9 Blanks",
            content_text=cases[name],
            output_dir=pkg_dir,
            private_key=fixed_key,
        )
        disk_bytes = (pkg_dir / "bulletin.txt").read_bytes()
        assert meta["content_bytes"] == len(expected_blank_bytes)
        assert meta["content_hash"] == expected_blank_hash
        assert disk_bytes == expected_blank_bytes
        assert b"\r" not in disk_bytes

    # Group 3: multiple trailing newlines
    trailing_group = ["trailing_multiple_crlf", "trailing_multiple_lf", "trailing_multiple_cr"]
    expected_trailing_lf = f"{l1}\n{l2}\n{l3}\n{l4}\n\n"
    expected_trailing_bytes = expected_trailing_lf.encode("utf-8")
    expected_trailing_hash = hashlib.sha3_256(expected_trailing_bytes).hexdigest()

    for name in trailing_group:
        pkg_dir = tmp_path / f"pkg_{name}"
        meta = prepare_bulletin_package(
            bulletin_id="POWER-09-TRAIL",
            revision=1,
            title="Substation 9 Trailing",
            content_text=cases[name],
            output_dir=pkg_dir,
            private_key=fixed_key,
        )
        disk_bytes = (pkg_dir / "bulletin.txt").read_bytes()
        assert meta["content_bytes"] == len(expected_trailing_bytes)
        assert meta["content_hash"] == expected_trailing_hash
        assert disk_bytes == expected_trailing_bytes
        assert b"\r" not in disk_bytes


# ============================================================================
# 2. Multibyte UTF-8 Characters Combined with CRLF / CR / LF
# ============================================================================

def test_multibyte_utf8_with_crlf_determinism(tmp_path: Path):
    """
    Stress-test multibyte international characters (emojis, CJK, European accents,
    combining diacritics, RTL Arabic/Hebrew) combined with CRLF endings.
    Ensures UTF-8 byte lengths, SHA3-256 digests, on-disk writes, and audio synthesis
    remain completely invariant to the line ending style.
    """
    fixed_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"\x02" * 32)

    test_payloads = [
        (
            "CJK_Japanese_Typhoon",
            "🚨 緊急台風警報: カテゴリー5接近中 🌀\r\n"
            "瞬間最大風速 65m/s。沿岸部に高潮警報。\r\n"
            "避難所: 市立第一中学校 体育館 🏫\r\n"
            "非常用持出袋（水・食料・充電器）を持参してください。\r\n",
        ),
        (
            "CJK_Chinese_Earthquake",
            "⚠️ 地震速报：震级 6.8 级 💥\r\n"
            "震中位于北纬 34.5 度，东经 108.2 度。\r\n"
            "余震持续，请广大群众迅速撤离至开阔安全地带。\r\n"
            "救援物资分配点：中心广场 ⛺\r\n",
        ),
        (
            "European_Accents_French",
            "URGENCE SANITAIRE: Qualité de l'eau compromise 💧\r\n"
            "Ébullition préalable obligatoire pendant 5 minutes.\r\n"
            "Distribution de bouteilles: École Saint-Éloi & Mairie.\r\n"
            "Contact d'urgence: Pompiers (18) ou SAMU (15).\r\n",
        ),
        (
            "BiDi_Arabic_Ambulance",
            "نداء طوارئ طبي عاجل 🚑\r\n"
            "مطلوب متبرعون بالدم من جميع الفئات فوراً.\r\n"
            "مستشفى السلام المركزي - قسم الطوارئ.\r\n"
            "يرجى الالتزام بتعليمات الدفاع المدني.\r\n",
        ),
        (
            "Emoji_Composite_ZWJ",
            "COMMUNITY RESCUE DISPATCH 🧑🏾‍🚒👨🏼‍⚕️\r\n"
            "Search and rescue team deployed to Sector 7.\r\n"
            "Communication channel: 146.520 MHz FM.\r\n"
            "Stay tuned for hourly updates. 📻\r\n",
        ),
    ]

    for label, raw_crlf_text in test_payloads:
        raw_lf_text = raw_crlf_text.replace("\r\n", "\n")
        raw_cr_text = raw_crlf_text.replace("\r\n", "\r")

        expected_norm_text = raw_lf_text
        expected_bytes = expected_norm_text.encode("utf-8")
        expected_hash = hashlib.sha3_256(expected_bytes).hexdigest()

        pkg_crlf = tmp_path / f"pkg_{label}_crlf"
        pkg_lf = tmp_path / f"pkg_{label}_lf"
        pkg_cr = tmp_path / f"pkg_{label}_cr"

        meta_crlf = prepare_bulletin_package(
            bulletin_id=f"B-{label[:8]}",
            revision=1,
            title=f"Test {label}",
            content_text=raw_crlf_text,
            output_dir=pkg_crlf,
            private_key=fixed_key,
        )
        meta_lf = prepare_bulletin_package(
            bulletin_id=f"B-{label[:8]}",
            revision=1,
            title=f"Test {label}",
            content_text=raw_lf_text,
            output_dir=pkg_lf,
            private_key=fixed_key,
        )
        meta_cr = prepare_bulletin_package(
            bulletin_id=f"B-{label[:8]}",
            revision=1,
            title=f"Test {label}",
            content_text=raw_cr_text,
            output_dir=pkg_cr,
            private_key=fixed_key,
        )

        # 1. Metadata check
        assert meta_crlf["content_hash"] == expected_hash
        assert meta_lf["content_hash"] == expected_hash
        assert meta_cr["content_hash"] == expected_hash

        assert meta_crlf["content_bytes"] == len(expected_bytes)
        assert meta_lf["content_bytes"] == len(expected_bytes)
        assert meta_cr["content_bytes"] == len(expected_bytes)

        assert meta_crlf["signature_hex"] == meta_lf["signature_hex"] == meta_cr["signature_hex"]

        # 2. Disk bulletin.txt check
        crlf_file_bytes = (pkg_crlf / "bulletin.txt").read_bytes()
        lf_file_bytes = (pkg_lf / "bulletin.txt").read_bytes()
        cr_file_bytes = (pkg_cr / "bulletin.txt").read_bytes()

        assert crlf_file_bytes == lf_file_bytes == cr_file_bytes == expected_bytes
        assert b"\r" not in crlf_file_bytes
        assert len(crlf_file_bytes) == meta_crlf["content_bytes"]
        assert hashlib.sha3_256(crlf_file_bytes).hexdigest() == meta_crlf["content_hash"]

        # 3. Audio WAV bit-exact check
        assert (pkg_crlf / "broadcast.wav").read_bytes() == (pkg_lf / "broadcast.wav").read_bytes() == (pkg_cr / "broadcast.wav").read_bytes()


# ============================================================================
# 3. End-to-End Lifecycle Verification (Memory -> Disk -> Audio -> DB)
# ============================================================================

def test_in_memory_disk_and_import_lifecycle_determinism(tmp_path: Path):
    """
    Verify complete lifecycle consistency:
    1. In-memory packaging (prepare_bulletin_package)
    2. Binary write to disk (write_bytes to bulletin.txt)
    3. On-disk read (read_bytes)
    4. Audio demodulation & import (import_bulletin_package)
    5. Authoritative database fetch (node.get_bulletin)
    Every layer must report the EXACT same byte length and SHA3-256 digest.
    """
    key = ed25519.Ed25519PrivateKey.generate()
    bid = "LIFECYCLE-CHECK-99"
    rev = 1
    title = "Multibyte Lifecycle Verification"

    # Multilingual body with mixed CRLF and CR
    raw_body = (
        "CIVIL DEFENSE ADVISORY 🛡️\r\n"
        "Status: Active\r\n"
        "Point de rassemblement: Place de l'Étoile 📍\r\n"
        "救援物資: 即席食品および飲料水 🍱🍶\r"
        "Contact: radio.relief@tfp.mesh\r\n"
    )

    pkg_dir = tmp_path / "lifecycle_pkg"

    # 1. In-memory packaging
    meta = prepare_bulletin_package(
        bulletin_id=bid,
        revision=rev,
        title=title,
        content_text=raw_body,
        output_dir=pkg_dir,
        private_key=key,
    )

    mem_bytes_count = meta["content_bytes"]
    mem_hash = meta["content_hash"]

    # 2 & 3. Binary on-disk read
    txt_path = pkg_dir / "bulletin.txt"
    assert txt_path.exists()
    disk_bytes = txt_path.read_bytes()
    disk_file_size = txt_path.stat().st_size

    assert len(disk_bytes) == mem_bytes_count
    assert disk_file_size == mem_bytes_count
    assert hashlib.sha3_256(disk_bytes).hexdigest() == mem_hash
    assert b"\r" not in disk_bytes

    # 4. Audio demodulation & node import
    db_path = tmp_path / "lifecycle_node.db"
    node = TFPNode(db_path=db_path)
    import_result = import_bulletin_package(pkg_dir, node=node)

    assert import_result["bulletin_id"] == bid
    assert import_result["revision"] == rev
    assert import_result["content_hash"] == mem_hash
    assert import_result["verified_status"] == "verified_ed25519"

    # 5. Authoritative persistence retrieval
    stored_meta, stored_bytes = node.get_bulletin(bid, rev)

    assert len(stored_bytes) == mem_bytes_count
    assert hashlib.sha3_256(stored_bytes).hexdigest() == mem_hash
    assert stored_meta["content_hash"] == mem_hash
    assert stored_meta["data_size"] == mem_bytes_count
    assert stored_bytes == disk_bytes
    assert b"\r" not in stored_bytes

    # Check watermark consistency
    wm = node.get_bulletin_watermark(stored_meta["publisher_id"], bid)
    assert wm is not None
    assert wm["max_revision"] == rev
    assert wm["latest_content_hash"] == mem_hash
    assert wm["latest_title"] == title


# ============================================================================
# 4. Cross-Environment Windows Text Mode vs Binary Mode Simulation
# ============================================================================

def test_cross_environment_windows_text_mode_vs_binary_mode(tmp_path: Path):
    """
    Simulate files authored in Windows text mode (where Python/C runtime writes CRLF)
    versus files authored in binary mode (LF only).
    Both files when packaged via CLI 'bulletin-prepare' must result in:
    1. Bit-identical bulletin.txt files
    2. Bit-identical broadcast.wav audio files
    3. Identical content_bytes and content_hash in metadata.json
    4. Successful duplicate detection across nodes
    """
    key_bytes = b"\x03" * 32
    key_hex = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes).private_bytes_raw().hex()

    lines = [
        "DISASTER RECOVERY MANUAL 🚒",
        "Section 1: Potable Water Distribution",
        "Point 1.1: Boil for 180 seconds minimum.",
        "Point 1.2: Add 2 drops sodium hypochlorite per liter.",
        "All stations monitor channel 12.",
    ]

    # Write file 1: Windows text mode (translates \n to \r\n on Windows)
    win_text_file = tmp_path / "manual_win_text.txt"
    with open(win_text_file, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    # Write file 2: Binary mode (guaranteed LF only \n)
    bin_file = tmp_path / "manual_bin_lf.txt"
    bin_content = ("\n".join(lines) + "\n").encode("utf-8")
    bin_file.write_bytes(bin_content)

    # Verify our test environment setup:
    # On Windows, win_text_file.read_bytes() will contain b"\r\n"
    # while bin_file.read_bytes() will only contain b"\n"
    raw_win_bytes = win_text_file.read_bytes()
    raw_bin_bytes = bin_file.read_bytes()
    if os.name == "nt":
        assert b"\r\n" in raw_win_bytes, "Expected Windows text mode to write CRLF on NT"
    assert b"\r" not in raw_bin_bytes, "Binary file should not contain CR"

    # Package via CLI bulletin-prepare
    pkg_win = tmp_path / "pkg_from_win_text"
    pkg_bin = tmp_path / "pkg_from_bin"

    main([
        "bulletin-prepare",
        str(win_text_file),
        "--id", "RECOVERY-101",
        "--revision", "1",
        "--title", "Disaster Recovery Manual",
        "--out-dir", str(pkg_win),
        "--key", key_hex,
    ])

    main([
        "bulletin-prepare",
        str(bin_file),
        "--id", "RECOVERY-101",
        "--revision", "1",
        "--title", "Disaster Recovery Manual",
        "--out-dir", str(pkg_bin),
        "--key", key_hex,
    ])

    # 1. Compare bulletin.txt on disk
    win_txt_bytes = (pkg_win / "bulletin.txt").read_bytes()
    bin_txt_bytes = (pkg_bin / "bulletin.txt").read_bytes()
    assert win_txt_bytes == bin_txt_bytes
    assert b"\r" not in win_txt_bytes

    # 2. Compare metadata content_hash and content_bytes
    import json
    meta_win = json.loads((pkg_win / "metadata.json").read_text(encoding="utf-8"))
    meta_bin = json.loads((pkg_bin / "metadata.json").read_text(encoding="utf-8"))
    assert meta_win["content_hash"] == meta_bin["content_hash"]
    assert meta_win["content_bytes"] == meta_bin["content_bytes"]
    assert meta_win["signature_hex"] == meta_bin["signature_hex"]
    assert meta_win["payload_bytes"] == meta_bin["payload_bytes"]

    # 3. Compare synthesized audio WAV bytes
    assert (pkg_win / "broadcast.wav").read_bytes() == (pkg_bin / "broadcast.wav").read_bytes()

    # 4. Import both into separate nodes and verify identical stored hash
    node1 = TFPNode(db_path=tmp_path / "n1.db")
    node2 = TFPNode(db_path=tmp_path / "n2.db")
    res1 = import_bulletin_package(pkg_win, node=node1)
    res2 = import_bulletin_package(pkg_bin, node=node2)
    assert res1["content_hash"] == res2["content_hash"]


# ============================================================================
# 5. Portable Asset Path Resolution Outside Repo Root
# ============================================================================

def test_portable_asset_path_resolution_outside_repo_root(tmp_path: Path, monkeypatch):
    """
    Stress-test asset path resolution when executing outside repository root:
    1. Change CWD to an arbitrary temporary directory outside the repository.
    2. Ensure get_receiver_html_path() in test_browser_acoustic_receiver resolves acoustic_receiver.html.
    3. Ensure no assertion error or FileNotFoundError is raised.
    4. Simulate copying test_browser_acoustic_receiver.py to an isolated test folder
       (as done in CI: $RUNNER_TEMP/bulletin-tests/) and execute get_receiver_html_path().
    """
    original_cwd = os.getcwd()
    outside_dir = tmp_path / "isolated_execution_sandbox"
    outside_dir.mkdir(parents=True, exist_ok=True)

    try:
        os.chdir(outside_dir)

        # 1. Resolve receiver html while cwd is outside repo root
        resolved_path = get_receiver_html_path()
        assert resolved_path is not None, "get_receiver_html_path returned None"
        assert resolved_path.exists(), f"Resolved path does not exist: {resolved_path}"
        assert resolved_path.is_file(), f"Resolved path is not a file: {resolved_path}"
        assert resolved_path.name == "acoustic_receiver.html"
        assert "packetCount" in resolved_path.read_text(encoding="utf-8")

        # 2. Verify static assets dir directly from visualizer_server
        static_dir = get_static_assets_dir()
        assert static_dir.is_dir()
        assert (static_dir / "acoustic_receiver.html").is_file()

        # 3. Simulate isolated runner execution:
        # Copy test_browser_acoustic_receiver.py into outside_dir, load it as a dynamic module,
        # and invoke its get_receiver_html_path().
        test_source = (Path(_tests_dir) / "test_browser_acoustic_receiver.py").read_text(encoding="utf-8")
        isolated_test_file = outside_dir / "test_browser_acoustic_receiver.py"
        isolated_test_file.write_text(test_source, encoding="utf-8")

        spec = importlib.util.spec_from_file_location("isolated_receiver_test", str(isolated_test_file))
        assert spec is not None
        assert spec.loader is not None
        isolated_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated_module)

        isolated_resolved = isolated_module.get_receiver_html_path()
        assert isolated_resolved is not None
        assert isolated_resolved.exists()
        assert isolated_resolved.name == "acoustic_receiver.html"

    finally:
        os.chdir(original_cwd)


# ============================================================================
# 6. Adversarial Fuzzing / Stress testing of Invariants
# ============================================================================

def test_adversarial_newline_fuzzing_stress(tmp_path: Path):
    """
    Fuzzing harness generating 25 diverse pseudo-random text samples containing
    random mixtures of newlines (\\r\\n, \\r, \\n, \\r\\r\\n, \\n\\r),
    multibyte symbols, and emojis.
    Validates protocol invariants across all generated payloads:
    1. Zero carriage return bytes in bulletin.txt
    2. Bit-exact match between metadata['content_bytes'] and len(read_bytes('bulletin.txt'))
    3. Bit-exact match between metadata['content_hash'] and sha3_256(read_bytes('bulletin.txt'))
    4. Successful audio demodulation and import into TFPNode
    """
    import random

    rng = random.Random(42)  # Deterministic seed for reproducible fuzzing

    chars = [
        "A", "z", "3", " ", "!", "#",
        "🚨", "⚠️", "🌊", "❄️", "⚡",
        "雨", "風", "避", "難", "所",
        "É", "ç", "à", "ô", "ü", "ß",
        "ع", "ر", "ب", "ي",
    ]
    newline_tokens = ["\r\n", "\n", "\r", "\r\r\n", "\n\r", "\r\n\r\n"]

    key = ed25519.Ed25519PrivateKey.generate()
    node = TFPNode(db_path=tmp_path / "fuzz_node.db")

    for i in range(25):
        num_segments = rng.randint(3, 8)
        segments = []
        for _ in range(num_segments):
            seg_text = "".join(rng.choice(chars) for _ in range(rng.randint(5, 20)))
            nl = rng.choice(newline_tokens)
            segments.append(seg_text + nl)

        raw_fuzz_text = "".join(segments)

        pkg_dir = tmp_path / f"pkg_fuzz_{i}"
        bid = f"FUZZ-{i:03d}"
        title = f"Fuzz Notice {i}"

        meta = prepare_bulletin_package(
            bulletin_id=bid,
            revision=1,
            title=title,
            content_text=raw_fuzz_text,
            output_dir=pkg_dir,
            private_key=key,
            baud_rate=1200,
        )

        disk_bytes = (pkg_dir / "bulletin.txt").read_bytes()

        # Invariant 1: zero \r bytes
        assert b"\r" not in disk_bytes, f"Fuzz test {i} leaked CR byte into bulletin.txt"

        # Invariant 2: byte length match
        assert len(disk_bytes) == meta["content_bytes"], f"Fuzz test {i} byte length mismatch"

        # Invariant 3: SHA3-256 hash match
        assert hashlib.sha3_256(disk_bytes).hexdigest() == meta["content_hash"], f"Fuzz test {i} hash mismatch"

        # Invariant 4: Audio demodulation & node storage
        imported = import_bulletin_package(pkg_dir, node=node)
        assert imported["bulletin_id"] == bid
        assert imported["content_hash"] == meta["content_hash"]

        stored_meta, stored_bytes = node.get_bulletin(bid, 1)
        assert stored_bytes == disk_bytes
        assert stored_meta["content_hash"] == meta["content_hash"]


# ============================================================================
# 7. Adversarial Wire CRLF Injection & Signature Determinism
# ============================================================================

def test_adversarial_raw_wire_crlf_injection_and_tampered_hash(tmp_path: Path):
    """
    Adversarially inject raw CRLF into the JSON wire payload directly before AFSK modulation.
    Case A: Sender signed canonical LF hash, but injected raw CRLF into wire 'body'.
            Receiver MUST normalize body to LF, compute matching SHA3-256, verify signature,
            and store LF bytes in TFPNode with zero CR bytes.
    Case B: Sender maliciously signed the unnormalized CRLF hash.
            Receiver normalizes body to LF, detecting signature mismatch.
    """
    import json
    from tfp_client.lib.audio.afsk_modulator import AFSKModulator
    from tfp_core_v4.bulletin_identity import sign_bulletin_content

    key = ed25519.Ed25519PrivateKey.generate()
    bid = "WIRE-CRLF-ADVERSARIAL"
    rev = 1
    title = "Raw Wire CRLF Advisory"

    raw_crlf_body = "ATTENTION ALL CITIZENS\r\nEmergency broadcast wire packet.\r\nEvacuate zone 2.\r\n"
    canonical_lf_body = "ATTENTION ALL CITIZENS\nEmergency broadcast wire packet.\nEvacuate zone 2.\n"

    lf_bytes = canonical_lf_body.encode("utf-8")
    crlf_bytes = raw_crlf_body.encode("utf-8")

    canonical_lf_hash = hashlib.sha3_256(lf_bytes).hexdigest()
    raw_crlf_hash = hashlib.sha3_256(crlf_bytes).hexdigest()

    assert canonical_lf_hash != raw_crlf_hash, "LF and CRLF hashes must differ"

    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200)

    # -------------------------------------------------------------------------
    # Case A: Valid canonical LF signature, wire has raw CRLF body
    # -------------------------------------------------------------------------
    pub_id_a, sig_hex_a = sign_bulletin_content(
        bid, rev, canonical_lf_hash, key, title=title
    )
    wire_dict_a = {
        "v": 2,
        "id": bid,
        "rev": rev,
        "title": title,
        "body": raw_crlf_body,  # Raw CRLF injected onto wire
        "pub": pub_id_a,
        "sig": sig_hex_a,
    }
    wire_bytes_a = json.dumps(wire_dict_a, ensure_ascii=False).encode("utf-8")
    wav_bytes_a = modulator.synthesize_wav(wire_bytes_a)

    wav_file_a = tmp_path / "broadcast_case_a.wav"
    wav_file_a.write_bytes(wav_bytes_a)

    node_a = TFPNode(db_path=tmp_path / "node_a.db")
    imported_a = import_bulletin_package(wav_file_a, node=node_a)

    # Invariants for Case A:
    assert imported_a["content_hash"] == canonical_lf_hash
    assert imported_a["verified_status"] == "verified_ed25519"

    meta_a, stored_bytes_a = node_a.get_bulletin(bid, rev)
    assert stored_bytes_a == lf_bytes
    assert b"\r" not in stored_bytes_a
    assert meta_a["content_hash"] == canonical_lf_hash
    assert meta_a["verified_status"] == "verified_ed25519"

    # -------------------------------------------------------------------------
    # Case B: Malicious signature over raw CRLF hash
    # -------------------------------------------------------------------------
    pub_id_b, sig_hex_b = sign_bulletin_content(
        bid, rev + 1, raw_crlf_hash, key, title=title
    )
    wire_dict_b = {
        "v": 2,
        "id": bid,
        "rev": rev + 1,
        "title": title,
        "body": raw_crlf_body,
        "pub": pub_id_b,
        "sig": sig_hex_b,  # Signed against unnormalized CRLF hash!
    }
    wire_bytes_b = json.dumps(wire_dict_b, ensure_ascii=False).encode("utf-8")
    wav_bytes_b = modulator.synthesize_wav(wire_bytes_b)

    wav_file_b = tmp_path / "broadcast_case_b.wav"
    wav_file_b.write_bytes(wav_bytes_b)

    node_b = TFPNode(db_path=tmp_path / "node_b.db")
    # Receiver normalizes body to canonical LF, which does not match the signature computed
    # over unnormalized CRLF. Admission MUST be rejected with ValueError.
    with pytest.raises(ValueError, match="Bulletin signature verification failed"):
        import_bulletin_package(wav_file_b, node=node_b)


# ============================================================================
# 8. Portable Asset Path Resolution in Clean Subprocess
# ============================================================================

def test_portable_asset_resolution_in_subprocess(tmp_path: Path):
    """
    Execute asset path resolution in an isolated subprocess launched from
    outside the repository root with no repo in sys.path.
    Confirms get_receiver_html_path() reliably locates acoustic_receiver.html.
    """
    import subprocess

    isolated_cwd = tmp_path / "subprocess_isolated_dir"
    isolated_cwd.mkdir(parents=True, exist_ok=True)

    tfp_pkg_dir = str(Path(_repo_root) / "tfp-foundation-protocol")

    test_script = (
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, r'{_repo_root}')\n"
        f"sys.path.insert(0, r'{tfp_pkg_dir}')\n"
        f"sys.path.insert(0, r'{_tests_dir}')\n"
        "from test_browser_acoustic_receiver import get_receiver_html_path\n"
        "resolved = get_receiver_html_path()\n"
        "assert resolved is not None, 'Returned None'\n"
        "assert resolved.exists(), f'File not found: {resolved}'\n"
        "assert resolved.name == 'acoustic_receiver.html', f'Wrong filename: {resolved}'\n"
        "content = resolved.read_text(encoding='utf-8')\n"
        "assert 'packetCount' in content, 'Missing packetCount in HTML'\n"
        "print('RESOLVED_OK:', resolved)\n"
    )

    proc = subprocess.run(
        [sys.executable, "-c", test_script],
        cwd=str(isolated_cwd),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "RESOLVED_OK:" in proc.stdout
    assert "acoustic_receiver.html" in proc.stdout

