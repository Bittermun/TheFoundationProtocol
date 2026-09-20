#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unified End-to-End Offline Delivery Lifecycle Verification.

Executes the complete developing-world knowledge transmission mission:
1. Ingest: Article + Voice Memo -> FastCDC Content-Defined Chunks & Merkle Roots.
2. Transport: Fountain droplet encoding + Simulated 30% loss over packet channel.
3. Reception: Receiver validation, Gaussian elimination / systematic assembly, SHA-3 integrity.
4. Persistence: Write assembled articles and metadata to SQLite store.
5. Cold Reboot: Terminate in-memory session; re-open database from disk in a fresh process context.
6. Search: Query restored database using BM25 text retrieval.
7. Kiwix / ZIM Export: Package articles into standard Kiwix offline directory layout with index.html.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.audio.voice_memo import VoiceMemo
from tfp_client.lib.ingest.article_packager import ArticlePackager, PackagedArticleBundle
from tfp_client.lib.ingest.zim_exporter import ZimDirectoryExporter
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_core_v4.cdc import ContentDefinedChunker


ARTICLE_TITLE = "Severe Malaria Rapid Triage Protocol"
ARTICLE_CONTENT = """
# Severe Malaria Field Resuscitation & Treatment
## Immediate Assessment
Assess ABCs (Airway, Breathing, Circulation). Check blood glucose immediately (hypoglycemia risk).
## Artesunate Administration
- Dose: 2.4 mg/kg IV or IM on admission (time 0).
- Repeat at 12 hours and 24 hours, then once daily until oral therapy can be tolerated.
- Minimum 3 doses even if patient improves rapidly.
## Warning Signs
Coma (cerebral malaria), acidotic breathing, repeated seizures, spontaneous bleeding, pulmonary edema.
"""

VOICE_TEXT = "REQUEST_URGENT_ARTESUNATE_50_VIALS_CLINIC_NORTH"


def run_lifecycle(db_path: Path, zim_out: Path, loss_rate: float = 0.30) -> dict[str, bool]:
    results = {}
    print("=" * 65)
    print("  THE FOUNDATION PROTOCOL: OFFLINE DELIVERY LIFECYCLE VERIFIER")
    print("=" * 65)
    print(f"  Target DB Path : {db_path}")
    print(f"  ZIM Directory  : {zim_out}")
    print(f"  Channel Loss   : {loss_rate * 100:.1f}%")
    print("=" * 65)

    # ------------------------------------------------------------------
    # Stage 1: Ingest & FastCDC Chunking
    # ------------------------------------------------------------------
    print("\n[Stage 1: Ingest & FastCDC Chunking]")
    packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=2048)
    article_bytes = ARTICLE_CONTENT.encode("utf-8")
    manifest, chunks, merkle_tree = packager.package(
        article_bytes,
        metadata={"title": ARTICLE_TITLE, "category": "medical"}
    )
    print(f"  Article Encoded    : {len(article_bytes)} bytes")
    print(f"  FastCDC Chunks     : {manifest.chunk_count}")
    print(f"  Merkle Root        : {manifest.merkle_root}")
    results["stage_1_ingest"] = manifest.chunk_count > 0

    # ------------------------------------------------------------------
    # Stage 2: Fountain Encoding & Lossy Airgap Transmission
    # ------------------------------------------------------------------
    print("\n[Stage 2: Fountain Stream & Simulated 30% Channel Loss]")
    streamer = FountainStreamer(symbol_size=256)
    # Generate real wire datagrams including manifest packets (FM) and droplet packets (FD)
    raw_wire_packets = list(streamer.stream_manifest_wire_packets(
        manifest=manifest,
        chunks=chunks,
        redundancy=3.0,
        repeat_manifest=5,
    ))

    # Simulate random channel loss
    import random
    rng = random.Random(9999)
    surviving_wire_packets = [pkt for pkt in raw_wire_packets if rng.random() >= loss_rate]
    actual_loss = (1.0 - len(surviving_wire_packets) / len(raw_wire_packets)) * 100.0
    print(f"  Wire Packets Sent   : {len(raw_wire_packets)}")
    print(f"  Wire Packets Recv   : {len(surviving_wire_packets)} (loss: {actual_loss:.1f}%)")
    results["stage_2_transmission"] = len(surviving_wire_packets) > 0

    # ------------------------------------------------------------------
    # Stage 3: Reception, Admission & Assembly
    # ------------------------------------------------------------------
    print("\n[Stage 3: Reception & SHA-3 Integrity Assembly]")
    receiver = FountainStreamReceiver(symbol_size=256)
    # Ingest raw wire bytes directly through receiver.ingest_bytes
    # This authentically parses manifest announcements (FM) and fountain droplets (FD)
    for wire_pkt in surviving_wire_packets:
        receiver.ingest_bytes(wire_pkt)

    assert receiver.latest_manifest is not None, "Receiver failed to receive wire manifest packet"
    assert receiver.is_complete(receiver.latest_manifest), "Receiver failed to collect sufficient fountain rank"
    reconstructed_bytes = receiver.assemble(receiver.latest_manifest)
    assert reconstructed_bytes == article_bytes, "Reconstructed bytes do not match original article"
    print(f"  Assembly Status    : 100% Bit-Exact Match ({len(reconstructed_bytes)} bytes)")
    results["stage_3_reception"] = True

    # ------------------------------------------------------------------
    # Stage 4: Persistence of Reconstructed Content to SQLite
    # ------------------------------------------------------------------
    print("\n[Stage 4: Persistence to SQLite]")
    # Persist the actual reconstructed payload, NOT the input constant
    reconstructed_text = reconstructed_bytes.decode("utf-8")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            root_hash TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            content TEXT,
            created_at REAL
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO articles VALUES (?, ?, ?, ?, ?)",
        (receiver.latest_manifest.merkle_root, ARTICLE_TITLE, "medical", reconstructed_text, time.time())
    )
    conn.commit()
    conn.close()
    print("  Article Committed  : Reconstructed text written to SQLite database successfully")
    results["stage_4_persistence"] = True

    # ------------------------------------------------------------------
    # Stage 5: Cold Reboot & Subprocess Boundary Simulation
    # ------------------------------------------------------------------
    print("\n[Stage 5: Cold Reboot & Subprocess Boundary Simulation]")
    import subprocess
    reboot_probe_cmd = [
        sys.executable,
        "-c",
        f"""
import sqlite3, sys
conn = sqlite3.connect(r"{db_path}")
cur = conn.cursor()
cur.execute("SELECT root_hash, title, length(content) FROM articles")
row = cur.fetchone()
conn.close()
if not row:
    sys.exit(1)
print(f"SUBPROCESS_REBOOT_OK:{{row[0]}}|{{row[1]}}|{{row[2]}}")
"""
    ]
    proc = subprocess.run(reboot_probe_cmd, capture_output=True, text=True, check=True)
    print(f"  Subprocess Output  : {proc.stdout.strip()}")
    results["stage_5_reboot"] = "SUBPROCESS_REBOOT_OK" in proc.stdout

    # ------------------------------------------------------------------
    # Stage 6: Database Recovery & Hybrid BM25 Search
    # ------------------------------------------------------------------
    print("\n[Stage 6: Restored Database Query & Hybrid BM25 Search]")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT root_hash, title, content FROM articles")
    rows = cursor.fetchall()
    conn.close()

    assert rows, "Article not found in restored database"
    found_root, found_title, found_content = rows[0]

    from tfp_client.lib.search.hybrid_search import HybridSearchEngine
    search_engine = HybridSearchEngine()
    for r_root, r_title, r_content in rows:
        search_engine.add_document(doc_id=r_root, content=f"{r_title}\n{r_content}", metadata={"title": r_title})

    search_hits = search_engine.search("Artesunate", top_k=5)
    assert len(search_hits) > 0, "BM25 hybrid search returned 0 results"
    top_hit = search_hits[0]
    print(f"  Restored Article   : '{found_title}'")
    print(f"  Root Hash Match    : {found_root}")
    print(f"  BM25 Search Score  : {top_hit.score:.4f} (hit on '{top_hit.metadata.get('title')}')")
    results["stage_6_search"] = "Artesunate" in top_hit.content

    # ------------------------------------------------------------------
    # Stage 7: Kiwix / ZIM Export & Verification
    # ------------------------------------------------------------------
    print("\n[Stage 7: Kiwix / ZIM Export]")
    bundle = PackagedArticleBundle(
        title=found_title,
        category="medical",
        merkle_root=found_root,
        raw_size_bytes=len(found_content.encode("utf-8")),
        compressed_size_bytes=len(found_content.encode("utf-8")),
        savings_pct=0.0,
        chunk_count=1,
        standalone_html=f"<!DOCTYPE html><html><head><title>{found_title}</title></head><body><pre>{found_content}</pre></body></html>",
        metadata={"source": "airgap_broadcast"},
    )
    exporter = ZimDirectoryExporter()
    index_file = exporter.export_bundles([bundle], target_dir=zim_out, library_title="Emergency Medical Field Library")

    assert (zim_out / "index.html").exists()
    assert (zim_out / "manifest.json").exists()
    assert len(list((zim_out / "A").glob("*.html"))) == 1
    print(f"  Export Complete    : {index_file}")
    results["stage_7_zim_export"] = True

    print("\n" + "=" * 65)
    print("  ALL 7 STAGES OF THE OFFLINE DELIVERY LIFECYCLE: PASSED")
    print("=" * 65)
    return results


def main():
    parser = argparse.ArgumentParser(description="TFP Offline Delivery Lifecycle Verifier")
    parser.add_argument("--db-path", default=None, help="Optional persistent SQLite path")
    parser.add_argument("--zim-out", default=None, help="Optional ZIM output directory")
    parser.add_argument("--loss", type=float, default=0.30, help="Channel loss rate (default: 0.30)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_path = Path(tmp_dir)
        db_path = Path(args.db_path) if args.db_path else temp_path / "lifecycle_pib.db"
        zim_out = Path(args.zim_out) if args.zim_out else temp_path / "zim_library"

        results = run_lifecycle(db_path, zim_out, loss_rate=args.loss)
        if not all(results.values()):
            sys.exit(1)


if __name__ == "__main__":
    main()
