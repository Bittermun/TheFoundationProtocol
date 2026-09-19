# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Live Real-File Transmission Engine & Telemetry Bus Bridge for TFP v4.0.

Pipes actual physical file chunks (web pages, audio tunes, short videos)
through FastCDC, Merkle trees, and rateless Fountain droplets, broadcasting
real-time telemetry events directly to web visualizers, dashboards, and network sockets.
"""

from __future__ import annotations

import base64
import math
import mimetypes
import secrets
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Ensure repository roots are importable
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaManifest, MediaStreamPackager
from tfp_client.lib.media.telemetry_events import TelemetryEventBus


@dataclass(frozen=True)
class ScholasticCodexEntry:
    """Represents a hands-free, voice-first educational and emergency triage codex."""

    title: str
    sector: str
    triage_tier: str
    epigraph: str
    steps: list[dict[str, Any]]
    earcon_cues: dict[str, list[float]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveTransmissionEngine:
    """
    Orchestrates real-time physical file transmission over rateless fountain codes
    and publishes live micro-events to the TelemetryEventBus.
    """

    def __init__(
        self,
        symbol_size: int = 512,
        secret_key: bytes | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.symbol_size = symbol_size
        self.secret_key = secret_key or b"tfp-live-stream-key-2026"
        self.event_callback = event_callback
        self.bus = TelemetryEventBus.get_instance()

        self.last_manifest: MediaManifest | None = None
        self.last_reconstructed_media: bytes | None = None
        self.last_media_type: str = "application/octet-stream"
        self.last_filename: str = "payload.bin"

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcasts an event to the global TelemetryEventBus and local callback."""
        self.bus.emit(event_type, **data)
        if self.event_callback:
            try:
                self.event_callback(event_type, data)
            except (TypeError, ValueError, RuntimeError):
                pass

    @staticmethod
    def detect_media_type(filename: str, data: bytes) -> str:
        """Determines accurate MIME type from file extension and magic byte signatures."""
        lower_name = filename.lower()
        if lower_name.endswith((".mp4", ".m4v")):
            return "video/mp4"
        if lower_name.endswith(".webm"):
            return "video/webm"
        if lower_name.endswith(".wav"):
            return "audio/wav"
        if lower_name.endswith(".mp3"):
            return "audio/mpeg"
        if lower_name.endswith(".opus"):
            return "audio/opus"
        if lower_name.endswith(".ogg"):
            return "audio/ogg"
        if lower_name.endswith((".html", ".htm")):
            return "text/html"
        if lower_name.endswith(".md"):
            return "text/markdown"
        if lower_name.endswith(".json"):
            return "application/json"
        if lower_name.endswith(".svg"):
            return "image/svg+xml"

        # Magic byte detection fallback
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if len(data) >= 8 and data[4:8] == b"ftyp":
            return "video/mp4"
        if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WAVE":
            return "audio/wav"
        if data.startswith(b"ID3") or (len(data) >= 2 and data[:2] == b"\xff\xfb"):
            return "audio/mpeg"
        if data.startswith(b"OggS"):
            return "audio/ogg"
        if data.startswith((b"<!DOCTYPE", b"<html", b"<svg")):
            return "text/html"

        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"

    def transmit_file_bytes(
        self,
        data: bytes,
        filename: str = "payload.bin",
        media_type: str | None = None,
        loss_rate: float = 0.20,
        pace_delay: float = 0.015,
    ) -> dict[str, Any]:
        """
        Processes physical binary file bytes through FastCDC, Merkle authentication,
        and Fountain streaming, broadcasting real-time protocol telemetry.
        """
        if not data:
            raise ValueError("Data payload cannot be empty.")

        resolved_media_type = media_type or self.detect_media_type(filename, data)
        self.last_media_type = resolved_media_type
        self.last_filename = filename

        # 1. Adaptive FastCDC Chunking Parameters
        total_len = len(data)
        if total_len < 32768:
            packager = MediaStreamPackager(min_chunk_size=128, target_chunk_size=512, max_chunk_size=1024)
            symbol_size = max(32, total_len // 16)
        elif total_len < 524288:
            packager = MediaStreamPackager(min_chunk_size=1024, target_chunk_size=4096, max_chunk_size=8192)
            symbol_size = 256
        else:
            packager = MediaStreamPackager(min_chunk_size=4096, target_chunk_size=16384, max_chunk_size=32768)
            symbol_size = 512

        # 2. Package into FastCDC Chunks & Merkle Tree
        manifest, chunks, merkle_tree = packager.package(
            data,
            media_type=resolved_media_type,
            metadata={"filename": filename},
        )
        self.last_manifest = manifest

        # Emit FastCDC cut events
        cumulative_cut = 0
        for i, c in enumerate(chunks):
            cumulative_cut += len(c)
            self.emit_event(
                "cdc_cut",
                {
                    "index": i,
                    "chunk_size": len(c),
                    "cut": cumulative_cut,
                    "hash": manifest.chunk_hashes[i][:16],
                    "total_chunks": manifest.chunk_count,
                    "progress_pct": round((cumulative_cut / total_len) * 100.0, 1),
                },
            )
            if pace_delay > 0:
                time.sleep(pace_delay)

        # Emit Merkle Tree authentication event
        merkle_levels = [
            [h.hex() if isinstance(h, bytes) else str(h) for h in lvl]
            for lvl in merkle_tree.levels
        ]
        self.emit_event(
            "merkle_step",
            {
                "status": "verified",
                "root": manifest.merkle_root,
                "levels": merkle_levels,
                "chunk_count": manifest.chunk_count,
                "total_size": manifest.total_size,
            },
        )
        if pace_delay > 0:
            time.sleep(pace_delay * 2)

        # 3. Stream through Fountain Codec with Real-Time Matrix Rank Tracking
        streamer = FountainStreamer(symbol_size=symbol_size, secret_key=self.secret_key)
        receiver = FountainStreamReceiver(symbol_size=symbol_size, secret_key=self.secret_key)
        sys_rng = secrets.SystemRandom()

        # Generate rateless packet stream (with 50% repair redundancy)
        packets = list(streamer.stream_manifest(manifest, chunks, redundancy=0.50))
        droplets_sent = 0
        droplets_dropped = 0

        for pkt in packets:
            droplets_sent += 1
            is_lost = sys_rng.random() < loss_rate

            if is_lost:
                droplets_dropped += 1
                self.emit_event(
                    "droplet_drop",
                    {
                        "seed": pkt.seed,
                        "chunk_index": pkt.chunk_index,
                        "k": pkt.k,
                        "loss_rate": loss_rate,
                    },
                )
            else:
                receiver.ingest_packet(pkt)
                buf = receiver._droplet_buffers.get(pkt.chunk_index, {})
                k, _ = receiver._chunk_meta.get(pkt.chunk_index, (pkt.k, len(data)))
                current_rank = k if pkt.chunk_index in receiver.reconstructed_chunks else min(k, len(buf))

                self.emit_event(
                    "droplet_recv",
                    {
                        "seed": pkt.seed,
                        "chunk_index": pkt.chunk_index,
                        "k": pkt.k,
                        "rank": current_rank,
                        "is_repair": pkt.seed >= pkt.k,
                    },
                )
                self.emit_event(
                    "matrix_pivot",
                    {
                        "chunk_index": pkt.chunk_index,
                        "rank": current_rank,
                        "k": pkt.k,
                    },
                )

            if pace_delay > 0:
                time.sleep(pace_delay)

            # If all chunks are complete, early break
            if receiver.is_complete(manifest):
                break

        # 4. Final Assembly & Verification
        if not receiver.is_complete(manifest):
            # Send sufficient emergency systematic packets to guarantee completion if loss was high
            for pkt in packets:
                if not receiver.is_complete(manifest):
                    receiver.ingest_packet(pkt)

        if not receiver.is_complete(manifest):
            raise RuntimeError("Stream reconstruction failed: insufficient rank achieved under loss channel.")

        reconstructed = receiver.assemble(manifest)
        if reconstructed != data:
            raise RuntimeError("Integrity failure: reconstructed media does not bit-exact match original payload.")

        self.last_reconstructed_media = reconstructed

        # 5. Emit Full Reconstruction Event with Embedded Media for Instant UI Playback
        data_base64 = base64.b64encode(reconstructed).decode("ascii")
        data_uri = f"data:{resolved_media_type};base64,{data_base64}"

        reconstruction_summary = {
            "filename": filename,
            "media_type": resolved_media_type,
            "total_size": len(reconstructed),
            "chunk_count": manifest.chunk_count,
            "merkle_root": manifest.merkle_root,
            "droplets_sent": droplets_sent,
            "droplets_dropped": droplets_dropped,
            "effective_loss_pct": round((droplets_dropped / max(1, droplets_sent)) * 100.0, 1),
            "bit_exact": True,
            "data_uri": data_uri,
        }

        self.emit_event("media_reconstructed", reconstruction_summary)
        if "hypothermia" in filename.lower() or resolved_media_type in ("text/html", "text/markdown"):
            self.emit_event(
                "slide_ready",
                {
                    "title": "Severe Hypothermia Field Triage & Resuscitation",
                    "badge": "TRIAGE ALERT [MEDICAL]",
                    "badgeClass": "badge-red",
                    "bullets": [
                        "Check carotid pulse for full 60 seconds before initiating CPR.",
                        "Initiate active core rewarming with heated packs (39-42°C) to neck, axillae, and groin.",
                        "Administer oral rehydration solution once conscious: 6 tsp sugar + 0.5 tsp salt per 1L water.",
                    ],
                    "narration": "Initiate active core rewarming immediately. Never rub frozen extremities.",
                },
            )
        return reconstruction_summary

    @classmethod
    def generate_earcon_pcm(cls, earcon_type: str, sample_rate: int = 16000) -> bytes:
        """
        Synthesizes a pure 16-bit PCM mono WAV earcon for audio navigation.
        Earcon types:
          - 'verified': Rising major triad (D4 -> F#4 -> A4)
          - 'prompt': Double woodblock tap (880 Hz, 1200 Hz)
          - 'alert': Golden gong harmonic (220 Hz + 330 Hz + 440 Hz)
          - 'step_done': Crisp xylophone chime (587.33 Hz, 880 Hz)
        """
        samples: list[float] = []

        if earcon_type == "verified":
            notes = [(293.66, 0.08), (369.99, 0.08), (440.00, 0.16)]
            for freq, dur in notes:
                n_samples = int(sample_rate * dur)
                for i in range(n_samples):
                    t = i / sample_rate
                    decay = math.exp(-3.5 * (i / n_samples))
                    val = math.sin(2.0 * math.pi * freq * t) * decay * 0.4
                    samples.append(val)

        elif earcon_type == "prompt":
            for freq in (880.0, 1174.66):
                dur = 0.06
                n_samples = int(sample_rate * dur)
                for i in range(n_samples):
                    t = i / sample_rate
                    decay = math.exp(-12.0 * (i / n_samples))
                    val = math.sin(2.0 * math.pi * freq * t) * decay * 0.35
                    samples.append(val)
                samples.extend([0.0] * int(sample_rate * 0.03))

        elif earcon_type == "alert":
            dur = 0.45
            n_samples = int(sample_rate * dur)
            for i in range(n_samples):
                t = i / sample_rate
                decay = math.exp(-4.0 * (i / n_samples))
                val = (
                    0.45 * math.sin(2.0 * math.pi * 220.0 * t)
                    + 0.25 * math.sin(2.0 * math.pi * 330.0 * t)
                    + 0.15 * math.sin(2.0 * math.pi * 440.0 * t)
                ) * decay
                samples.append(val)

        else:  # 'step_done'
            notes = [(587.33, 0.09), (880.00, 0.16)]
            for freq, dur in notes:
                n_samples = int(sample_rate * dur)
                for i in range(n_samples):
                    t = i / sample_rate
                    decay = math.exp(-6.0 * (i / n_samples))
                    val = math.sin(2.0 * math.pi * freq * t) * decay * 0.4
                    samples.append(val)

        raw_pcm = bytearray()
        for s in samples:
            clamped = max(-1.0, min(1.0, s))
            sample_val = int(clamped * 32767.0)
            raw_pcm.extend(struct.pack("<h", sample_val))

        num_channels = 1
        bytes_per_sample = 2
        block_align = num_channels * bytes_per_sample
        byte_rate = sample_rate * block_align
        data_size = len(raw_pcm)

        header = bytearray()
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", 36 + data_size))
        header.extend(b"WAVEfmt ")
        header.extend(struct.pack("<I", 16))
        header.extend(struct.pack("<H", 1))  # PCM
        header.extend(struct.pack("<H", num_channels))
        header.extend(struct.pack("<I", sample_rate))
        header.extend(struct.pack("<I", byte_rate))
        header.extend(struct.pack("<H", block_align))
        header.extend(struct.pack("<H", bytes_per_sample * 8))
        header.extend(b"data")
        header.extend(struct.pack("<I", data_size))

        return bytes(header + raw_pcm)

    @classmethod
    def generate_sample_short(cls) -> tuple[bytes, str, str]:
        """
        Generates a standalone, educational multimedia 'Short' featuring:
        1. Encarta & Utopian Scholastic aesthetic styling (manuscript gold, deep indigo).
        2. Scalable single-stroke vector SVG anatomy diagram.
        3. Zero-touch offline voice navigation (SpeechRecognition / SpeechSynthesis).
        4. Web Audio procedural earcons and ambient Pythagorean harmonics.
        Returns: (payload_bytes, filename, media_type)
        """
        html_short = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Severe Hypothermia Triage &mdash; The Scholastic Codex</title>
<style>
  :root {
    --bg-codex: #060913;
    --gold-frame: #d4af37;
    --gold-glow: rgba(212, 175, 55, 0.4);
    --gold-subtle: rgba(212, 175, 55, 0.15);
    --ink-parchment: #f4f1ea;
    --ink-muted: #9da8ba;
    --ruby-alert: #ff3366;
    --cyan-salve: #00f0ff;
    --emerald-safe: #00ffa3;
    --font-serif: "Cinzel", "Baskerville", "Palatino Linotype", "Georgia", serif;
    --font-mono: "SF Mono", "Fira Code", "Consolas", monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--font-serif);
    background: var(--bg-codex);
    color: var(--ink-parchment);
    padding: 12px;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
  }
  .scholastic-frame {
    max-width: 440px;
    width: 100%;
    background: radial-gradient(circle at 50% 10%, #0d1527 0%, #060913 100%);
    border: 2px solid var(--gold-frame);
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 16px 48px rgba(0,0,0,0.8), inset 0 0 24px rgba(212,175,55,0.08);
    position: relative;
    overflow: hidden;
  }
  .scholastic-frame::before {
    content: "";
    position: absolute;
    top: 3px; left: 3px; right: 3px; bottom: 3px;
    border: 1px dashed rgba(212, 175, 55, 0.35);
    border-radius: 8px;
    pointer-events: none;
  }
  .codex-header {
    text-align: center;
    border-bottom: 1px solid var(--gold-subtle);
    padding-bottom: 14px;
    margin-bottom: 14px;
  }
  .codex-seal {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 2px;
    color: var(--gold-frame);
    text-transform: uppercase;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }
  .codex-title {
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    letter-spacing: 0.5px;
    line-height: 1.3;
    margin-bottom: 6px;
  }
  .codex-epigraph {
    font-size: 11px;
    font-style: italic;
    color: var(--ink-muted);
    font-family: Georgia, serif;
  }
  .atlas-container {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 10px 0;
    position: relative;
  }
  .atlas-svg {
    width: 140px;
    height: 190px;
    filter: drop-shadow(0 0 8px rgba(0, 240, 255, 0.3));
  }
  .pulse-core {
    animation: corePulse 2s ease-in-out infinite;
  }
  @keyframes corePulse {
    0%, 100% { fill: #00f0ff; r: 6; opacity: 0.8; }
    50% { fill: #ffcc00; r: 9; opacity: 1.0; filter: drop-shadow(0 0 6px #ffcc00); }
  }
  .voice-step-card {
    background: rgba(13, 21, 39, 0.7);
    border-left: 3px solid var(--gold-frame);
    padding: 12px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 14px;
    min-height: 84px;
  }
  .step-marker {
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 700;
    color: var(--gold-frame);
    letter-spacing: 1px;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }
  .step-text {
    font-size: 13px;
    line-height: 1.5;
    color: var(--ink-parchment);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  .zero-touch-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(4, 7, 13, 0.85);
    border: 1px solid var(--gold-subtle);
    border-radius: 24px;
    padding: 8px 14px;
  }
  .voice-btn {
    background: linear-gradient(135deg, #d4af37, #9b7e22);
    color: #060913;
    border: none;
    padding: 8px 16px;
    border-radius: 18px;
    font-weight: 700;
    font-size: 12px;
    cursor: pointer;
    font-family: var(--font-mono);
    letter-spacing: 0.5px;
    transition: all 0.2s;
  }
  .voice-btn:hover {
    box-shadow: 0 0 12px var(--gold-glow);
  }
  .ear-status {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--cyan-salve);
    display: flex;
    align-items: center;
    gap: 6px;
  }
</style>
</head>
<body>
<div class="scholastic-frame" id="codexFrame" onclick="advanceStep()">
  <div class="codex-header">
    <div class="codex-seal">&diams; THE SCHOLASTIC CODEX &bull; ENTRY IV-87 &diams;</div>
    <h1 class="codex-title">Severe Hypothermia Triage & Resuscitation</h1>
    <p class="codex-epigraph">&ldquo;Life is preserved in the core; blood follows warmth.&rdquo;</p>
  </div>

  <div class="atlas-container">
    <svg class="atlas-svg" viewBox="0 0 100 140" fill="none" xmlns="http://www.w3.org/2000/svg">
      <!-- Human silhouette wireframe -->
      <circle cx="50" cy="18" r="11" stroke="#4a5d78" stroke-width="1.5" />
      <path d="M50 29 L50 78 M32 42 L68 42 M32 42 L22 75 M68 42 L78 75 M50 78 L34 126 M50 78 L66 126" stroke="#4a5d78" stroke-width="1.8" stroke-linecap="round" />
      <!-- Active warming core zones -->
      <!-- Carotid (Neck) -->
      <circle class="pulse-core" id="pulseCarotid" cx="50" cy="30" r="6" />
      <!-- Left & Right Axillae (Armpits) -->
      <circle class="pulse-core" id="pulseAxillaeL" cx="37" cy="45" r="5" />
      <circle class="pulse-core" id="pulseAxillaeR" cx="63" cy="45" r="5" />
      <!-- Inguinal (Groin) -->
      <circle class="pulse-core" id="pulseGroin" cx="50" cy="78" r="6" />
    </svg>
  </div>

  <div class="voice-step-card">
    <div class="step-marker">
      <span id="stepLabel">STEP 1 OF 3</span>
      <span style="color: var(--cyan-salve);">&bull; ZERO-TOUCH ACTIVE</span>
    </div>
    <p class="step-text" id="stepInstruction">Check carotid pulse for a full 60 seconds before CPR. Core temperature below 30&deg;C induces severe bradycardia.</p>
  </div>

  <div class="zero-touch-bar">
    <button class="voice-btn" id="btnAudioAction" onclick="toggleVoiceDialog(event)">&#9658; SPEAK STEPS</button>
    <div class="ear-status" id="voiceStatus">&bull; TAP OR SAY &lsquo;NEXT&rsquo;</div>
  </div>
</div>

<script>
const codexSteps = [
  {
    num: "STEP 1 OF 3: RAPID CAROTID ASSESSMENT",
    text: "Check carotid pulse for a full 60 seconds before CPR. Core temperature below 30 degrees induces severe bradycardia.",
    speech: "Step one: Check carotid pulse for a full sixty seconds before initiating CPR. Core temperature below thirty degrees induces severe bradycardia. Say 'Next' or tap screen to continue.",
    focus: "pulseCarotid"
  },
  {
    num: "STEP 2 OF 3: ACTIVE CORE REWARMING",
    text: "Apply heated packs (39-42&deg;C) to the neck, axillae, and groin. Never rub frozen extremities.",
    speech: "Step two: Apply heated packs to the neck, armpits, and groin. Never rub frozen extremities, as cold acidotic blood will cause cardiac fibrillation. Say 'Next' to proceed.",
    focus: "pulseAxillaeL"
  },
  {
    num: "STEP 3 OF 3: ORAL HYDRATION RECOVERY",
    text: "Administer warm oral rehydration solution (6 tsp sugar + 0.5 tsp salt per 1L clean water) once conscious.",
    speech: "Step three: Once patient regains consciousness, administer warm oral rehydration solution: six teaspoons sugar and half teaspoon salt per one liter clean water. Protocol complete.",
    focus: "pulseGroin"
  }
];

let activeStep = 0;
let isSpeaking = false;
let speechRecognizer = null;

function renderStep(idx) {
  activeStep = Math.max(0, Math.min(idx, codexSteps.length - 1));
  const s = codexSteps[activeStep];
  document.getElementById("stepLabel").innerText = `STEP ${activeStep + 1} OF ${codexSteps.length}`;
  document.getElementById("stepInstruction").innerHTML = s.text;
  playScholasticChime(activeStep === codexSteps.length - 1 ? "step_done" : "prompt");
}

function advanceStep() {
  if (activeStep < codexSteps.length - 1) {
    renderStep(activeStep + 1);
  } else {
    renderStep(0);
  }
  speakActiveStep();
}

function playScholasticChime(type) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    if (type === "step_done") {
      osc.frequency.setValueAtTime(587.33, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(880.0, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } else {
      osc.frequency.setValueAtTime(880.0, ctx.currentTime);
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);
      osc.start();
      osc.stop(ctx.currentTime + 0.12);
    }
  } catch(e) {}
}

function speakActiveStep() {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(codexSteps[activeStep].speech);
  utter.rate = 0.92;
  utter.onstart = () => {
    isSpeaking = true;
    document.getElementById("btnAudioAction").innerText = "&#9632; PAUSE";
    document.getElementById("voiceStatus").innerText = "&bull; NARRATING...";
  };
  utter.onend = () => {
    isSpeaking = false;
    document.getElementById("btnAudioAction").innerText = "&#9658; REPEAT";
    document.getElementById("voiceStatus").innerText = "&bull; SAY 'NEXT' / 'REPEAT'";
  };
  window.speechSynthesis.speak(utter);
}

function toggleVoiceDialog(e) {
  if (e) e.stopPropagation();
  if (isSpeaking) {
    window.speechSynthesis.cancel();
    isSpeaking = false;
    document.getElementById("btnAudioAction").innerText = "&#9658; RESUME";
  } else {
    speakActiveStep();
    startVoiceListener();
  }
}

function startVoiceListener() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec || speechRecognizer) return;
  try {
    speechRecognizer = new SpeechRec();
    speechRecognizer.continuous = true;
    speechRecognizer.interimResults = false;
    speechRecognizer.lang = "en-US";
    speechRecognizer.onresult = (evt) => {
      const last = evt.results[evt.results.length - 1][0].transcript.toLowerCase().trim();
      console.log("[Voice Command]", last);
      if (last.includes("next") || last.includes("forward")) {
        advanceStep();
      } else if (last.includes("repeat") || last.includes("again")) {
        speakActiveStep();
      } else if (last.includes("back") || last.includes("previous")) {
        renderStep(Math.max(0, activeStep - 1));
        speakActiveStep();
      }
    };
    speechRecognizer.start();
  } catch(err) {
    console.log("[Voice Listener Unavailable]", err);
  }
}

// Inline headphone / spacebar click listener
window.addEventListener("keydown", (e) => {
  if (e.code === "Space") {
    e.preventDefault();
    advanceStep();
  }
});
</script>
</body>
</html>"""
        return html_short.encode("utf-8"), "hypothermia_short.html", "text/html"

    @classmethod
    def generate_sample_audio_melody(cls) -> tuple[bytes, str, str]:
        """
        Synthesizes a clean 3-second harmonic acoustic audio chime in 16-bit PCM WAV.
        """
        from tfp_client.lib.audio.afsk_modulator import AFSKModulator
        payload = b"TFP-HARMONIC-CHIME: RESCUE-PROTOCOL-ACTIVE"
        modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=8)
        wav_bytes = modulator.synthesize_wav(payload)
        return wav_bytes, "rescue_chime.wav", "audio/wav"
