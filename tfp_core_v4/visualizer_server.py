# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Visualizer Web Dashboard Server for The Foundation Protocol.

Provides HTTP and Server-Sent Events (SSE) endpoints for real-time monitoring of
Fountain coding, transmission loss simulation, article ingestion, and hybrid search.
Extracted from tfp_core_v4.cli to maintain strict separation of concerns.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import queue
import re
import socketserver
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any

log = logging.getLogger("tfp.visualizer")

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.ingest.article_ingester import ArticleIngester
from tfp_client.lib.ingest.article_packager import ArticlePackager, PackagedArticleBundle
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.live_streamer import LiveTransmissionEngine
from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.telemetry_events import TelemetryEventBus
from tfp_client.lib.media.template_engine import TemplateParser
from tfp_client.lib.search.hybrid_search import HybridSearchEngine


def get_static_assets_dir() -> Path:
    """
    Resolve static web assets directory across:
    1. importlib.resources for installed wheel/package distributions
    2. Local checkout paths (_repo_root / "tfp-foundation-protocol" / "tfp_demo" / "static")
    3. Direct parent search fallback across sys.path
    """
    try:
        import importlib.resources as pkg_resources

        res = pkg_resources.files("tfp_demo").joinpath("static")
        p = Path(str(res))
        if p.is_dir() and (p / "visualizer.html").exists():
            return p
    except Exception as exc:
        log.debug(f"importlib.resources asset lookup skipped: {exc}")

    candidates = [
        _tfp_root / "tfp_demo" / "static",
        _repo_root / "tfp-foundation-protocol" / "tfp_demo" / "static",
        _repo_root / "tfp_demo" / "static",
        Path(__file__).resolve().parent.parent / "tfp-foundation-protocol" / "tfp_demo" / "static",
        Path.cwd() / "tfp-foundation-protocol" / "tfp_demo" / "static",
    ]
    for c in candidates:
        if c.is_dir() and (c / "visualizer.html").exists():
            return c

    for sp in sys.path:
        c1 = Path(sp) / "tfp_demo" / "static"
        if c1.is_dir() and (c1 / "visualizer.html").exists():
            return c1
        c2 = Path(sp) / "tfp-foundation-protocol" / "tfp_demo" / "static"
        if c2.is_dir() and (c2 / "visualizer.html").exists():
            return c2

    raise FileNotFoundError("Could not locate tfp_demo static assets directory.")


def create_visualizer_server(port: int = 8080, *, data_dir: Path | str | None = None) -> tuple[Any, int]:
    """Create the dashboard, storing articles outside the installed code.

    Storage defaults to ~/.tfp/visualizer; an explicit data_dir takes precedence
    over TFP_VISUALIZER_DATA_DIR. Existing archives can be selected with either.
    """
    static_dir = get_static_assets_dir()
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

    if data_dir is None:
        data_dir = os.environ.get("TFP_VISUALIZER_DATA_DIR") or Path.home() / ".tfp" / "visualizer"
    articles_dir = Path(data_dir).expanduser().resolve() / "articles"
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
                    except (ValueError, IndexError, KeyError) as exc:
                        log.debug(f"Invalid rate parameter ignored in /api/set-loss: {exc}")
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
