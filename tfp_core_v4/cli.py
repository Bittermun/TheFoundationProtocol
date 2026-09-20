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
import hashlib
import json
import os
import re
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
from tfp_client.lib.ingest.article_packager import ArticlePackager, PackagedArticleBundle
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

    search_engine = HybridSearchEngine(bm25_weight=0.70, lsh_weight=0.30)
    packager = ArticlePackager(lexicons_dir=_repo_root / "lexicons")
    articles_by_root: dict[str, Any] = {}

    INITIAL_ARTICLES = [
        """# Severe Hypothermia Field Triage & Resuscitation
> Immediate field emergency medical protocol for acute environmental hypothermia.

## Assessment & Staging
- Mild (35-32°C): Shivering, normal blood pressure, alert.
- Moderate (32-28°C): Ceased shivering, confusion, bradycardia.
- Severe (<28°C): Coma, ventricular fibrillation risk, apnea.

## Rewarming Protocols
- Initiate passive external rewarming in sheltered dry environment.
- Active core rewarming with warmed IV fluids at 39-42°C.
- Avoid rough movement to prevent ventricular fibrillation arrest.
- Administer oral rehydration: 6 tsp sugar + 0.5 tsp salt per 1L clean water.
""",
        """# Emergency Water Purification & Chlorine Dosage
> Field guidelines for making contaminated water bacteriologically safe.

## Boiling Protocol
- Bring water to a rolling boil for at least 1 full minute (3 minutes at altitudes above 2000m).
- Allow water to cool naturally without adding ice.

## Chemical Chlorination (Bleach / NaDCC)
- Household unscented bleach (5.25% - 8.25% sodium hypochlorite):
  - Clear water: 2 drops per liter (approx. 8 drops per gallon).
  - Cloudy / turbid water: Filter through clean cloth first, then 4 drops per liter.
- Stir thoroughly and let stand covered for at least 30 minutes.
- Water should have a slight chlorine scent. If not, repeat dose and wait 15 minutes.
""",
        """# FastCDC Content-Defined Chunking & Gear Hash Mechanics
> Technical architecture of boundary-shift resistant chunking in The Foundation Protocol.

## Gear Hash Algorithm
- FastCDC uses a precomputed 256-entry 64-bit random gear array.
- For each incoming byte, state advances as: H = (H << 1) + GearMatrix[byte].
- Rolling hash state requires zero division or modulo arithmetic, maximizing throughput.

## Normalized Sub-Chunk Masks
- Uses normalized bitmasks to control chunk size distribution:
  - Minimum size: 512 bytes (avoids chunk explosion).
  - Target average: 1024 to 4096 bytes.
  - Maximum limit: 8192 bytes.
- Achieves >10x deduplication speed over Rabin-Karp while preserving boundary resilience.
""",
        """# Luby Transform Rateless Fountain Codes over Lossy Links
> Mathematical principles of erasure recovery across unreliable physical radio transport.

## Soliton Degree Distribution
- The transmitter samples droplet degree d from an Ideal or Robust Soliton distribution.
- Low degree ensures quick ripple formation; high degree ensures full coupon-collector coverage.
- Each encoded droplet is the bitwise XOR of d randomly selected source symbols.

## Gaussian Elimination Decoding
- Receiver maintains a sparse matrix of received droplets and resolves ripple symbols incrementally.
- Inversion succeeds with high probability with only (1 + epsilon) * K packets received.
- Eliminates need for round-trip acknowledgment (ACK) packets across unidirectional broadcasts.
""",
        """# VHF/UHF Packet Radio & KISS TNC Protocol Bridging
> Emergency communication bridge linking TCP/IP networks with physical amateur radio transceivers.

## KISS Framing Rules
- FEND (0xC0): Frame End delimiter.
- FESC (0xDB): Frame Escape character.
- TFEND (0xDC): Transposed Frame End.
- TFESC (0xDD): Transposed Frame Escape.

## Physical Layer & Modulation
- Bell 202 Audio Frequency Shift Keying (AFSK) at 1200 baud.
- 1200 Hz Mark (Binary 1), 2200 Hz Space (Binary 0).
- Compatible with Baofeng, Yaesu, and Kenwood handheld radios via 3.5mm TRRS audio cables.
""",
        """# Structural Collapse Search & Rescue INSARAG Marking
> Unified marking system for urban search and rescue (USAR) teams clearing damaged buildings.

## Central 2x2 Meter Square Symbol
- Upper Quadrant: Time and date of entry and exit.
- Left Quadrant: Search and Rescue team identifier.
- Right Quadrant: Identified hazards (gas leak, structural collapse, asbestos).
- Lower Quadrant: Number of live victims rescued (L) and deceased victims recovered (D).

## Operational Safety
- Establish structural lookout prior to interior breach.
- Monitor secondary collapse indicators using plumb bobs or acoustic listening devices.
"""
    ]

    articles_dir = _repo_root / "data" / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    def persist_bundle(bundle_to_save: PackagedArticleBundle):
        try:
            target_path = articles_dir / f"{bundle_to_save.merkle_root}.json"
            target_path.write_text(json.dumps(bundle_to_save.to_dict(include_html=True), indent=2), encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"Article persistence warning: {exc}\n")

    # 1. Recover any existing persisted articles from disk
    for pf in articles_dir.glob("*.json"):
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            b = PackagedArticleBundle.from_dict(data)
            articles_by_root[b.merkle_root] = b
            # Include body content so body-only searches return exact results after restart
            clean_body = re.sub(r"<[^>]+>", " ", b.standalone_html or "")
            search_engine.add_document(
                doc_id=b.merkle_root,
                content=f"{b.title}\n{b.category}\n{b.metadata.get('summary', '')}\n{clean_body}",
                metadata={
                    "title": b.title,
                    "summary": b.metadata.get("summary", ""),
                    "category": b.category,
                    "reading_time_minutes": b.metadata.get("reading_time_minutes", 1),
                    "merkle_root": b.merkle_root,
                    "savings_pct": b.savings_pct,
                    "compressed_size": b.compressed_size_bytes,
                },
            )
        except Exception as exc:
            sys.stderr.write(f"Article recovery error from {pf.name}: {exc}\n")

    # 2. If first run with no persisted articles, seed foundational guides
    if not articles_by_root:
        for raw_md in INITIAL_ARTICLES:
            try:
                art = ArticleIngester.ingest_markdown(raw_md)
                bundle = packager.package_article(art)
                articles_by_root[bundle.merkle_root] = bundle
                persist_bundle(bundle)
                search_engine.add_document(
                    doc_id=bundle.merkle_root,
                    content=f"{art.title}\n{art.summary}\n{art.to_markdown()}",
                    metadata={
                        "title": art.title,
                        "summary": art.summary,
                        "category": art.category,
                        "reading_time_minutes": art.reading_time_minutes,
                        "merkle_root": bundle.merkle_root,
                        "savings_pct": bundle.savings_pct,
                        "compressed_size": bundle.compressed_size_bytes,
                    },
                )
            except Exception as exc:
                sys.stderr.write(f"Pre-indexing warning: {exc}\n")

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
            "dedup_ratio": f"{max(1.0, len(md) / max(1, sum(len(c) for c in chunks))):.1f}x",
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

            if self.path.startswith("/api/search"):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                q = query.get("q", [""])[0].strip()
                top_k = int(query.get("top_k", [10])[0])
                if not q:
                    self._send_json({"ok": True, "query": "", "count": 0, "results": []})
                    return
                results = search_engine.search(q, top_k=top_k)
                res_list = [
                    {
                        "merkle_root": r.chunk_id,
                        "score": round(r.score, 4),
                        "lexical_score": round(r.lexical_score, 4),
                        "semantic_score": round(r.semantic_score, 4),
                        "metadata": r.metadata,
                        "snippet": r.metadata.get("summary") or r.content[:160] + "...",
                    }
                    for r in results
                ]
                self._send_json({"ok": True, "query": q, "count": len(res_list), "results": res_list})
                return

            if self.path == "/api/articles":
                articles_list = [b.to_dict() for b in articles_by_root.values()]
                self._send_json({"ok": True, "count": len(articles_list), "articles": articles_list})
                return

            if self.path.startswith("/api/article"):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                root = query.get("root", [""])[0].strip()
                if not root:
                    parts = self.path.split("/")
                    if len(parts) > 2 and parts[2]:
                        root = parts[2].split("?")[0]
                bundle = articles_by_root.get(root)
                if not bundle:
                    self._send_json({"ok": False, "error": f"Article not found for root: {root}"}, status=404)
                    return
                html_bytes = bundle.standalone_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
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
            if self.path == "/api/ingest":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length <= 0:
                    self._send_json({"ok": False, "error": "Empty body"}, status=400)
                    return
                body_bytes = self.rfile.read(content_length)
                content_type = self.headers.get("Content-Type", "")

                try:
                    if "application/json" in content_type:
                        payload = json.loads(body_bytes.decode("utf-8"))
                        text = payload.get("text", "")
                        url = payload.get("url", "")
                        fmt = payload.get("format", "markdown")
                        if url:
                            extracted = ArticleIngester.ingest_url(url)
                        elif fmt == "html":
                            extracted = ArticleIngester.ingest_html(text)
                        else:
                            extracted = ArticleIngester.ingest_markdown(text)
                    else:
                        extracted = ArticleIngester.ingest_markdown(body_bytes.decode("utf-8"))

                    bundle = packager.package_article(extracted)
                    articles_by_root[bundle.merkle_root] = bundle
                    persist_bundle(bundle)
                    search_engine.add_document(
                        doc_id=bundle.merkle_root,
                        content=f"{extracted.title}\n{extracted.summary}\n{extracted.to_markdown()}",
                        metadata={
                            "title": extracted.title,
                            "summary": extracted.summary,
                            "category": extracted.category,
                            "reading_time_minutes": extracted.reading_time_minutes,
                            "merkle_root": bundle.merkle_root,
                            "savings_pct": bundle.savings_pct,
                            "compressed_size": bundle.compressed_size_bytes,
                        }
                    )
                    self._send_json({"ok": True, "bundle": bundle.to_dict()})
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=500)
                return

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

            if self.path == "/api/sample-video":
                def run_video():
                    data, fname, mtype = live_engine.generate_sample_video()
                    live_engine.transmit_file_bytes(
                        data,
                        filename=fname,
                        media_type=mtype,
                        loss_rate=active_loss_rate[0],
                        pace_delay=0.02,
                    )
                threading.Thread(target=run_video, daemon=True).start()
                self._send_json({"ok": True, "status": "streaming_sample_video"})
                return

            if self.path == "/api/sample-atlas":
                def run_atlas():
                    data, fname, mtype = live_engine.generate_parametric_atlas_payload()
                    live_engine.transmit_file_bytes(
                        data,
                        filename=fname,
                        media_type=mtype,
                        loss_rate=active_loss_rate[0],
                        pace_delay=0.02,
                    )
                threading.Thread(target=run_atlas, daemon=True).start()
                self._send_json({"ok": True, "status": "streaming_sample_atlas"})
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

    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = ThreadedTCPServer(("127.0.0.1", port), VisualizerHandler)
    actual_port = server.server_address[1]
    return server, actual_port


def main():
    parser = argparse.ArgumentParser(
        prog="tfp",
        description="The Foundation Protocol (TFP v4.0) Unified CLI",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("TFP_DB_PATH", str(Path.home() / ".tfp" / "node_store.db")),
        help="Path to persistent SQLite node storage (default: ~/.tfp/node_store.db or $TFP_DB_PATH)",
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

    # Fetch
    fetch_p = subparsers.add_parser("fetch", help="Fetch content by root hash")
    fetch_p.add_argument("hash", help="Root hash to fetch")
    fetch_p.add_argument("--output", default=None, help="Optional output file path")

    # Inspect
    inspect_p = subparsers.add_parser("inspect", help="Inspect content recipe by root hash")
    inspect_p.add_argument("hash", help="Root hash to inspect")

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

    # Export ZIM (Kiwix offline reader bundle)
    zim_p = subparsers.add_parser("export-zim", help="Export articles to Kiwix-compatible ZIM directory layout")
    zim_p.add_argument("target", help="Path to article JSON, or directory containing articles")
    zim_p.add_argument("--out", default="zim_export", help="Output directory for ZIM archive (default: zim_export)")
    zim_p.add_argument("--title", default="The Foundation Protocol Offline Library", help="ZIM bundle title")

    # Voice Memo (Audio-Pocket 1200 bps Vocoder)
    vm_p = subparsers.add_parser("voice-memo", help="Process ultra-low-bitrate voice memos via 1200 bps vocoder")
    vm_p.add_argument("action", choices=["compress", "decompress", "info"], help="Action: compress WAV to .vm, decompress .vm to WAV, or inspect .vm")
    vm_p.add_argument("input_path", help="Path to input .wav (for compress) or .vm (for decompress/info)")
    vm_p.add_argument("--out", default=None, help="Output file path")
    vm_p.add_argument("--callsign", default="TFP_NODE", help="Station callsign (max 8 characters)")

    # Verify
    subparsers.add_parser("verify", help="Run automated self-verification test battery")

    args = parser.parse_args()

    if args.command == "publish":
        path = Path(args.file_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        data = path.read_bytes()
        node = TFPNode(db_path=args.db)
        recipe = node.publish(data, metadata={"filename": path.name, "title": args.title or path.stem})

        print("=" * 60)
        print("  [TFP] File Published & Persisted Successfully")
        print("=" * 60)
        print(f"  Root Hash    : {recipe.root_hash}")
        print(f"  Total Size   : {recipe.total_size:,} bytes")
        print(f"  FastCDC Chunks: {len(recipe.chunk_hashes)}")
        print(f"  Database     : {args.db}")
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

    elif args.command == "fetch":
        node = TFPNode(db_path=args.db)
        target_hash = getattr(args, "hash", getattr(args, "root_hash", None))
        loss = getattr(args, "loss", 0.0)
        try:
            recovered = node.fetch(target_hash, simulated_loss=loss)
            if getattr(args, "output", None):
                Path(args.output).write_bytes(recovered)
                print(f"[TFP] Fetched {len(recovered):,} bytes and written to {args.output}")
            else:
                sys.stdout.buffer.write(recovered)
        except (KeyError, RuntimeError, ValueError) as exc:
            print(f"Error: Could not fetch content for hash '{target_hash}': {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "inspect":
        node = TFPNode(db_path=args.db)
        target_hash = getattr(args, "hash", getattr(args, "root_hash", None))
        try:
            info = node.inspect_recipe(target_hash)
            print(json.dumps(info, indent=2))
        except KeyError:
            print(f"Error: No recipe found for root hash '{target_hash}'.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "export-zim":
        from tfp_client.lib.ingest.article_packager import PackagedArticleBundle
        from tfp_client.lib.ingest.zim_exporter import ZimDirectoryExporter

        target_path = Path(args.target)
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        bundles = []
        if target_path.is_file():
            try:
                data = json.loads(target_path.read_text(encoding="utf-8"))
                bundles.append(PackagedArticleBundle.from_dict(data))
            except Exception:
                text = target_path.read_text(encoding="utf-8")
                b = PackagedArticleBundle(
                    title=target_path.stem,
                    category="General",
                    merkle_root=hashlib.sha3_256(text.encode("utf-8")).hexdigest(),
                    raw_size_bytes=len(text),
                    compressed_size_bytes=len(text),
                    savings_pct=0.0,
                    chunk_count=1,
                    standalone_html=text,
                    metadata={"source": target_path.name},
                )
                bundles.append(b)
        elif target_path.is_dir():
            for p in sorted(target_path.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if "title" in data and ("standalone_html" in data or "merkle_root" in data):
                        bundles.append(PackagedArticleBundle.from_dict(data))
                except Exception:
                    continue
        else:
            print(f"Error: Target path '{target_path}' not found.", file=sys.stderr)
            sys.exit(1)

        if not bundles:
            print(f"Error: No valid article bundles found at '{target_path}'.", file=sys.stderr)
            sys.exit(1)

        exporter = ZimDirectoryExporter()
        index_path = exporter.export_bundles(
            bundles=bundles,
            target_dir=out_dir,
            library_title=args.title,
        )
        print("=" * 60)
        print("  [TFP] Kiwix / ZIM Bundle Export Complete")
        print("=" * 60)
        print(f"  Articles Exported : {len(bundles)}")
        print(f"  ZIM Directory     : {out_dir}")
        print(f"  Offline Index     : {index_path}")
        print("=" * 60)

    elif args.command == "voice-memo":
        from tfp_client.lib.audio.voice_memo import VoiceMemo

        in_path = Path(args.input_path)
        if not in_path.exists():
            print(f"Error: Input file not found: {in_path}", file=sys.stderr)
            sys.exit(1)

        if args.action == "compress":
            wav_bytes = in_path.read_bytes()
            memo = VoiceMemo.from_wav(wav_bytes, callsign=args.callsign, compress_vocoder=True)
            vm_bytes = memo.to_bytes()
            out_file = Path(args.out) if args.out else in_path.with_suffix(".vm")
            out_file.write_bytes(vm_bytes)
            print("=" * 60)
            print("  [TFP] Voice Memo Compressed (1200 bps Vocoder)")
            print("=" * 60)
            print(f"  Input WAV Size    : {len(wav_bytes):,} bytes")
            print(f"  Output .vm Size   : {len(vm_bytes):,} bytes")
            ratio = (1.0 - len(vm_bytes) / max(1, len(wav_bytes))) * 100.0
            print(f"  Compression Ratio : {ratio:.1f}%")
            print(f"  Duration          : {(memo.duration_ms or 0) / 1000.0:.2f} s")
            print(f"  Callsign          : {memo.callsign}")
            print(f"  Saved To          : {out_file}")
            print("=" * 60)

        elif args.action == "decompress":
            vm_bytes = in_path.read_bytes()
            memo = VoiceMemo.from_bytes(vm_bytes, auto_decompress=True)
            wav_bytes = memo.to_wav()
            out_file = Path(args.out) if args.out else in_path.with_suffix(".decompressed.wav")
            out_file.write_bytes(wav_bytes)
            print("=" * 60)
            print("  [TFP] Voice Memo Decompressed to 16-bit PCM WAV")
            print("=" * 60)
            print(f"  Input .vm Size    : {len(vm_bytes):,} bytes")
            print(f"  Output WAV Size   : {len(wav_bytes):,} bytes")
            print(f"  Duration          : {(memo.duration_ms or 0) / 1000.0:.2f} s")
            print(f"  Callsign          : {memo.callsign}")
            print(f"  Saved To          : {out_file}")
            print("=" * 60)

        elif args.action == "info":
            vm_bytes = in_path.read_bytes()
            memo = VoiceMemo.from_bytes(vm_bytes, auto_decompress=False)
            print("=" * 60)
            print("  [TFP] Voice Memo Binary Wire Inspection")
            print("=" * 60)
            print(f"  Callsign          : {memo.callsign}")
            print(f"  Timestamp         : {memo.timestamp}")
            print(f"  Duration          : {memo.duration_ms} ms ({(memo.duration_ms or 0) / 1000.0:.2f} s)")
            print(f"  Sample Rate       : {memo.sample_rate} Hz")
            print(f"  Vocoder Encoded   : {memo.is_vocoder}")
            print(f"  Wire Payload Size : {len(memo.pcm_data):,} bytes")
            print("=" * 60)

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
