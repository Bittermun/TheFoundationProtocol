# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit tests for new TFP v4.0 CLI subcommands: export-zim and voice-memo.
"""

import math
import subprocess
import struct
import sys
import wave
from pathlib import Path

import pytest

from tfp_client.lib.ingest.article_ingester import ArticleIngester
from tfp_client.lib.ingest.article_packager import ArticlePackager


def _create_sine_wav(path: Path, duration_s: float = 1.0, freq: float = 400.0, rate: int = 8000) -> None:
    frames = bytearray()
    n_samples = int(duration_s * rate)
    for i in range(n_samples):
        val = int(8000 * math.sin(2 * math.pi * freq * i / rate))
        frames.extend(struct.pack("<h", val))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


def test_cli_export_zim_from_directory(tmp_path: Path):
    zim_out = tmp_path / "zim_output"
    articles_dir = tmp_path / "articles"
    articles_dir.mkdir()
    # Supply this test's own archive; it must work before any dashboard has run.
    import json
    packager = ArticlePackager()
    for idx in range(3):
        article = ArticleIngester.ingest_markdown(f"# Offline guide {idx}\n\nLocal test article {idx}.")
        bundle = packager.package_article(article)
        (articles_dir / f"{bundle.merkle_root}.json").write_text(
            json.dumps(bundle.to_dict(include_html=True)), encoding="utf-8",
        )

    result = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "export-zim", str(articles_dir), "--out", str(zim_out)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "Kiwix / ZIM Bundle Export Complete" in result.stdout
    assert (zim_out / "index.html").exists()
    assert (zim_out / "manifest.json").exists()
    assert (zim_out / "A").is_dir()
    assert len(list((zim_out / "A").glob("*.html"))) >= 3


def test_cli_voice_memo_lifecycle(tmp_path: Path):
    in_wav = tmp_path / "voice_input.wav"
    out_vm = tmp_path / "voice_compressed.vm"
    decomp_wav = tmp_path / "voice_decompressed.wav"

    _create_sine_wav(in_wav, duration_s=1.5, freq=250.0, rate=8000)
    assert in_wav.stat().st_size > 20000

    # 1. Compress
    comp_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli", "voice-memo", "compress",
            str(in_wav), "--out", str(out_vm), "--callsign", "MEDIC01"
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert comp_res.returncode == 0, comp_res.stderr
    assert "Voice Memo Compressed" in comp_res.stdout
    assert out_vm.exists()
    assert out_vm.stat().st_size < 300  # > 98% compression

    # 2. Info
    info_res = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "voice-memo", "info", str(out_vm)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert info_res.returncode == 0, info_res.stderr
    assert "MEDIC01" in info_res.stdout
    assert "Vocoder Encoded   : True" in info_res.stdout

    # 3. Decompress
    decomp_res = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "voice-memo", "decompress", str(out_vm), "--out", str(decomp_wav)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert decomp_res.returncode == 0, decomp_res.stderr
    assert "Voice Memo Decompressed" in decomp_res.stdout
    assert decomp_wav.exists()
    assert decomp_wav.stat().st_size > 20000


def test_cli_voice_memo_missing_file():
    result = subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "voice-memo", "info", "non_existent_file.vm"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower()


def test_cli_publish_inspect_fetch_roundtrip(tmp_path: Path):
    """Verify publish -> process exit -> inspect -> process exit -> fetch cross-process journey."""
    db_file = tmp_path / "node_storage.db"
    sample_file = tmp_path / "payload.txt"
    sample_text = "TFP v4.0 Cross-Process Persistence & Retrieval Test Payload"
    sample_file.write_text(sample_text, encoding="utf-8")

    # 1. Publish in Subprocess A
    pub_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "publish", str(sample_file),
            "--title", "TestPayload"
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "File Published & Persisted Successfully" in pub_res.stdout
    assert db_file.exists()

    root_hash = None
    for line in pub_res.stdout.splitlines():
        if "Root Hash" in line:
            root_hash = line.split(":")[-1].strip()
            break
    assert root_hash is not None

    # 2. Inspect in Subprocess B (fresh process context)
    insp_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "inspect", root_hash
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    import json
    recipe_info = json.loads(insp_res.stdout)
    assert recipe_info["root_hash"] == root_hash
    assert recipe_info["total_size_bytes"] == len(sample_text.encode("utf-8"))

    # 3. Fetch in Subprocess C (fresh process context)
    out_file = tmp_path / "fetched.txt"
    fetch_res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "--db", str(db_file),
            "fetch", root_hash,
            "--output", str(out_file)
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == sample_text


def test_cli_export_zim_plain_text_fallback(tmp_path: Path):
    """Verify export-zim does not fail with NameError on hashlib when exporting plain text."""
    txt_file = tmp_path / "offline_guidelines.txt"
    txt_file.write_text("Community emergency procedures and contacts.", encoding="utf-8")
    out_zim = tmp_path / "zim_output"

    res = subprocess.run(
        [
            sys.executable, "-m", "tfp_core_v4.cli",
            "export-zim", str(txt_file),
            "--out", str(out_zim),
            "--title", "Community Triage"
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "Kiwix / ZIM Bundle Export Complete" in res.stdout
    assert (out_zim / "index.html").exists()
    assert (out_zim / "manifest.json").exists()


def test_afsk_packet_size_symmetric_limit():
    """Verify that AFSK modulator and demodulator enforce symmetric 4096-byte packet limits."""
    from tfp_client.lib.audio.afsk_modulator import AFSKModulator, MAX_AFSK_PAYLOAD_SIZE
    from tfp_client.lib.audio.afsk_demodulator import MAX_AFSK_PAYLOAD_SIZE as RX_MAX

    assert MAX_AFSK_PAYLOAD_SIZE == 4096
    assert RX_MAX == 4096

    mod = AFSKModulator()
    # 4096 bytes: within limit
    framed_ok = mod.frame_packet(b"X" * 4096)
    assert len(framed_ok) > 4096

    # 4097 bytes: must be rejected with ValueError
    import pytest
    with pytest.raises(ValueError, match="exceeds maximum allowed 4096 bytes"):
        mod.frame_packet(b"X" * 4097)

