# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Audio Scholar Headless Appliance and Encarta Scholastic Codex.

Validates:
1. ScholasticCodexEntry schema, immutability, and serialization.
2. Procedural PCM WAV earcon synthesis (Pythagorean harmonic triads, woodblock taps).
3. Text, Markdown, and HTML triage title and speech narration extraction.
4. End-to-end packet ingestion, Galois Field GF(2) solving, and acoustic triage delivery.
5. Headless UDP listening loop and thread lifecycle management.
"""

from __future__ import annotations

import io
import socket
import struct
import wave
from pathlib import Path

import pytest
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.live_streamer import (
    LiveTransmissionEngine,
    ScholasticCodexEntry,
)
from tfp_client.lib.media.stream_packager import MediaStreamPackager

from tfp_core_v4.audio_scholar import AudioScholarDaemon


def test_scholastic_codex_entry_structure():
    """Validates ScholasticCodexEntry dataclass invariants."""
    entry = ScholasticCodexEntry(
        title="I. THE ANATOMICAL ATLAS: CORE HYPOTHERMIA RESUSCITATION",
        sector="EMERGENCY MEDICINE",
        triage_tier="TIER-1 IMMEDIATE",
        epigraph="Ex umbra in solem — Sovereign life-preservation protocol.",
        steps=[
            {
                "num": 1,
                "title": "Vital Signs & Carotid Assessment",
                "instruction": "Palpate carotid pulse for full 60 seconds.",
            }
        ],
        earcon_cues={"step": [293.66, 369.99, 440.0]},
    )

    assert entry.title.startswith("I. THE ANATOMICAL ATLAS")
    assert entry.triage_tier == "TIER-1 IMMEDIATE"
    assert len(entry.steps) == 1

    d = entry.to_dict()
    assert isinstance(d, dict)
    assert d["sector"] == "EMERGENCY MEDICINE"
    assert d["earcon_cues"]["step"][0] == 293.66

    # Verify immutability
    with pytest.raises((AttributeError, TypeError)):
        entry.title = "New Title"  # type: ignore


@pytest.mark.parametrize("earcon_type", ["verified", "prompt", "alert", "step_done"])
def test_procedural_earcon_generation(earcon_type: str):
    """Validates procedural PCM WAV earcon generation produces well-formed 16-bit audio."""
    wav_bytes = LiveTransmissionEngine.generate_earcon_pcm(earcon_type)
    assert isinstance(wav_bytes, bytes)
    assert len(wav_bytes) > 200

    # Parse WAV RIFF header
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1  # Mono
        assert wf.getsampwidth() == 2  # 16-bit
        assert wf.getframerate() == 16000  # 16 kHz
        n_frames = wf.getnframes()
        assert n_frames > 0
        raw_frames = wf.readframes(n_frames)
        assert len(raw_frames) == n_frames * 2


def test_audio_scholar_text_and_narration_extraction():
    """Validates title and spoken narration extraction from various document formats."""
    # HTML with explicit narration container
    sample_html = b"""
    <!DOCTYPE html>
    <html>
      <head><title>Codex</title></head>
      <body>
        <h2>Severe Hypothermia Secondary to Immersion</h2>
        <div id="slideNarration">
          <span>&#128266; VOICE:</span>
          "Initiate active core rewarming with 39 degree saline immediately."
        </div>
        <ul>
          <li>Apply warming blankets to groin and axillae.</li>
        </ul>
      </body>
    </html>
    """
    title, narration = AudioScholarDaemon.extract_title_and_narration(sample_html)
    assert "Severe Hypothermia" in title
    assert "Initiate active core rewarming with 39 degree saline immediately." in narration

    # Markdown format
    sample_md = b"""# Field Water Disinfection
    > Emergency sanitation guidelines.
    - Boil rolling boil for 1 minute.
    - Add 2 drops bleach per liter if fuel scarce.
    """
    title_md, narration_md = AudioScholarDaemon.extract_title_and_narration(sample_md)
    assert "Field Water Disinfection" in title_md
    assert "Boil rolling boil for 1 minute" in narration_md

    # Plain text format
    sample_txt = b"Triage Alert: Evacuate southern ridge due to flash flood threat."
    title_txt, narration_txt = AudioScholarDaemon.extract_title_and_narration(sample_txt)
    assert title_txt == "Acoustic Message"
    assert "flash flood threat" in narration_txt


def test_audio_scholar_end_to_end_reconstruction():
    """Tests end-to-end fountain transmission, GF(2) solving, and audio scholar delivery."""
    short_content, _filename, _media_type = LiveTransmissionEngine.generate_sample_short()
    assert b"Severe Hypothermia" in short_content

    # Package into chunks
    packager = MediaStreamPackager(min_chunk_size=128, target_chunk_size=256, max_chunk_size=512)
    _manifest, chunks, _merkle = packager.package(short_content)
    assert len(chunks) >= 1

    streamer = FountainStreamer(symbol_size=64)
    target_chunk = chunks[0]

    narrations_received = []

    def on_narration(t: str, n: str):
        narrations_received.append((t, n))

    daemon = AudioScholarDaemon(
        symbol_size=64,
        secret_key=streamer.secret_key,
        earcons_enabled=False,
        on_narration_callback=on_narration,
    )

    # Generate fountain packets and ingest into daemon
    reconstructed = False
    for seed in range(60):
        pkt = streamer.generate_packet(target_chunk, chunk_index=0, session_id=101, seed=seed)
        res = daemon.ingest_raw_packet(pkt.to_bytes(secret_key=streamer.secret_key))
        if res is not None:
            reconstructed = True
            break

    assert reconstructed is True
    assert daemon.total_packets_received > 0
    assert len(daemon.reconstructed_payloads) == 1
    assert len(daemon.spoken_narrations) == 1
    assert len(narrations_received) == 1
    assert "Hypothermia" in daemon.last_title
    assert len(daemon.last_narration) > 10


def test_audio_scholar_daemon_socket_lifecycle():
    """Validates UDP socket binding, background thread execution, and graceful termination."""
    daemon = AudioScholarDaemon(host="127.0.0.1", port=0, earcons_enabled=False)

    # Test speaking string doesn't crash on any platform
    spoken = daemon.speak("Test voice transmission.")
    assert isinstance(spoken, bool)

    # Test earcon generation call
    daemon.play_earcon("verified")

    # Start and stop cleanly
    daemon.start_in_thread()
    assert daemon._running is True

    daemon.stop()
    assert daemon._running is False
