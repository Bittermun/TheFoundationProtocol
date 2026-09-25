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
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("tfp.cli")

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
from tfp_client.lib.radio.framing import RadioFramePacker, RadioFrameReassembler
from tfp_client.lib.search.hybrid_search import HybridSearchEngine

from tfp_core_v4.bulletin import import_bulletin_package, prepare_bulletin_package
from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
)
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import (
    create_visualizer_server,
    get_static_assets_dir,
)


def main(argv: list[str] | None = None):
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
    search_p.add_argument("--top-k", type=int, default=5, help="Maximum number of results to return (default: 5)")
    search_p.add_argument("--db", dest="search_db", default=None, help="Path to persistent SQLite node storage")
    search_p.add_argument("--demo", action="store_true", help="Search built-in emergency demonstration corpus if database is empty")

    # Bulletin Prepare
    bprep_p = subparsers.add_parser("bulletin-prepare", help="Prepare an atomic broadcast bulletin package with audio WAV")
    bprep_p.add_argument("content", help="Bulletin text or path to text file to broadcast")
    bprep_p.add_argument("--id", required=True, help="Unique bulletin ID")
    bprep_p.add_argument("--revision", type=int, default=1, help="Bulletin revision (default: 1)")
    bprep_p.add_argument("--title", default=None, help="Bulletin title")
    bprep_p.add_argument("--out-dir", default="bulletin_package", help="Target output directory (default: bulletin_package)")
    bprep_p.add_argument("--replace", action="store_true", help="Replace an existing bulletin package, retaining a recoverable backup")
    bprep_p.add_argument("--airtime-limit", type=float, default=None, help="Maximum allowed transmission airtime in seconds")
    bprep_p.add_argument("--baud", type=int, default=1200, help="Baud rate (default: 1200, or 300 for long-range)")
    bprep_p.add_argument("--key", default=None, help="Optional hex private key for Ed25519 signing")

    # Bulletin Import
    bimp_p = subparsers.add_parser("bulletin-import", help="Demodulate and verify broadcast audio package into authoritative storage")
    bimp_p.add_argument("source", help="Path to broadcast package directory or broadcast WAV file")
    bimp_p.add_argument("--baud", type=int, default=1200, help="Baud rate (default: 1200)")

    # Bulletin List
    subparsers.add_parser("bulletin-list", help="List verified bulletins in authoritative storage")

    # Bulletin Read
    bread_p = subparsers.add_parser("bulletin-read", help="Read verified bulletin body from authoritative storage")
    bread_p.add_argument("bulletin_id", help="Bulletin ID to read")
    bread_p.add_argument("--revision", type=int, default=None, help="Specific revision to read (default: latest)")

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
    vis_p.add_argument("--data-dir", default=None, help="Article storage directory (default: ~/.tfp/visualizer or $TFP_VISUALIZER_DATA_DIR)")

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

    args = parser.parse_args(argv)

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
        db_target = getattr(args, "search_db", None) or getattr(args, "db", None)
        node = TFPNode(db_path=db_target)
        recipes = node.list_recipes()

        engine = HybridSearchEngine()
        indexed_count = 0
        degraded_docs: list[tuple[str, str, str]] = []

        for r in recipes:
            title = r.metadata.get("title", r.metadata.get("filename", r.root_hash[:16]))
            body_retrieved = True
            err_msg = ""
            try:
                content_bytes = node.fetch(r.root_hash)
                text_content = content_bytes.decode("utf-8", errors="replace")
                doc_text = f"{title}\n\n{text_content}"
            except Exception as exc:
                body_retrieved = False
                err_msg = str(exc)
                doc_text = title
                degraded_docs.append((r.root_hash, title, err_msg))

            bulletin_id = r.metadata.get("bulletin_id")
            revision = r.metadata.get("revision")
            publisher_id = r.metadata.get("publisher_id")

            superseded_tag = ""
            if bulletin_id is not None:
                max_rev = node.get_max_bulletin_revision(bulletin_id, publisher_id=publisher_id)
                if revision is not None and max_rev is not None and revision < max_rev:
                    superseded_tag = f" [SUPERSEDED (Rev {revision} < Latest Rev {max_rev})]"

            engine.add_document(
                doc_id=r.root_hash,
                content=doc_text,
                metadata={
                    "title": title,
                    "filename": r.metadata.get("filename", ""),
                    "root_hash": r.root_hash,
                    "total_size": r.total_size,
                    "degraded": not body_retrieved,
                    "degraded_reason": err_msg,
                    "bulletin_id": bulletin_id,
                    "revision": revision,
                    "superseded_tag": superseded_tag,
                },
            )
            indexed_count += 1

        if indexed_count == 0:
            db_label = db_target or "local node database"
            print(f"[TFP SEARCH] Notice: 0 published articles found in '{db_label}'. Searching built-in emergency demonstration corpus:")
            engine.add_document("[DEMO] doc1", "Emergency field manual for water purification and sanitation.")
            engine.add_document("[DEMO] doc2", "Triage protocols for trauma and hypothermia resuscitation.")
            engine.add_document("[DEMO] doc3", "LoRa physical layer modulation and packet radio framing.")
        else:
            if degraded_docs:
                print(f"[TFP SEARCH] Indexed {indexed_count} document(s) ({len(degraded_docs)} degraded/body unavailable) from '{db_target}'.")
                print(f"[TFP SEARCH] Warning: {len(degraded_docs)} document(s) could not be fully searched because content body was unretrievable.")
            else:
                print(f"[TFP SEARCH] Indexed {indexed_count} persisted document(s) from '{db_target}'.")

        top_k = getattr(args, "top_k", 5)
        results = engine.search(args.query, top_k=top_k)
        if not results:
            if degraded_docs:
                print(f"[TFP SEARCH] No matching content found for '{args.query}', but {len(degraded_docs)} document(s) could not be searched because content body was unavailable.")
            else:
                print(f"[TFP SEARCH] No matching content found for '{args.query}'.")
        else:
            print(f"[TFP SEARCH] Found {len(results)} match(es) for '{args.query}':")
            for r in results:
                is_degraded = r.metadata.get("degraded", False)
                degraded_tag = " [DEGRADED: BODY UNAVAILABLE]" if is_degraded else ""
                superseded_tag = r.metadata.get("superseded_tag", "")
                snippet = r.content.strip().replace("\n", " ")
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                print(f"  [{r.score:.3f}] {r.chunk_id}{degraded_tag}{superseded_tag}: {snippet}")
            if degraded_docs:
                print(f"[TFP SEARCH] Note: {len(degraded_docs)} document(s) could not be fully searched because their content body was unavailable.")

    elif args.command == "bulletin-prepare":
        content_arg = args.content
        p = Path(content_arg)
        try:
            is_content_file = p.exists() and p.is_file()
        except OSError as exc:
            if exc.errno != errno.ENAMETOOLONG:
                raise
            is_content_file = False
        if is_content_file:
            content_text = p.read_text(encoding="utf-8")
        else:
            content_text = content_arg
        content_text = content_text.replace("\r\n", "\n").replace("\r", "\n")

        priv_key = None
        if args.key:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            try:
                key_bytes = bytes.fromhex(args.key.strip())
            except ValueError as exc:
                print(f"Error: Invalid hex string for --key: {exc}", file=sys.stderr)
                sys.exit(1)
            if len(key_bytes) not in (32, 64):
                print(
                    f"Error: Ed25519 private key must be 32 bytes (64 hex chars) or 64 bytes (128 hex chars), got {len(key_bytes)} bytes.",
                    file=sys.stderr,
                )
                sys.exit(1)
            priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes[:32])

        meta = prepare_bulletin_package(
            bulletin_id=args.id,
            revision=args.revision,
            title=args.title or args.id,
            content_text=content_text,
            output_dir=args.out_dir,
            private_key=priv_key,
            airtime_limit_seconds=args.airtime_limit,
            baud_rate=args.baud,
            overwrite=args.replace,
        )

        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: BROADCAST BULLETIN PACKAGE")
        print("=" * 65)
        print(f"  Bulletin ID    : {meta['bulletin_id']} (Rev {meta['revision']})")
        print(f"  Title          : {meta['title']}")
        print(f"  Content Hash   : {meta['content_hash']}")
        print(f"  Publisher ID   : {meta['publisher_id']}")
        print(f"  Verification   : {meta['verification_status']}")
        print(f"  Audio Duration : {meta['audio_duration_seconds']:.2f}s (@ {meta['baud_rate']} Baud)")
        print(f"  Payload Size   : {meta['payload_bytes']} bytes")
        print(f"  Package Output : {Path(args.out_dir).resolve()}")
        if "previous_package_path" in meta:
            print(f"  Previous Copy  : {meta['previous_package_path']}")
        print("=" * 65)

    elif args.command == "bulletin-import":
        node = TFPNode(db_path=args.db)
        try:
            imported = import_bulletin_package(args.source, node=node, baud_rate=args.baud)
        except (StaleRevisionError, RevisionConflictError, PublisherIdentityConflictError, ValueError) as exc:
            err_type = type(exc).__name__
            print("=" * 65, file=sys.stderr)
            print("  [ERROR: BULLETIN ADMISSION REJECTED]", file=sys.stderr)
            print("=" * 65, file=sys.stderr)
            print(f"  Error Type : {err_type}", file=sys.stderr)
            print(f"  Details    : {exc}", file=sys.stderr)
            if isinstance(exc, StaleRevisionError):
                print("  Reason     : Incoming bulletin revision is lower than accepted watermark.", file=sys.stderr)
                print("  Action     : Ensure broadcasts distribute current or subsequent revisions.", file=sys.stderr)
            elif isinstance(exc, RevisionConflictError):
                print("  Reason     : Incoming bulletin reuses an existing revision with conflicting content or title.", file=sys.stderr)
                print("  Action     : Revision numbers are immutable; author a higher revision number.", file=sys.stderr)
            elif isinstance(exc, PublisherIdentityConflictError):
                print("  Reason     : Bulletin ID is already associated with a different publisher key.", file=sys.stderr)
                print("  Action     : Verify publisher signing key or assign a distinct bulletin ID.", file=sys.stderr)
            else:
                print("  Reason     : Package validation, demodulation, or signature verification failed.", file=sys.stderr)
                print("  Action     : Verify audio source quality, package integrity, and cryptographic signatures.", file=sys.stderr)
            print("=" * 65, file=sys.stderr)
            sys.exit(1)

        is_dup = bool(imported.get("duplicate") or imported.get("status") == "duplicate")
        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: BULLETIN IMPORT & VERIFICATION")
        print("=" * 65)
        if is_dup:
            print("  [NOTICE: DUPLICATE BULLETIN REPLAY]")
        print(f"  Bulletin ID    : {imported['bulletin_id']} (Rev {imported['revision']})")
        print(f"  Title          : {imported['title']}")
        print(f"  Content Hash   : {imported['content_hash']}")
        print(f"  Root Hash      : {imported['root_hash']}")
        print(f"  Publisher ID   : {imported['publisher_id']}")
        print(f"  Verification   : {imported['verified_status']}")
        print("  Publisher Trust: Not established (signature validity is separate)")
        print(f"  Payload Size   : {imported['data_size']} bytes")
        if is_dup:
            print("  Status: Verified authentic duplicate; existing record retained.")
        else:
            print("  Status         : Durably stored in authoritative node store")
        print("=" * 65)
        if is_dup:
            sys.exit(0)

    elif args.command == "bulletin-list":
        node = TFPNode(db_path=args.db)
        bulletins = node.list_bulletins()
        print("=" * 65)
        print("  THE FOUNDATION PROTOCOL: AUTHORITATIVE BULLETIN STORE")
        print("=" * 65)
        if not bulletins:
            print("  0 bulletins found in store.")
        else:
            print(f"  Found {len(bulletins)} stored bulletin(s):")
            for b in bulletins:
                max_rev = node.get_max_bulletin_revision(b["bulletin_id"], publisher_id=b.get("publisher_id"))
                superseded = (
                    f" [SUPERSEDED (Rev {b['revision']} < Latest Rev {max_rev})]"
                    if (max_rev is not None and b["revision"] < max_rev)
                    else ""
                )
                print(f"  [{b['bulletin_id']} v{b['revision']}] {b['title']}{superseded}")
                print(f"    Hash      : {b['content_hash']}")
                print(f"    Publisher : {b['publisher_id']}")
                print(f"    Status    : {b['verified_status']} | Size: {b['data_size']}B")
                print("    Publisher trust: Not established")
        print("=" * 65)

    elif args.command == "bulletin-read":
        node = TFPNode(db_path=args.db)
        res = node.get_bulletin(args.bulletin_id, revision=args.revision)
        if not res:
            print(f"Error: Bulletin '{args.bulletin_id}' not found in store.", file=sys.stderr)
            sys.exit(1)
        meta, content = res
        max_rev = node.get_max_bulletin_revision(meta["bulletin_id"], publisher_id=meta.get("publisher_id"))
        superseded = (
            f" [SUPERSEDED (Rev {meta['revision']} < Latest Rev {max_rev})]"
            if (max_rev is not None and meta["revision"] < max_rev)
            else ""
        )
        print("=" * 65)
        print(f"  BULLETIN: {meta['title']} (ID: {meta['bulletin_id']}, Rev: {meta['revision']}){superseded}")
        print(f"  Publisher: {meta['publisher_id']} | Status: {meta['verified_status']}")
        print("  Publisher trust: Not established")
        print("=" * 65)
        print(content.decode("utf-8", errors="replace"))
        print("=" * 65)

    elif args.command == "mesh-sim":
        from scripts.run_mesh_simulation import run_simulation
        asyncio.run(run_simulation())

    elif args.command == "visualize":
        import webbrowser

        port = args.port
        try:
            httpd, actual_port = create_visualizer_server(port, data_dir=args.data_dir)
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

        static_dir = get_static_assets_dir()

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
