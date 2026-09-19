# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Headless Audio Scholar Appliance Daemon for The Foundation Protocol (TFP v4.0).

Designed for screenless, zero-touch operation on low-power edge appliances
(Raspberry Pi, solar radios, loudspeakers, broken-screen phones).

Operates entirely through audio:
1. Listens to incoming rateless fountain droplets over UDP or radio tone frames.
2. Performs dynamic GF(2) Gaussian elimination until Rank K is achieved.
3. Automatically synthesizes bit-exact emergency medical or educational triage guides.
4. Generates procedural acoustic earcons (Pythagorean harmonic triads) for auditory cues.
5. Speaks out instructions locally via offline text-to-speech (espeak-ng / pyttsx3 / TTS fallback).
"""

from __future__ import annotations

import html
import logging
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Ensure repository paths are importable
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.fountain_streamer import MediaDropletPacket
from tfp_client.lib.media.live_streamer import LiveTransmissionEngine
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.telemetry_events import TelemetryEventBus

log = logging.getLogger("tfp.audio_scholar")


class AudioScholarDaemon:
    """
    Headless Audio Scholar appliance daemon for zero-touch acoustic triage.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",  # nosec B104
        port: int = 9999,
        symbol_size: int = 256,
        secret_key: bytes = b"tfp-live-stream-key-2026",
        earcons_enabled: bool = True,
        speech_rate: int = 140,
        on_narration_callback: Callable[[str, str], None] | None = None,
    ):
        self.host = host
        self.port = port
        self.symbol_size = symbol_size
        self.secret_key = secret_key
        self.earcons_enabled = earcons_enabled
        self.speech_rate = speech_rate
        self.on_narration_callback = on_narration_callback

        self.receiver = FountainStreamReceiver(symbol_size=symbol_size, secret_key=secret_key)
        self.event_bus = TelemetryEventBus.get_instance()

        self._running = False
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

        # State tracking
        self.total_packets_received = 0
        self.reconstructed_payloads: list[bytes] = []
        self.spoken_narrations: list[str] = []
        self.last_title: str = ""
        self.last_narration: str = ""

    def start_in_thread(self) -> None:
        """Starts the daemon in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self.start_sync, daemon=True, name="AudioScholarWorker")
        self._thread.start()
        log.info(f"[AudioScholar] Background daemon started on {self.host}:{self.port}")

    def stop(self) -> None:
        """Signals the daemon loop to stop and closes resources."""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("[AudioScholar] Daemon stopped.")

    def start_sync(self, timeout: float | None = None) -> None:
        """
        Runs the daemon listening loop synchronously.
        """
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
            sock.settimeout(1.0)
            self._socket = sock
            log.info(f"[AudioScholar] Listening for fountain droplets on UDP {self.host}:{self.port}")

            start_time = time.monotonic()
            while self._running:
                if timeout is not None and (time.monotonic() - start_time) > timeout:
                    break

                try:
                    data, _addr = sock.recvfrom(65535)
                    self.ingest_raw_packet(data)
                except TimeoutError:
                    continue
                except OSError:
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._running = False

    def ingest_raw_packet(self, raw_data: bytes) -> tuple[int, bytes] | None:
        """
        Ingests a raw UDP packet, unmarshals MediaDropletPacket, feeds into
        FountainStreamReceiver, and triggers speech triage upon Rank K completion.
        """
        self.total_packets_received += 1
        try:
            pkt = MediaDropletPacket.from_bytes(raw_data, secret_key=self.secret_key)
        except (ValueError, KeyError, struct.error, OSError) as exc:
            log.debug(f"[AudioScholar] Invalid droplet discarded: {exc}")
            return None

        self.event_bus.emit(
            "scholar_packet_received",
            seed=pkt.seed,
            k=pkt.k,
            chunk_index=pkt.chunk_index,
        )

        res = self.receiver.ingest_packet(pkt)
        if res is not None:
            chunk_idx, reconstructed_chunk = res
            self.reconstructed_payloads.append(reconstructed_chunk)
            log.info(
                f"[AudioScholar] Chunk {chunk_idx} Reconstructed! "
                f"({len(reconstructed_chunk)} bytes). Processing acoustic output..."
            )
            self._process_reconstructed_content(reconstructed_chunk)
            return res
        return None

    def _process_reconstructed_content(self, data: bytes) -> None:
        """
        Parses text, markdown, HTML, or JSON codex content and delivers acoustic output.
        """
        title, narration = self.extract_title_and_narration(data)
        self.last_title = title
        self.last_narration = narration
        self.spoken_narrations.append(narration)

        # 1. Play procedural arrival earcon
        if self.earcons_enabled:
            self.play_earcon("verified")

        # 2. Speak narration
        self.speak(narration)

        # 3. Emit event bus notification
        self.event_bus.emit(
            "scholar_narration_delivered",
            title=title,
            narration=narration,
            bytes_count=len(data),
        )

        # 4. Trigger user callback if provided
        if self.on_narration_callback:
            try:
                self.on_narration_callback(title, narration)
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                log.warning(f"[AudioScholar] Narration callback error: {exc}")

    @staticmethod
    def extract_title_and_narration(data: bytes) -> tuple[str, str]:
        """
        Extracts human-digestible triage title and spoken narration from incoming content.
        Supports HTML, Markdown, JSON, and raw text.
        """
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except (UnicodeDecodeError, ValueError) as exc:
                log.debug(f"[AudioScholar] Non-text payload notice: {exc}")
                return "Binary Payload", "Received binary payload. Sovereign audit verified."

        # Case A: Check for HTML structure
        if "<html" in text.lower() or "<!doctype" in text.lower() or "<title" in text.lower():
            # Strip CSS and JS blocks so they never leak into speech
            cleaned_html = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
            cleaned_html = re.sub(r"<script[^>]*>.*?</script>", "", cleaned_html, flags=re.IGNORECASE | re.DOTALL)

            title_m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", cleaned_html, re.IGNORECASE | re.DOTALL)
            if title_m:
                title = html.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
            else:
                title_tag = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
                if title_tag:
                    title = html.unescape(re.sub(r"<[^>]+>", "", title_tag.group(1))).strip()
                else:
                    title = "Emergency Protocol"

            # Look for spoken narration container or scholastic step instruction
            voice_m = re.search(
                r'(?:id=["\'](?:slideNarration|stepInstruction)["\']|class=["\'](?:narration-box|step-text)["\'])[^>]*>(.*?)<(?:/div|/p)>',
                cleaned_html,
                re.IGNORECASE | re.DOTALL,
            )
            if voice_m:
                raw_voice = re.sub(r"<[^>]+>", "", voice_m.group(1)).strip()
                cleaned_voice = html.unescape(raw_voice).replace("🔊 VOICE:", "").replace('"', "").strip()
                if cleaned_voice:
                    return title, cleaned_voice

            # Extract bullet points
            bullets = re.findall(r"<li>(.*?)</li>", cleaned_html, re.IGNORECASE | re.DOTALL)
            if bullets:
                cleaned_bullets = [html.unescape(re.sub(r"<[^>]+>", "", b)).strip() for b in bullets[:4]]
                bullet_summary = ". ".join(cleaned_bullets)
                return title, f"Protocol: {title}. {bullet_summary}"

            # Fallback for plain HTML body text
            body_clean = re.sub(r"<[^>]+>", " ", cleaned_html)
            body_clean = " ".join(body_clean.split())
            return title, body_clean[:250]

        # Case B: Check for Markdown structure
        if text.startswith("#") or "\n## " in text:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0].lstrip("#").strip() if lines else "Field Protocol"
            body_sentences = []
            for line in lines[1:]:
                if line.startswith(("-", "*", "•")):
                    body_sentences.append(line.lstrip("-*• ").strip())
                elif not line.startswith(("#", ">")):
                    body_sentences.append(line)
            narration = f"Attention: {title}. " + " ".join(body_sentences[:3])
            return title, narration

        # Case C: Plain text or unknown format
        clean_text = " ".join(text.split())
        title = "Acoustic Message"
        narration = clean_text[:300] if clean_text else "Acoustic message received."
        return title, narration

    def play_earcon(self, earcon_type: str = "verified") -> None:
        """
        Generates and plays a procedural PCM earcon.
        """
        wav_bytes = LiveTransmissionEngine.generate_earcon_pcm(earcon_type)
        log.info(f"[AudioScholar] Playing earcon '{earcon_type}' ({len(wav_bytes)} bytes WAV)")

        # Try OS playback mechanisms
        if sys.platform == "win32":
            try:
                import winsound

                winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
                return
            except (RuntimeError, OSError) as exc:
                log.debug(f"[AudioScholar] Winsound playback notice: {exc}")

        # Try aplay / paplay on Linux / ALSA
        aplay_bin = shutil.which("aplay")
        if aplay_bin:
            try:
                p = subprocess.Popen([aplay_bin, "-q"], stdin=subprocess.PIPE)  # nosec B603
                p.communicate(input=wav_bytes, timeout=1.5)
                return
            except (subprocess.SubprocessError, OSError) as exc:
                log.debug(f"[AudioScholar] aplay playback notice: {exc}")

    def speak(self, text: str) -> bool:
        """
        Synthesizes speech using local offline TTS (espeak-ng / pyttsx3 / stdout fallback).
        """
        log.info(f'[AudioScholar Voice Speaking]: "{text}"')
        spoken_success = False

        # 1. Try espeak-ng or espeak CLI
        for espeak_cmd in ["espeak-ng", "espeak"]:
            espeak_bin = shutil.which(espeak_cmd)
            if espeak_bin:
                try:
                    subprocess.run(
                        [espeak_bin, "-s", str(self.speech_rate), text],  # nosec B603
                        check=False,
                        capture_output=True,
                        timeout=10,
                    )
                    spoken_success = True
                    break
                except (subprocess.SubprocessError, OSError) as exc:
                    log.debug(f"[AudioScholar] {espeak_cmd} invocation error: {exc}")

        # 2. Try pyttsx3 if espeak CLI is not present
        if not spoken_success:
            try:
                import pyttsx3  # type: ignore

                engine = pyttsx3.init()
                engine.setProperty("rate", self.speech_rate)
                engine.say(text)
                engine.runAndWait()
                spoken_success = True
            except (ImportError, RuntimeError, OSError) as exc:
                log.debug(f"[AudioScholar] pyttsx3 invocation notice: {exc}")

        # 3. Always print authoritative phonetic broadcast to stdout
        print("\n" + "─" * 60)
        print("  🏛️ [AUDIO SCHOLAR ANNOUNCEMENT] 🔊")
        print(f"  \"{text}\"")
        print("─" * 60 + "\n", flush=True)

        return spoken_success
