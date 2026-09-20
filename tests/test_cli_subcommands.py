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
    articles_dir = Path("data/articles")
    assert articles_dir.exists()

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
