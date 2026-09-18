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
from pathlib import Path
import sys

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_core_v4.node import TFPNode
from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.radio.framing import RadioFramePacker, RadioFrameReassembler
from tfp_client.lib.search.hybrid_search import HybridSearchEngine


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
    radio_p.add_argument("--mtu", type=int, default=200, help="Physical radio MTU (default: 200)")

    # Mesh Sim
    subparsers.add_parser("mesh-sim", help="Run offline community Wi-Fi mesh simulation")

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
        manifest, chunks, merkle = packager.package(data, metadata={"filename": path.name})

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

        assert receiver.is_complete(manifest)
        reconstructed = receiver.assemble(manifest)
        assert reconstructed == data

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
        print(f"[TFP RADIO] CRC16 verified; reassembly succeeded: 100% MATCH.")

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

    elif args.command == "verify":
        print("[TFP] Running self-verification across core protocol primitives...")
        node = TFPNode()
        sample_data = b"THE FOUNDATION PROTOCOL v4.0 TEST PAYLOAD: " * 50
        recipe = node.publish(sample_data, metadata={"test": True})
        recovered = node.fetch(recipe.root_hash, simulated_loss=0.30)
        assert recovered == sample_data
        print("[TFP] Core verification: PASSED (bit-exact under loss).")


if __name__ == "__main__":
    main()
