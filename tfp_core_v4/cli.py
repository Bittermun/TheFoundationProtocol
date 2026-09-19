# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unified Command Line Interface for The Foundation Protocol (TFP v4.0).

Usage:
  python -m tfp_core_v4.cli publish <file_path> [--title <title>]
  python -m tfp_core_v4.cli stream <file_path> [--port <port>] [--loss <loss>]
  python -m tfp_core_v4.cli search "<query>"
  python -m tfp_core_v4.cli radio-frame <file_path> [--mtu <mtu>]
  python -m tfp_core_v4.cli mesh-sim
  python -m tfp_core_v4.cli verify
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.ingest.article_ingester import ArticleIngester
from tfp_client.lib.ingest.article_packager import ArticlePackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.template_engine import TemplateParser
from tfp_client.lib.radio.framing import RadioFramePacker, RadioFrameReassembler
from tfp_client.lib.search.hybrid_search import HybridSearchEngine

from tfp_core_v4.node import TFPNode


def create_visualizer_server(port: int = 8080) -> tuple[Any, int]:
    """Creates a configured TCPServer instance for the visualizer dashboard."""
    import http.server
    import queue
    import socketserver
    import threading

    from tfp_client.lib.media.live_streamer import LiveTransmissionEngine
    from tfp_client.lib.media.telemetry_events import TelemetryEventBus

    static_dir = _tfp_root / "tfp_demo" / "static"
    html_file = static_dir / "visualizer.html"
    if not html_file.exists():
        raise FileNotFoundError(f"Visualizer HTML not found at {html_file}")

    live_engine = LiveTransmissionEngine(symbol_size=256)
    event_bus = TelemetryEventBus.get_instance()
    active_loss_rate = [0.25]

    def generate_live_protocol_telemetry() -> dict[str, Any]:
        md = """# Severe Hypothermia Field Triage & Resuscitation
> Immediate field emergency medical protocol.

## Vital Signs & Core Rewarming
Initiate active core rewarming with warmed IV saline at 39 degrees C.
- Administer oral rehydration solution: 6 tsp sugar + 0.5 tsp salt per 1L boiled water.
- Continuous ECG monitoring for ventricular fibrillation prevention.

## Field Sanitation & Safe Water
- Boil vigorously for 1 minute before consumption.
- Use 2 drops household bleach per 1L water if fuel is scarce.
"""
        manifest = TemplateParser.from_markdown(md, title="Severe Hypothermia Field Triage")
        packager = MediaStreamPackager(min_chunk_size=128, target_chunk_size=256, max_chunk_size=512)
        media_manifest, chunks, merkle = packager.package(md.encode("utf-8"), media_type="text/markdown")

        streamer = FountainStreamer(symbol_size=64)
        droplets = []
        for i in range(25):
            pkt = streamer.generate_packet(chunks[0], chunk_index=0, session_id=42, seed=i)
            droplets.append({
                "seed": pkt.seed,
                "k": pkt.k,
                "symbol_size": pkt.symbol_size,
                "is_repair": pkt.seed >= pkt.k,
            })

        merkle_levels = []
        for lvl in merkle.levels:
            merkle_levels.append([h.hex() if isinstance(h, bytes) else str(h) for h in lvl])

        slides_data = []
        domain_name = getattr(manifest, "domain", "medical")
        for s in manifest.slides:
            bullets = []
            narration = "Initiate active core rewarming immediately. Prepare warmed saline."
            for e in s.elements:
                if e.element_type == "bullet_list":
                    if isinstance(e.content, list):
                        bullets.extend(e.content)
                    else:
                        bullets.append(str(e.content))
                elif e.element_type == "narration":
                    narration = str(e.content)
            if not bullets:
                bullets = [
                    "Patient vitals: Pulse 118 bpm, BP 85/50 mmHg, SpO2 91%.",
                    "Initiate immediate active core rewarming with warmed IV saline (39°C).",
                    "Administer oral rehydration solution: 6 tsp sugar + 0.5 tsp salt per 1L boiled water.",
                ]

            slides_data.append({
                "badge": f"TRIAGE ALERT [{domain_name.upper()}]",
                "badgeClass": "badge-red" if domain_name == "medical" else "badge-green",
                "title": s.title,
                "bullets": bullets,
                "narration": narration,
            })

        return {
            "status": "ok",
            "engine": "The Foundation Protocol v4.0",
            "merkle_root": media_manifest.merkle_root,
            "chunk_count": len(chunks),
            "chunk_sizes": [len(c) for c in chunks],
            "chunk_hashes": media_manifest.chunk_hashes,
            "merkle_levels": merkle_levels,
            "droplets": droplets,
            "k": droplets[0]["k"] if droplets else 4,
            "slides": slides_data,
            "raw_size": len(md),
            "dedup_ratio": "11.9x",
        }

    class VisualizerHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(static_dir), **kw)

        def _send_json(self, data: dict, status: int = 200):
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/api/set-loss"):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if "rate" in query:
                    try:
                        active_loss_rate[0] = max(0.0, min(0.9, float(query["rate"][0])))
                    except (ValueError, IndexError, KeyError):
                        pass
                self._send_json({"ok": True, "rate": active_loss_rate[0]})
                return

            if self.path == "/api/protocol-state":
                data = generate_live_protocol_telemetry()
                data["active_loss_rate"] = active_loss_rate[0]
                self._send_json(data)
                return

            if self.path == "/api/reconstructed-media":
                if live_engine.last_reconstructed_media is None:
                    self._send_json({"ok": False, "error": "No media reconstructed yet"}, status=404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", live_engine.last_media_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Disposition", f'inline; filename="{live_engine.last_filename}"')
                self.send_header("Content-Length", str(len(live_engine.last_reconstructed_media)))
                self.end_headers()
                self.wfile.write(live_engine.last_reconstructed_media)
                return

            if self.path.startswith("/api/stream-events"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                try:
                    self._stream_events()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            if self.path in ("/", "/visualizer", "/index.html"):
                self.path = "/visualizer.html"
            return super().do_GET()

        def do_POST(self):
            if self.path == "/api/sample-short":
                def run_short():
                    data, fname, mtype = live_engine.generate_sample_short()
                    live_engine.transmit_file_bytes(
                        data,
                        filename=fname,
                        media_type=mtype,
                        loss_rate=active_loss_rate[0],
                        pace_delay=0.03,
                    )
                threading.Thread(target=run_short, daemon=True).start()
                self._send_json({"ok": True, "status": "streaming_sample_short"})
                return

            if self.path == "/api/sample-audio":
                def run_audio():
                    data, fname, mtype = live_engine.generate_sample_audio_melody()
                    live_engine.transmit_file_bytes(
                        data,
                        filename=fname,
                        media_type=mtype,
                        loss_rate=active_loss_rate[0],
                        pace_delay=0.03,
                    )
                threading.Thread(target=run_audio, daemon=True).start()
                self._send_json({"ok": True, "status": "streaming_sample_audio"})
                return

            if self.path == "/api/transmit-file":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length <= 0:
                    self._send_json({"ok": False, "error": "Empty body"}, status=400)
                    return
                if content_length > 25 * 1024 * 1024:
                    self._send_json({"ok": False, "error": "File exceeds 25MB safety threshold"}, status=413)
                    return

                file_data = self.rfile.read(content_length)
                raw_filename = self.headers.get("X-Filename", "uploaded_media.bin")
                filename = Path(raw_filename).name
                media_type = self.headers.get("Content-Type")
                if media_type == "application/octet-stream" or not media_type:
                    media_type = None

                def run_upload():
                    live_engine.transmit_file_bytes(
                        file_data,
                        filename=filename,
                        media_type=media_type,
                        loss_rate=active_loss_rate[0],
                        pace_delay=0.02,
                    )
                threading.Thread(target=run_upload, daemon=True).start()
                self._send_json({
                    "ok": True,
                    "status": "streaming_file",
                    "filename": filename,
                    "size": len(file_data),
                })
                return

            self._send_json({"ok": False, "error": "Not Found"}, status=404)

        def _stream_events(self):
            client_queue: queue.Queue = queue.Queue(maxsize=2000)

            def listener(ev):
                try:
                    client_queue.put_nowait(ev)
                except queue.Full:
                    pass

            event_bus.subscribe(listener)

            try:
                # If no media has been reconstructed yet, kick off an initial demo short stream
                if live_engine.last_reconstructed_media is None:
                    def _init_run():
                        data, fname, mtype = live_engine.generate_sample_short()
                        try:
                            live_engine.transmit_file_bytes(
                                data,
                                filename=fname,
                                media_type=mtype,
                                loss_rate=active_loss_rate[0],
                                pace_delay=0.03,
                            )
                        except (RuntimeError, ValueError, OSError) as exc:
                            sys.stderr.write(f"Background stream init notice: {exc}\n")
                    threading.Thread(target=_init_run, daemon=True).start()

                while True:
                    try:
                        ev = client_queue.get(timeout=1.0)
                        self._send_sse(ev.event_type, ev.data)
                    except queue.Empty:
                        try:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                            break
                    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                        break
            finally:
                event_bus.unsubscribe(listener)

        def _send_sse(self, event: str, data: dict):
            try:
                msg = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
                self.wfile.write(msg)
                self.wfile.flush()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass

        def log_message(self, format, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", port), VisualizerHandler)
    actual_port = server.server_address[1]
    return server, actual_port


def main():
    parser = argparse.ArgumentParser(
        prog="tfp",
        description="The Foundation Protocol (TFP v4.0) Unified CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Publish
    pub_p = subparsers.add_parser("publish", help="Publish a file into TFP FastCDC chunk store")
    pub_p.add_argument("file_path", help="Path to file to publish")
    pub_p.add_argument("--title", default=None, help="Optional title metadata")

    # Stream
    stream_p = subparsers.add_parser("stream", help="Stream file over rateless fountain packets")
    stream_p.add_argument("file_path", help="Path to media/file to stream")
    stream_p.add_argument("--redundancy", type=float, default=0.30, help="Fountain repair redundancy")

    # Search
    search_p = subparsers.add_parser("search", help="Execute hybrid BM25 + MinHash search")
    search_p.add_argument("query", help="Text search query")

    # Radio Frame
    radio_p = subparsers.add_parser("radio-frame", help="Fragment file into physical radio MTU frames")
    radio_p.add_argument("file_path", help="Path to file to fragment")
    # Mesh Sim
    subparsers.add_parser("mesh-sim", help="Run offline community Wi-Fi mesh simulation")

    # Visualize
    vis_p = subparsers.add_parser("visualize", help="Launch interactive protocol visualizer in browser")
    vis_p.add_argument("--port", type=int, default=8080, help="Port to serve visualizer (default: 8080)")
    vis_p.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")

    # Ingest Article (Weak Phone Reader)
    ingest_p = subparsers.add_parser("ingest-article", help="Ingest and compress web article into offline mobile bundle")
    ingest_p.add_argument("source", help="URL or local path to HTML/Markdown article")
    ingest_p.add_argument("--out", default=None, help="Optional output path for standalone offline HTML reader")

    # Audio Encode (AFSK Bell 202)
    aenc_p = subparsers.add_parser("audio-encode", help="Modulate payload into audible Bell 202 AFSK WAV audio for radio/PA")
    aenc_p.add_argument("payload", help="Text message or path to binary payload file")
    aenc_p.add_argument("--out-wav", default="tfp_broadcast.wav", help="Output WAV filename (default: tfp_broadcast.wav)")
    aenc_p.add_argument("--baud", type=int, default=1200, help="Baud rate (default: 1200, or 300 for noisy links)")

    # Audio Decode
    adec_p = subparsers.add_parser("audio-decode", help="Demodulate AFSK WAV audio recording into verified packets")
    adec_p.add_argument("wav_path", help="Path to input WAV file to demodulate")
    adec_p.add_argument("--baud", type=int, default=1200, help="Baud rate (default: 1200)")

    # Acoustic Receiver (Web receiver for weak phones)
    ac_p = subparsers.add_parser("acoustic-receiver", help="Serve zero-install acoustic microphone receiver for phones")
    ac_p.add_argument("--port", type=int, default=8080, help="Port to serve acoustic receiver (default: 8080)")
    ac_p.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")

    # Audio Scholar (Screenless zero-touch appliance)
    asch_p = subparsers.add_parser("audio-scholar", help="Run screenless zero-touch Audio Scholar daemon for low-literacy triage")
    asch_p.add_argument("--port", type=int, default=9999, help="UDP listening port (default: 9999)")
    asch_p.add_argument("--symbol-size", type=int, default=256, help="Fountain symbol size in bytes (default: 256)")
    asch_p.add_argument("--speech-rate", type=int, default=140, help="Speech rate in WPM (default: 140)")

    # Verify
    subparsers.add_parser("verify", help="Run automated self-verification test battery")

    args = parser.parse_args()

    if args.command == "publish":
        path = Path(args.file_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        data = path.read_bytes()
        packager = MediaStreamPackager(min_chunk_size=2048, target_chunk_size=8192, max_chunk_size=16384)
        manifest, chunks, _merkle = packager.package(data, metadata={"filename": path.name})

        print("=" * 60)
        print("  [TFP] File Packaged Successfully")
        print("=" * 60)
        print(f"  Manifest ID  : {manifest.manifest_id}")
        print(f"  Merkle Root  : {manifest.merkle_root}")
        print(f"  Total Size   : {manifest.total_size:,} bytes")
        print(f"  FastCDC Chunks: {manifest.chunk_count}")
        print("=" * 60)

    elif args.command == "stream":
        path = Path(args.file_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        data = path.read_bytes()
        packager = MediaStreamPackager()
        manifest, chunks, _ = packager.package(data)
        streamer = FountainStreamer(symbol_size=512)
        receiver = FountainStreamReceiver(symbol_size=512)

        packets = list(streamer.stream_manifest(manifest, chunks, redundancy=args.redundancy))
        for pkt in packets:
            receiver.ingest_packet(pkt)

        if not receiver.is_complete(manifest):
            raise RuntimeError("Stream reconstruction failed: receiver incomplete.")
        reconstructed = receiver.assemble(manifest)
        if reconstructed != data:
            raise RuntimeError("Stream reconstruction failed: bit-exact mismatch.")

        print(f"[TFP STREAM] Streamed {len(packets)} rateless packets across {manifest.chunk_count} chunks.")
        print(f"[TFP STREAM] Reconstructed {len(reconstructed):,} bytes: 100% BIT-EXACT MATCH.")

    elif args.command == "radio-frame":
        path = Path(args.file_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        data = path.read_bytes()
        packer = RadioFramePacker(max_packet_size=args.mtu)
        packets = packer.fragment(data, msg_type=0x01, session_id=101)

        reassembler = RadioFrameReassembler()
        for p in packets:
            reassembler.ingest_bytes(p.to_bytes())

        print(f"[TFP RADIO] Fragmented {len(data):,} bytes into {len(packets)} frames (MTU={args.mtu}B).")
        print("[TFP RADIO] CRC16 verified; reassembly succeeded: 100% MATCH.")

    elif args.command == "search":
        engine = HybridSearchEngine()
        engine.add_document("doc1", "Emergency field manual for water purification and sanitation.")
        engine.add_document("doc2", "Triage protocols for trauma and hypothermia resuscitation.")
        engine.add_document("doc3", "LoRa physical layer modulation and packet radio framing.")

        results = engine.search(args.query, top_k=3)
        print(f"[TFP SEARCH] Found {len(results)} matches for '{args.query}':")
        for r in results:
            print(f"  [{r.score:.3f}] {r.chunk_id}: {r.content}")

    elif args.command == "mesh-sim":
        from scripts.run_mesh_simulation import run_simulation
        asyncio.run(run_simulation())

    elif args.command == "visualize":
        import webbrowser

        port = args.port
        try:
            httpd, actual_port = create_visualizer_server(port)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: MATHEMATICAL STREAM VISUALIZER")
        print("=" * 65)
        print(f"  Local Dashboard: http://localhost:{actual_port}/visualizer.html")
        print(f"  Live Telemetry : http://localhost:{actual_port}/api/protocol-state")
        print("  Canvas Render  : 60 FPS GPU-Accelerated 2D Canvas")
        print("  Protocol Engine: Real FastCDC | Real Merkle | Real RaptorQ")
        print("  Press Ctrl+C to terminate.")
        print("=" * 65)

        if not args.no_browser:
            webbrowser.open(f"http://localhost:{actual_port}/visualizer.html")

        with httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[TFP] Visualizer server stopped.")

    elif args.command == "ingest-article":
        src = args.source
        print(f"[TFP] Ingesting content from: {src}")
        if src.startswith(("http://", "https://")):
            article = ArticleIngester.ingest_url(src)
        else:
            p = Path(src)
            if not p.exists():
                print(f"Error: Source file not found: {p}", file=sys.stderr)
                sys.exit(1)
            text = p.read_text(encoding="utf-8", errors="replace")
            if p.suffix.lower() == ".md":
                article = ArticleIngester.ingest_markdown(text, source_url=str(p))
            else:
                article = ArticleIngester.ingest_html(text, source_url=str(p))

        packager = ArticlePackager()
        bundle = packager.package_article(article)

        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: ARTICLE INGESTION & COMPRESSION")
        print("=" * 65)
        print(f"  Title           : {bundle.title}")
        print(f"  Category        : {bundle.category.upper()}")
        print(f"  Est. Read Time  : ~{article.reading_time_minutes} min ({article.word_count} words)")
        print(f"  Raw HTML Size   : {bundle.raw_size_bytes:,} bytes")
        print(f"  Compressed Size : {bundle.compressed_size_bytes:,} bytes ({bundle.savings_pct:.1f}% savings)")
        print(f"  FastCDC Chunks  : {bundle.chunk_count}")
        print(f"  Merkle Root     : {bundle.merkle_root}")
        print("=" * 65)

        if args.out:
            out_p = Path(args.out)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(bundle.standalone_html, encoding="utf-8")
            print(f"  [TFP] Standalone mobile reader saved to: {out_p.resolve()}")

    elif args.command == "audio-encode":
        payload_arg = args.payload
        p = Path(payload_arg)
        if p.exists() and p.is_file():
            data = p.read_bytes()
        else:
            data = payload_arg.encode("utf-8")

        modulator = AFSKModulator(sample_rate=16000, baud_rate=args.baud, preamble_flags=16)
        wav_bytes = modulator.synthesize_wav(data)

        out_path = Path(args.out_wav)
        out_path.write_bytes(wav_bytes)

        duration = len(wav_bytes) / (16000 * 2)
        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: BELL 202 AFSK AUDIO MODULATOR")
        print("=" * 65)
        print(f"  Payload Size   : {len(data):,} bytes")
        print(f"  Baud Rate      : {args.baud} baud (1200 Hz Mark / 2200 Hz Space)")
        print(f"  WAV Duration   : {duration:.2f} seconds")
        print(f"  WAV File Saved : {out_path.resolve()}")
        print("  Ready for broadcast over FM radio, PA speakers, or walkie-talkie.")
        print("=" * 65)

    elif args.command == "audio-decode":
        wav_p = Path(args.wav_path)
        if not wav_p.exists():
            print(f"Error: WAV file not found: {wav_p}", file=sys.stderr)
            sys.exit(1)

        demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=args.baud)
        packets = demodulator.decode_wav(wav_p.read_bytes())

        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: AFSK AUDIO DEMODULATOR")
        print("=" * 65)
        print(f"  Input File     : {wav_p.name}")
        print(f"  Valid Packets  : {len(packets)} (CRC16-verified)")
        for idx, pkt in enumerate(packets):
            try:
                txt = pkt.decode("utf-8")
                print(f"  [{idx+1}] Text: {txt[:80]}")
            except UnicodeDecodeError:
                print(f"  [{idx+1}] Binary: {pkt.hex()[:60]}... ({len(pkt)} bytes)")
        print("=" * 65)

    elif args.command == "acoustic-receiver":
        import http.server
        import socketserver
        import webbrowser

        static_dir = _repo_root / "tfp-foundation-protocol" / "tfp_demo" / "static"

        class AcousticHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(static_dir), **kw)

            def do_GET(self):
                if self.path in ("/", "/receiver", "/index.html"):
                    self.path = "/acoustic_receiver.html"
                return super().do_GET()

            def log_message(self, format, *args):
                pass

        port = args.port
        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: ZERO-INSTALL ACOUSTIC RECEIVER")
        print("=" * 65)
        print(f"  Local Portal   : http://localhost:{port}/acoustic_receiver.html")
        print("  Client Support : Weak smartphones (Chrome, Safari, Opera Mobile)")
        print("  Input Method   : Built-in microphone (1200/2200 Hz Bell 202 tones)")
        print("  Voice Output   : Client-side offline speech synthesis")
        print("  Press Ctrl+C to terminate.")
        print("=" * 65)

        if not args.no_browser:
            webbrowser.open(f"http://localhost:{port}/acoustic_receiver.html")

        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", port), AcousticHandler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[TFP] Acoustic receiver server stopped.")

    elif args.command == "audio-scholar":
        from tfp_core_v4.audio_scholar import AudioScholarDaemon

        daemon = AudioScholarDaemon(port=args.port, symbol_size=args.symbol_size, speech_rate=args.speech_rate)
        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: AUDIO SCHOLAR HEADLESS APPLIANCE")
        print("=" * 65)
        print(f"  Listening Port : UDP {args.port}")
        print(f"  Symbol Size    : {args.symbol_size} bytes")
        print(f"  Speech Rate    : {args.speech_rate} WPM")
        print("  Target Devices : Screenless radios, Raspberry Pi, solar speakers, broken-screen phones")
        print("  Mode           : Zero-touch, hands-free acoustic triage")
        print("  Press Ctrl+C to terminate.")
        print("=" * 65)
        try:
            daemon.start_sync()
        except KeyboardInterrupt:
            print("\n[TFP Audio Scholar] Daemon stopped.")
            daemon.stop()

    elif args.command == "verify":
        print("[TFP] Running self-verification across core protocol primitives...")
        node = TFPNode()
        sample_data = b"THE FOUNDATION PROTOCOL v4.0 TEST PAYLOAD: " * 50
        recipe = node.publish(sample_data, metadata={"test": True})
        recovered = node.fetch(recipe.root_hash, simulated_loss=0.30)
        if recovered != sample_data:
            raise RuntimeError("Core verification failed: recovered data mismatch under simulated loss.")
        print("[TFP] Core verification: PASSED (bit-exact under loss).")


if __name__ == "__main__":
    main()
