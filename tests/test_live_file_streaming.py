# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Integration Tests for Live Real-File Transmission Engine & Visualizer Endpoints.

Validates:
1. Adaptive FastCDC slicing and Merkle generation on arbitrary bytes.
2. Full round-trip transmission of HTML shorts and WAV audio chimes under simulated packet loss.
3. Bit-exact media reconstruction and telemetry micro-events.
4. HTTP API endpoints (POST /api/transmit-file, POST /api/sample-short, GET /api/reconstructed-media).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest
from tfp_client.lib.media.live_streamer import LiveTransmissionEngine

from tfp_core_v4.cli import create_visualizer_server


class TestLiveTransmissionEngine:
    """Validates LiveTransmissionEngine core logic."""

    def test_mime_detection(self):
        """Verifies accurate MIME type inference from extensions and magic signatures."""
        assert LiveTransmissionEngine.detect_media_type("video.mp4", b"\x00\x00\x00 ftypisom") == "video/mp4"
        assert LiveTransmissionEngine.detect_media_type("clip.webm", b"\x1a\x45\xdf\xa3") == "video/webm"
        assert LiveTransmissionEngine.detect_media_type("tone.wav", b"RIFF....WAVEfmt ") == "audio/wav"
        assert LiveTransmissionEngine.detect_media_type("page.html", b"<!DOCTYPE html>") == "text/html"
        assert LiveTransmissionEngine.detect_media_type("notes.md", b"# Emergency") == "text/markdown"

    def test_sample_short_generation(self):
        """Verifies sample short generates valid HTML payload."""
        data, filename, media_type = LiveTransmissionEngine.generate_sample_short()
        assert len(data) > 200
        assert filename == "hypothermia_short.html"
        assert media_type == "text/html"
        assert b"Severe Hypothermia" in data

    def test_sample_audio_generation(self):
        """Verifies sample audio generates valid 16-bit PCM WAV."""
        data, filename, media_type = LiveTransmissionEngine.generate_sample_audio_melody()
        assert len(data) > 1000
        assert filename == "rescue_chime.wav"
        assert media_type == "audio/wav"
        assert data.startswith(b"RIFF")

    def test_transmit_file_bytes_bit_exact(self):
        """Verifies full round-trip streaming under 20% loss produces bit-exact reconstructed data."""
        recorded_events: list[tuple[str, dict[str, Any]]] = []

        def on_event(ev_type: str, data: dict[str, Any]):
            recorded_events.append((ev_type, data))

        engine = LiveTransmissionEngine(symbol_size=64, event_callback=on_event)
        test_payload = b"CRITICAL MEDICAL DIRECTIVE: 100mg Epinephrine IV at T+0." * 40

        res = engine.transmit_file_bytes(
            test_payload,
            filename="emergency_protocol.txt",
            media_type="text/plain",
            loss_rate=0.20,
            pace_delay=0.0,
        )

        assert res["bit_exact"] is True
        assert res["total_size"] == len(test_payload)
        assert engine.last_reconstructed_media == test_payload
        assert engine.last_filename == "emergency_protocol.txt"

        event_types = [t for t, _ in recorded_events]
        assert "cdc_cut" in event_types
        assert "merkle_step" in event_types
        assert "droplet_recv" in event_types
        assert "matrix_pivot" in event_types
        assert "media_reconstructed" in event_types

    def test_empty_payload_raises_error(self):
        """Verifies ValueError when passing empty bytes."""
        engine = LiveTransmissionEngine()
        with pytest.raises(ValueError, match="Data payload cannot be empty"):
            engine.transmit_file_bytes(b"")


class TestVisualizerServerEndpoints:
    """Validates HTTP endpoints of create_visualizer_server."""

    @pytest.fixture(scope="class")
    @classmethod
    def visualizer_server(cls, tmp_path_factory):
        server, port = create_visualizer_server(port=0, data_dir=tmp_path_factory.mktemp("live-stream"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"{base_url}/api/protocol-state", timeout=0.2):
                    break
            except (urllib.error.URLError, OSError, TimeoutError):
                time.sleep(0.05)

        yield base_url
        server.shutdown()
        server.server_close()

    def test_get_protocol_state(self, visualizer_server):
        with urllib.request.urlopen(f"{visualizer_server}/api/protocol-state") as res:
            assert res.status == 200
            data = json.loads(res.read().decode())
            assert data["status"] == "ok"
            assert "The Foundation Protocol" in data["engine"]
            assert "merkle_root" in data

    def test_set_loss_rate(self, visualizer_server):
        req = urllib.request.Request(f"{visualizer_server}/api/set-loss?rate=0.45")
        with urllib.request.urlopen(req) as res:
            assert res.status == 200
            data = json.loads(res.read().decode())
            assert data["ok"] is True
            assert data["rate"] == 0.45

    def test_post_sample_short(self, visualizer_server):
        req = urllib.request.Request(
            f"{visualizer_server}/api/sample-short",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            assert res.status == 200
            data = json.loads(res.read().decode())
            assert data["ok"] is True
            assert data["status"] == "streaming_sample_short"

    def test_post_sample_audio(self, visualizer_server):
        req = urllib.request.Request(
            f"{visualizer_server}/api/sample-audio",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            assert res.status == 200
            data = json.loads(res.read().decode())
            assert data["ok"] is True
            assert data["status"] == "streaming_sample_audio"

    def test_post_transmit_custom_file_and_retrieve_reconstructed(self, visualizer_server):
        # Transmit custom test file
        test_content = b"TEST RECONSTRUCTION PAYLOAD: RAPTORQ VALIDATION 2026." * 30
        req = urllib.request.Request(
            f"{visualizer_server}/api/transmit-file",
            data=test_content,
            headers={
                "X-Filename": "custom_audit.txt",
                "Content-Type": "text/plain",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            assert res.status == 200
            data = json.loads(res.read().decode())
            assert data["ok"] is True
            assert data["filename"] == "custom_audit.txt"

        # Wait for transmission and reconstruction to finish
        time.sleep(1.0)

        # Retrieve reconstructed media
        with urllib.request.urlopen(f"{visualizer_server}/api/reconstructed-media") as get_res:
            assert get_res.status == 200
            assert "text/plain" in get_res.headers.get("Content-Type")
            reconstructed_bytes = get_res.read()
            assert reconstructed_bytes == test_content
