#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Shared Disposable Verification Lab & Protocol Experiment Runner.

Executes protocol resilience experiments in ephemeral, isolated sandboxes:
1. e2e_fountain_loss: Sockets & dropping proxy over OS loopback with configurable loss.
2. consecutive_streams: Sequential transfers verifying zero state contamination.
3. interleaved_multiplex: Concurrent streams multiplexed over a single channel.
4. daemon_reboot_persistence: Ephemeral cold storage write, process kill, and offline restart.
5. acoustic_afsk_airgap: Bell 202 AFSK audio synthesis, channel noise, and AGC demodulation.

Usage:
    python scripts/run_experiment.py --scenario all
    python scripts/run_experiment.py --scenario e2e_fountain_loss --loss 0.25
    python scripts/run_experiment.py --scenario daemon_reboot_persistence --json
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import random
import shutil
import socket
import struct
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
import wave

# Ensure repository roots are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TFP_ROOT = REPO_ROOT / "tfp-foundation-protocol"
if str(TFP_ROOT) not in sys.path:
    sys.path.insert(0, str(TFP_ROOT))

from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.voice_memo import VoiceMemo
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator
from tfp_client.lib.search.hybrid_search import HybridSearchEngine


class DroppingProxyProtocol(asyncio.DatagramProtocol):
    """Intermediary proxy protocol that intercepts UDP datagrams and drops a recorded percentage."""

    def __init__(self, target_port: int, drop_rate: float = 0.20, seed: int = 42):
        self.target_port = target_port
        self.drop_rate = drop_rate
        self.packets_received = 0
        self.packets_forwarded = 0
        self.packets_dropped = 0
        self.transport = None
        self._rng = random.Random(seed)

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        self.packets_received += 1
        if self._rng.random() < self.drop_rate:
            self.packets_dropped += 1
        else:
            self.packets_forwarded += 1
            if self.transport:
                self.transport.sendto(data, ("127.0.0.1", self.target_port))


async def run_e2e_fountain_loss_experiment(loss_rate: float = 0.20, seed: int = 42) -> Dict[str, Any]:
    """Runs end-to-end fountain stream over OS UDP loopback with a dropping proxy."""
    loop = asyncio.get_running_loop()
    start_time = time.perf_counter()

    payload = (
        b"DISPOSABLE_LAB_EXPERIMENT_01: EPHEMERAL MESH AIRGAP DISPATCH PROTOCOL. "
        b"Triage clinic established at coordinates 34.0522 N, 118.2437 W. "
        b"Fountain coding ensures reliable delivery despite 20-30% radio packet loss. "
    ) * 20  # ~4 KB
    expected_hash = hashlib.sha3_256(payload).hexdigest()

    packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=2048)
    manifest, chunks, _ = packager.package(payload)

    secret = b"disposable-lab-secret-key-32b-!"
    streamer = FountainStreamer(symbol_size=256, secret_key=secret)
    # Erasure code physics: To survive loss rate L, (1 + R) * (1 - L) must exceed 1.0 + margin
    calc_redundancy = max(1.5, loss_rate * 3.5)
    repeat_manifest = max(8, int(8 / max(0.1, 1.0 - loss_rate)))

    wire_packets = list(
        streamer.stream_manifest_wire_packets(
            manifest, chunks, redundancy=calc_redundancy, repeat_manifest=repeat_manifest
        )
    )

    receiver = FountainStreamReceiver(symbol_size=256, secret_key=secret)
    done_event = asyncio.Event()

    class ReceiverProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            receiver.ingest_bytes(data)
            if receiver.is_complete():
                done_event.set()

    # Bind receiver
    rcv_transport, _ = await loop.create_datagram_endpoint(
        lambda: ReceiverProtocol(),
        local_addr=("127.0.0.1", 0),
    )
    rcv_port = rcv_transport.get_extra_info("sockname")[1]

    # Bind dropping proxy
    proxy_protocol = DroppingProxyProtocol(target_port=rcv_port, drop_rate=loss_rate, seed=seed)
    proxy_transport, _ = await loop.create_datagram_endpoint(
        lambda: proxy_protocol,
        local_addr=("127.0.0.1", 0),
    )
    proxy_port = proxy_transport.get_extra_info("sockname")[1]

    try:
        # Transmit datagrams through proxy
        await streamer.broadcast_udp(wire_packets, host="127.0.0.1", port=proxy_port)

        # Await completion with timeout
        await asyncio.wait_for(done_event.wait(), timeout=5.0)

        # Assemble and verify autonomously from wire manifest
        assembled = receiver.assemble()
        actual_hash = hashlib.sha3_256(assembled).hexdigest()
        success = (actual_hash == expected_hash)
    except Exception as exc:
        success = False
        actual_hash = None
        error_msg = str(exc)
    else:
        error_msg = None
    finally:
        proxy_transport.close()
        rcv_transport.close()

    elapsed = time.perf_counter() - start_time
    return {
        "scenario": "e2e_fountain_loss",
        "success": success,
        "payload_bytes": len(payload),
        "packets_sent": len(wire_packets),
        "packets_received_by_proxy": proxy_protocol.packets_received,
        "packets_forwarded": proxy_protocol.packets_forwarded,
        "packets_dropped": proxy_protocol.packets_dropped,
        "configured_loss_rate": loss_rate,
        "effective_loss_rate": (
            proxy_protocol.packets_dropped / max(1, proxy_protocol.packets_received)
        ),
        "sha3_verified": success,
        "duration_seconds": round(elapsed, 4),
        "error": error_msg,
    }


async def run_consecutive_streams_experiment() -> Dict[str, Any]:
    """Sends two independent streams sequentially and verifies zero chunk cross-contamination."""
    start_time = time.perf_counter()
    secret = b"disposable-lab-consecutive-32b-!"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)

    payload_a = b"BURST_ALPHA: Medical supplies manifest for sector 4." * 30
    payload_b = b"BURST_BETA: Emergency food distribution points at sector 9." * 30

    manifest_a, chunks_a, _ = packager.package(payload_a)
    manifest_b, chunks_b, _ = packager.package(payload_b)

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    packets_a = list(streamer.stream_manifest(manifest_a, chunks_a, redundancy=0.50))
    packets_b = list(streamer.stream_manifest(manifest_b, chunks_b, redundancy=0.50))

    # Ingest Stream A
    for pkt in packets_a:
        receiver.ingest_packet(pkt)

    complete_a = receiver.is_complete(manifest_a)
    complete_b_premature = receiver.is_complete(manifest_b)
    assembled_a = receiver.assemble(manifest_a) if complete_a else None

    # Reset session A
    receiver.reset(manifest_a.manifest_id)

    # Ingest Stream B
    for pkt in packets_b:
        receiver.ingest_packet(pkt)

    complete_b = receiver.is_complete(manifest_b)
    assembled_b = receiver.assemble(manifest_b) if complete_b else None

    success = (
        complete_a
        and not complete_b_premature
        and assembled_a == payload_a
        and complete_b
        and assembled_b == payload_b
    )

    elapsed = time.perf_counter() - start_time
    return {
        "scenario": "consecutive_streams",
        "success": success,
        "stream_a_bytes": len(payload_a),
        "stream_b_bytes": len(payload_b),
        "premature_completion_prevented": not complete_b_premature,
        "stream_a_verified": assembled_a == payload_a,
        "stream_b_verified": assembled_b == payload_b,
        "duration_seconds": round(elapsed, 4),
    }


async def run_interleaved_multiplex_experiment() -> Dict[str, Any]:
    """Multiplexes two concurrent streams in random order to verify concurrent stream isolation."""
    start_time = time.perf_counter()
    secret = b"disposable-lab-interleaved-32b-!"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)

    payload_1 = b"TELEMETRY_LOG_1: Battery voltage 12.8V, solar input 45W." * 25
    payload_2 = b"TELEMETRY_LOG_2: Atmospheric pressure 1013.25 hPa, temp 21.4C." * 25

    manifest_1, chunks_1, _ = packager.package(payload_1)
    manifest_2, chunks_2, _ = packager.package(payload_2)

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    packets_1 = list(streamer.stream_manifest(manifest_1, chunks_1, redundancy=0.50))
    packets_2 = list(streamer.stream_manifest(manifest_2, chunks_2, redundancy=0.50))

    # Shuffle both packet streams together
    combined = [(1, p) for p in packets_1] + [(2, p) for p in packets_2]
    rng = random.Random(1337)
    rng.shuffle(combined)

    for _, pkt in combined:
        receiver.ingest_packet(pkt)

    complete_1 = receiver.is_complete(manifest_1)
    complete_2 = receiver.is_complete(manifest_2)
    assembled_1 = receiver.assemble(manifest_1) if complete_1 else None
    assembled_2 = receiver.assemble(manifest_2) if complete_2 else None

    success = (
        complete_1
        and complete_2
        and assembled_1 == payload_1
        and assembled_2 == payload_2
    )

    elapsed = time.perf_counter() - start_time
    return {
        "scenario": "interleaved_multiplex",
        "success": success,
        "total_multiplexed_packets": len(combined),
        "stream_1_verified": assembled_1 == payload_1,
        "stream_2_verified": assembled_2 == payload_2,
        "duration_seconds": round(elapsed, 4),
    }


def run_daemon_reboot_persistence_experiment(sandbox_dir: Path) -> Dict[str, Any]:
    """Tests cold storage persistence across simulated reboot in an isolated sandbox directory."""
    start_time = time.perf_counter()
    articles_dir = sandbox_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    # 1. First run: Ingest articles into sandbox
    search_engine_1 = HybridSearchEngine()
    test_articles = [
        {
            "id": "cholera-triage-2026",
            "title": "Cholera Field Triage & Oral Rehydration Guide",
            "content": "Prepare oral rehydration salts using clean boiled water, sugar, and salt.",
            "tags": ["medical", "epidemic", "triage"],
        },
        {
            "id": "solar-purifier-diy",
            "title": "Solar Still Water Purification Manual",
            "content": "Condense potable water using simple plastic sheet and sunlight distillation.",
            "tags": ["water", "survival", "infrastructure"],
        },
    ]

    for art in test_articles:
        # Write durable JSON bundle
        art_path = articles_dir / f"{art['id']}.json"
        with open(art_path, "w", encoding="utf-8") as f:
            json.dump(art, f, indent=2)
        search_engine_1.add_document(art["id"], art["title"] + " " + art["content"], art)

    # Validate in-memory search 1
    res1 = search_engine_1.search("oral rehydration salts")
    assert len(res1) > 0 and res1[0].chunk_id == "cholera-triage-2026"

    # 2. Simulate process kill: destroy search_engine_1 completely
    del search_engine_1

    # 3. Simulate reboot: start fresh engine with zero prior memory
    search_engine_2 = HybridSearchEngine()
    reloaded_count = 0
    for art_file in articles_dir.glob("*.json"):
        with open(art_file, "r", encoding="utf-8") as f:
            doc = json.load(f)
            search_engine_2.add_document(doc["id"], doc["title"] + " " + doc["content"], doc)
            reloaded_count += 1

    # Validate search survival after cold restart
    res2 = search_engine_2.search("plastic sheet sunlight distillation")
    match_ok = len(res2) > 0 and res2[0].chunk_id == "solar-purifier-diy"

    elapsed = time.perf_counter() - start_time
    success = (reloaded_count == 2 and match_ok)

    return {
        "scenario": "daemon_reboot_persistence",
        "success": success,
        "articles_ingested": 2,
        "articles_restored_post_reboot": reloaded_count,
        "offline_query_verified": match_ok,
        "sandbox_path": str(sandbox_dir),
        "duration_seconds": round(elapsed, 4),
    }


def run_acoustic_afsk_airgap_experiment() -> Dict[str, Any]:
    """Tests 1200 baud Bell 202 audio modulation, channel attenuation, and AGC demodulation."""
    start_time = time.perf_counter()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

    test_payload = b"ACOUSTIC_AIRGAP:CLINIC_MEDS_REQUEST:ANTIBIOTICS_NEEDED:500MG"
    # Synthesize at -20 dB attenuation (amplitude 0.10)
    wav_bytes = modulator.synthesize_wav(test_payload, amplitude=0.10)

    # Demodulate with AGC
    extracted = demodulator.decode_wav(wav_bytes)
    success = (len(extracted) >= 1 and test_payload in extracted)

    elapsed = time.perf_counter() - start_time
    return {
        "scenario": "acoustic_afsk_airgap",
        "success": success,
        "baud_rate": 1200,
        "sample_rate": 16000,
        "attenuation_amplitude": 0.10,
        "payload_bytes": len(test_payload),
        "packets_recovered": len(extracted),
        "crc_verified": success,
        "duration_seconds": round(elapsed, 4),
    }


def run_voice_memo_airgap_experiment() -> Dict[str, Any]:
    """Tests Audio-Pocket VoiceMemo packaging, sync chirp, channel simulator, and bit-exact recovery."""
    start_time = time.perf_counter()

    sample_rate = 8000
    n_samples = 2000
    pcm = bytearray()
    for i in range(n_samples):
        val = int(14000.0 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
        pcm.extend(struct.pack("<h", val))

    memo = VoiceMemo(callsign="OUTPOST3", sample_rate=sample_rate, pcm_data=bytes(pcm), is_16bit=True)
    memo_wire = memo.to_bytes()

    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=777)

    clean_wav = modulator.synthesize_wav(memo_wire, amplitude=0.75, include_chirp=True)

    impaired_wav = sim.impair_wav(
        clean_wav,
        attenuation=0.35,
        snr_db=35.0,
        reverberation=True,
        clipping=False,
    )

    extracted = demodulator.decode_wav(impaired_wav)
    success = False
    recovered_callsign = None
    if len(extracted) >= 1 and memo_wire in extracted:
        recovered = VoiceMemo.from_bytes(memo_wire)
        if recovered.pcm_data == memo.pcm_data and recovered.callsign == "OUTPOST3":
            success = True
            recovered_callsign = recovered.callsign

    elapsed = time.perf_counter() - start_time
    return {
        "scenario": "voice_memo_airgap",
        "success": success,
        "callsign": recovered_callsign,
        "audio_duration_ms": memo.duration_ms,
        "wire_bytes": len(memo_wire),
        "multipath_degraded": True,
        "bit_exact_pcm_recovered": success,
        "duration_seconds": round(elapsed, 4),
    }


async def main_async(args: argparse.Namespace) -> int:
    results: List[Dict[str, Any]] = []
    scenarios_to_run = (
        ["e2e_fountain_loss", "consecutive_streams", "interleaved_multiplex", "daemon_reboot_persistence", "acoustic_afsk_airgap", "voice_memo_airgap"]
        if args.scenario == "all"
        else [args.scenario]
    )

    print(f"=== The Foundation Protocol: Disposable Verification Lab ===")
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print(f"Executing scenarios: {', '.join(scenarios_to_run)}\n")

    overall_success = True

    with tempfile.TemporaryDirectory(prefix="tfp_exp_lab_") as temp_dir_str:
        sandbox_dir = Path(temp_dir_str)

        for scenario in scenarios_to_run:
            print(f"--> Running scenario: [{scenario}]...", end=" ", flush=True)
            res = {}

            if scenario == "e2e_fountain_loss":
                res = await run_e2e_fountain_loss_experiment(loss_rate=args.loss)
            elif scenario == "consecutive_streams":
                res = await run_consecutive_streams_experiment()
            elif scenario == "interleaved_multiplex":
                res = await run_interleaved_multiplex_experiment()
            elif scenario == "daemon_reboot_persistence":
                res = run_daemon_reboot_persistence_experiment(sandbox_dir)
            elif scenario == "acoustic_afsk_airgap":
                res = run_acoustic_afsk_airgap_experiment()
            elif scenario == "voice_memo_airgap":
                res = run_voice_memo_airgap_experiment()
            else:
                print(f"UNKNOWN SCENARIO: {scenario}")
                overall_success = False
                continue

            results.append(res)
            if res.get("success", False):
                print(f"PASS ({res.get('duration_seconds')}s)")
            else:
                print(f"FAIL: {res.get('error', 'Assertion or verification failed')}")
                overall_success = False

        if args.preserve and not overall_success:
            preserved_path = REPO_ROOT / f"preserved_lab_{int(time.time())}"
            shutil.copytree(sandbox_dir, preserved_path)
            print(f"\n[!] Preserved sandbox state to: {preserved_path}")

    # Output formatting
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_success": overall_success,
        "scenarios": results,
    }

    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved lab report to: {report_path}")

    if args.json:
        print("\n" + json.dumps(report, indent=2))

    return 0 if overall_success else 1


def main():
    parser = argparse.ArgumentParser(description="Shared Disposable Verification Lab & Experiment Runner")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "e2e_fountain_loss", "consecutive_streams", "interleaved_multiplex", "daemon_reboot_persistence", "acoustic_afsk_airgap", "voice_memo_airgap"],
        help="Experiment scenario to execute (default: all)",
    )
    parser.add_argument(
        "--loss",
        type=float,
        default=0.20,
        help="Simulated packet loss rate for lossy network scenarios (default: 0.20)",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON summary to stdout")
    parser.add_argument("--report-file", type=str, default=None, help="Save structured JSON report to path")
    parser.add_argument("--preserve", action="store_true", help="Preserve sandbox directory on failure")

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
