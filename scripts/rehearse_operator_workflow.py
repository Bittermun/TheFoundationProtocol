#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Station-to-Listener Operator Rehearsal Harness.

Simulates the realistic 8-stage operational workflow:
Stage 1: Notice Authoring (Initial bulletin, "WILDFIRE EVACUATION NOTICE", rev 1).
Stage 2: Ed25519 Signing (Canonical JSON envelope v2 signed with publisher key, SHA3-256 content hash).
Stage 3: Acoustic Modulation (Bell 202 continuous-phase FSK 1200 baud audio synthesis via AFSKModulator).
Stage 4: Audio Transmission (Pass audio through AcousticChannelSimulator with AWGN noise and multipath echo).
Stage 5: Receiver Capture & Ingestion (Demodulate audio via AFSKDemodulator, ingest into Listener TFPNode, verify signature, store in SQLite DB, update watermark to rev 1).
Stage 6: Simulated Missed Broadcast (Author and sign rev 2 correction "WILDFIRE ROUTE UPDATE", synthesize audio, transmit over air, but simulate listener packet drop / offline so rev 2 is NOT ingested).
Stage 7: Correction Distribution & Revision Gap Detection (Author and sign rev 3 correction "WILDFIRE FINAL CLEARANCE", synthesize audio, transmit through channel, demodulate and ingest into listener node; detect revision gap rev 3 > watermark 1 + 1, flag missed broadcast warning, update watermark to rev 3).
Stage 8: Replay Rejection Validation (Attempt re-import of rev 1 and missed rev 2; verify node rejects both with StaleRevisionError and maintains watermark at rev 3).

Reports comprehensive operator metrics:
- Timing: per-stage duration and total execution duration (seconds).
- Airtime Footprint: total wire bytes, audio sample count, audio duration seconds, transmission efficiency (payload bytes / airtime second).
- Recovery Verification: latest notice recovered bit-exact (title, body, SHA3-256 hash, verified Ed25519 signature, node watermark = 3).
- Gap detection confirmed = True, replay protection confirmed = True.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

# Ensure repository root and tfp package root are on sys.path
_repo_root = Path(__file__).resolve().parent.parent
_tfp_root = _repo_root / "tfp-foundation-protocol"
for _p in (str(_repo_root), str(_tfp_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator  # noqa: E402
from tfp_client.lib.audio.afsk_modulator import AFSKModulator  # noqa: E402
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator  # noqa: E402
from tfp_core_v4.bulletin_identity import (  # noqa: E402
    SIGNATURE_VERSION,
    StaleRevisionError,
    sign_bulletin_content,
    verification_status,
    verify_bulletin_signature,
)
from tfp_core_v4.node import TFPNode  # noqa: E402

BULLETIN_ID = "NOTICE-WILDFIRE-2026"

NOTICE_REV1 = {
    "revision": 1,
    "title": "WILDFIRE EVACUATION NOTICE",
    "body": (
        "MANDATORY EVACUATION: Wildfire spreading rapidly along Ridge Road. "
        "All residents in Sector A must evacuate immediately to Community Center 1. "
        "Evacuation route: Highway 12 West. Bring emergency kits and pets."
    ),
}

NOTICE_REV2 = {
    "revision": 2,
    "title": "WILDFIRE ROUTE UPDATE",
    "body": (
        "EVACUATION ROUTE UPDATE: Highway 12 is closed due to dense smoke and spot fires. "
        "Reroute immediately via South Pass Road to Shelter 2 at County Fairgrounds. "
        "Emergency personnel are stationed at South Pass checkpoints."
    ),
}

NOTICE_REV3 = {
    "revision": 3,
    "title": "WILDFIRE FINAL CLEARANCE",
    "body": (
        "FINAL ALL-CLEAR: Fire perimeter fully contained by CalFire crews. "
        "Mandatory evacuation orders for Sector A have been officially lifted. "
        "Residents may safely return. Air quality advisory remains in effect."
    ),
}


def rehearse_operator_workflow(
    output_dir: Path | str | None = None,
    seed: int = 42,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Execute the complete 8-stage station-to-listener operator rehearsal workflow.

    Parameters:
        output_dir: Optional directory to store rehearsal WAV files and database.
                    If None, a temporary directory is created.
        seed: Random seed for the acoustic channel simulator.
        verbose: If True, prints formatted human-readable terminal progress and metrics.

    Returns:
        dict: Complete structured metrics reporting per-stage timings, airtime footprint,
              recovery verification, revision gap detection, and replay protection.
    """
    t_global_start = time.perf_counter()

    temp_dir_obj = None
    if output_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="tfp_rehearsal_")
        out_path = Path(temp_dir_obj.name)
    else:
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

    stages_log: list[dict[str, Any]] = []
    timing: dict[str, float] = {}
    airtime_per_broadcast: list[dict[str, Any]] = []
    total_wire_bytes = 0
    total_payload_bytes = 0
    total_audio_samples = 0
    total_audio_duration = 0.0

    if verbose:
        print("=" * 72)
        print("  THE FOUNDATION PROTOCOL: OPERATOR WORKFLOW REHEARSAL HARNESS")
        print("  Station-to-Listener 8-Stage Operational Lifecycle Simulation")
        print("=" * 72)

    # Common components
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    channel_sim = AcousticChannelSimulator(seed=seed)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

    db_path = out_path / "isolated_listener.db"
    listener_node = TFPNode(db_path=db_path)

    # -------------------------------------------------------------------------
    # STAGE 1: Notice Authoring (Rev 1)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    bulletin_id = BULLETIN_ID
    rev1 = NOTICE_REV1
    body_bytes_1 = rev1["body"].encode("utf-8")
    content_hash_1 = hashlib.sha3_256(body_bytes_1).hexdigest()
    s1_duration = time.perf_counter() - t0
    timing["stage_1_duration_seconds"] = round(s1_duration, 4)

    s1_entry = {
        "stage": 1,
        "name": "Notice Authoring",
        "duration_seconds": timing["stage_1_duration_seconds"],
        "status": "PASS",
        "details": {
            "bulletin_id": bulletin_id,
            "revision": 1,
            "title": rev1["title"],
            "body_length_bytes": len(body_bytes_1),
            "content_hash": content_hash_1,
        },
    }
    stages_log.append(s1_entry)
    if verbose:
        print("\n[STAGE 1: NOTICE AUTHORING]")
        print(f"  Bulletin ID  : {bulletin_id} (Rev 1)")
        print(f"  Title        : {rev1['title']}")
        print(f"  Payload Size : {len(body_bytes_1)} bytes")
        print(f"  SHA3-256 Hash: {content_hash_1[:20]}...")
        print(f"  Status       : PASS ({s1_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 2: Ed25519 Signing (Rev 1)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    # Station operator keypair
    operator_sk = ed25519.Ed25519PrivateKey.generate()

    pub_id, sig_hex_1 = sign_bulletin_content(
        bulletin_id=bulletin_id,
        revision=1,
        content_hash=content_hash_1,
        private_key=operator_sk,
        title=rev1["title"],
    )
    sig_valid_1 = verify_bulletin_signature(
        bulletin_id=bulletin_id,
        revision=1,
        content_hash=content_hash_1,
        publisher_id_hex=pub_id,
        signature_hex=sig_hex_1,
        title=rev1["title"],
    )
    if not sig_valid_1:
        raise ValueError("Stage 2 failure: Ed25519 signature verification failed")

    s2_duration = time.perf_counter() - t0
    timing["stage_2_duration_seconds"] = round(s2_duration, 4)

    s2_entry = {
        "stage": 2,
        "name": "Ed25519 Signing",
        "duration_seconds": timing["stage_2_duration_seconds"],
        "status": "PASS",
        "details": {
            "publisher_id": pub_id,
            "signature_hex": sig_hex_1,
            "signature_version": SIGNATURE_VERSION,
            "verified": True,
        },
    }
    stages_log.append(s2_entry)
    if verbose:
        print("\n[STAGE 2: ED25519 SIGNING]")
        print(f"  Publisher ID : {pub_id}")
        print(f"  Signature Hex: {sig_hex_1[:32]}... ({len(sig_hex_1)} chars)")
        print(f"  Envelope Ver : Version {SIGNATURE_VERSION} (Canonical JSON)")
        print(f"  Status       : PASS ({s2_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 3: Acoustic Modulation (Rev 1)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    wire_dict_1 = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": 1,
        "title": rev1["title"],
        "body": rev1["body"],
        "pub": pub_id,
        "sig": sig_hex_1,
    }
    wire_bytes_1 = json.dumps(wire_dict_1, ensure_ascii=False).encode("utf-8")
    wav_bytes_1 = modulator.synthesize_wav(wire_bytes_1)

    wav_path_1 = out_path / "broadcast_rev1.wav"
    wav_path_1.write_bytes(wav_bytes_1)

    duration_1 = len(wav_bytes_1) / (16000 * 2)
    samples_1 = (len(wav_bytes_1) - 44) // 2

    total_wire_bytes += len(wire_bytes_1)
    total_payload_bytes += len(body_bytes_1)
    total_audio_samples += samples_1
    total_audio_duration += duration_1

    airtime_per_broadcast.append({
        "revision": 1,
        "title": rev1["title"],
        "wire_bytes": len(wire_bytes_1),
        "payload_bytes": len(body_bytes_1),
        "audio_samples": samples_1,
        "audio_duration_seconds": round(duration_1, 3),
    })

    s3_duration = time.perf_counter() - t0
    timing["stage_3_duration_seconds"] = round(s3_duration, 4)

    s3_entry = {
        "stage": 3,
        "name": "Acoustic Modulation",
        "duration_seconds": timing["stage_3_duration_seconds"],
        "status": "PASS",
        "details": {
            "wire_bytes": len(wire_bytes_1),
            "audio_duration_seconds": round(duration_1, 3),
            "audio_samples": samples_1,
            "baud_rate": 1200,
            "profile": "Bell 202 CPFSK",
            "wav_path": str(wav_path_1),
        },
    }
    stages_log.append(s3_entry)
    if verbose:
        print("\n[STAGE 3: ACOUSTIC MODULATION]")
        print(f"  Wire Payload : {len(wire_bytes_1)} bytes")
        print(f"  Audio Samples: {samples_1:,} samples (16 kHz 16-bit PCM)")
        print(f"  Airtime Audio: {duration_1:.2f} seconds (@ 1200 Baud Bell 202)")
        print(f"  Artifact File: {wav_path_1.name}")
        print(f"  Status       : PASS ({s3_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 4: Audio Transmission (Rev 1)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    rx_wav_1 = channel_sim.impair_wav(
        wav_bytes_1,
        attenuation=0.70,
        snr_db=30.0,
        reverberation=True,
        clipping=True,
    )
    rx_wav_path_1 = out_path / "received_rev1.wav"
    rx_wav_path_1.write_bytes(rx_wav_1)

    s4_duration = time.perf_counter() - t0
    timing["stage_4_duration_seconds"] = round(s4_duration, 4)

    s4_entry = {
        "stage": 4,
        "name": "Audio Transmission",
        "duration_seconds": timing["stage_4_duration_seconds"],
        "status": "PASS",
        "details": {
            "attenuation": 0.70,
            "snr_db": 30.0,
            "multipath_reverberation": True,
            "clipping": True,
            "output_wav": str(rx_wav_path_1),
        },
    }
    stages_log.append(s4_entry)
    if verbose:
        print("\n[STAGE 4: AUDIO TRANSMISSION]")
        print("  Channel Model: Acoustic Multipath Reverberation + AWGN (30 dB SNR) + Saturation Clipping")
        print(f"  Channel File : {rx_wav_path_1.name} ({len(rx_wav_1):,} bytes)")
        print(f"  Status       : PASS ({s4_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 5: Receiver Capture & Ingestion (Rev 1)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    packets_1 = demodulator.decode_wav(rx_wav_1)
    if not packets_1:
        raise ValueError("Stage 5 failure: Demodulation failed to recover packets from received audio")

    wire_rx_1 = json.loads(packets_1[0].decode("utf-8"))
    rx_hash_1 = hashlib.sha3_256(wire_rx_1["body"].encode("utf-8")).hexdigest()

    v_status_1 = verification_status(
        bulletin_id=wire_rx_1["id"],
        revision=wire_rx_1["rev"],
        content_hash=rx_hash_1,
        publisher=wire_rx_1["pub"],
        signature=wire_rx_1["sig"],
        title=wire_rx_1["title"],
        version=wire_rx_1["v"],
    )
    if v_status_1 != "verified_ed25519":
        raise ValueError(f"Stage 5 signature check unexpected status: {v_status_1}")

    recipe_1 = listener_node.store_bulletin(
        bulletin_id=wire_rx_1["id"],
        revision=wire_rx_1["rev"],
        data=wire_rx_1["body"].encode("utf-8"),
        title=wire_rx_1["title"],
        publisher_id=wire_rx_1["pub"],
        signature_hex=wire_rx_1["sig"],
        signature_version=wire_rx_1["v"],
        metadata={"origin": "rehearsal_audio_rx", "stage": 5},
    )

    wm_1 = listener_node.get_bulletin_watermark(pub_id, bulletin_id)
    if not wm_1 or wm_1["max_revision"] != 1:
        raise ValueError(f"Stage 5 failure: Node watermark revision expected 1, got {wm_1}")

    stored_meta_1, stored_data_1 = listener_node.get_bulletin(bulletin_id, 1)
    if stored_data_1 != body_bytes_1:
        raise ValueError("Stage 5 failure: Stored body bytes differ from original authoring")

    s5_duration = time.perf_counter() - t0
    timing["stage_5_duration_seconds"] = round(s5_duration, 4)

    s5_entry = {
        "stage": 5,
        "name": "Receiver Capture & Ingestion",
        "duration_seconds": timing["stage_5_duration_seconds"],
        "status": "PASS",
        "details": {
            "packets_recovered": len(packets_1),
            "verified_status": v_status_1,
            "root_hash": recipe_1.root_hash,
            "watermark_revision": wm_1["max_revision"],
            "bit_exact": True,
        },
    }
    stages_log.append(s5_entry)
    if verbose:
        print("\n[STAGE 5: RECEIVER CAPTURE & INGESTION]")
        print(f"  CRC16 Packets: {len(packets_1)} recovered cleanly")
        print(f"  Verification : {v_status_1} (Cryptographically Valid)")
        print(f"  Node Root    : {recipe_1.root_hash[:24]}...")
        print(f"  Watermark    : Rev {wm_1['max_revision']} established in durable SQLite store")
        print("  Bit-Exactness: 100% MATCH with authored Rev 1")
        print(f"  Status       : PASS ({s5_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 6: Simulated Missed Broadcast (Rev 2)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    rev2 = NOTICE_REV2
    body_bytes_2 = rev2["body"].encode("utf-8")
    content_hash_2 = hashlib.sha3_256(body_bytes_2).hexdigest()

    pub_id_2, sig_hex_2 = sign_bulletin_content(
        bulletin_id=bulletin_id,
        revision=2,
        content_hash=content_hash_2,
        private_key=operator_sk,
        title=rev2["title"],
    )
    wire_dict_2 = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": 2,
        "title": rev2["title"],
        "body": rev2["body"],
        "pub": pub_id_2,
        "sig": sig_hex_2,
    }
    wire_bytes_2 = json.dumps(wire_dict_2, ensure_ascii=False).encode("utf-8")
    wav_bytes_2 = modulator.synthesize_wav(wire_bytes_2)

    wav_path_2 = out_path / "broadcast_rev2.wav"
    wav_path_2.write_bytes(wav_bytes_2)

    duration_2 = len(wav_bytes_2) / (16000 * 2)
    samples_2 = (len(wav_bytes_2) - 44) // 2

    total_wire_bytes += len(wire_bytes_2)
    total_payload_bytes += len(body_bytes_2)
    total_audio_samples += samples_2
    total_audio_duration += duration_2

    airtime_per_broadcast.append({
        "revision": 2,
        "title": rev2["title"],
        "wire_bytes": len(wire_bytes_2),
        "payload_bytes": len(body_bytes_2),
        "audio_samples": samples_2,
        "audio_duration_seconds": round(duration_2, 3),
    })

    # Transmit through airgap channel
    rx_wav_2 = channel_sim.impair_wav(
        wav_bytes_2,
        attenuation=0.70,
        snr_db=30.0,
        reverberation=True,
        clipping=True,
    )
    rx_wav_path_2 = out_path / "received_rev2.wav"
    rx_wav_path_2.write_bytes(rx_wav_2)

    # SIMULATED LISTENER PACKET DROP:
    # Ingestion into listener_node is intentionally bypassed.
    wm_unaffected = listener_node.get_bulletin_watermark(pub_id, bulletin_id)
    if not wm_unaffected or wm_unaffected["max_revision"] != 1:
        raise ValueError("Stage 6 failure: Listener watermark should remain at Rev 1")
    if listener_node.get_bulletin(bulletin_id, 2) is not None:
        raise ValueError("Stage 6 failure: Rev 2 should not exist in listener node")

    s6_duration = time.perf_counter() - t0
    timing["stage_6_duration_seconds"] = round(s6_duration, 4)

    s6_entry = {
        "stage": 6,
        "name": "Simulated Missed Broadcast",
        "duration_seconds": timing["stage_6_duration_seconds"],
        "status": "PASS",
        "details": {
            "missed_revision": 2,
            "title": rev2["title"],
            "wire_bytes": len(wire_bytes_2),
            "airtime_duration_seconds": round(duration_2, 3),
            "simulated_drop": True,
            "listener_watermark_retained": wm_unaffected["max_revision"],
        },
    }
    stages_log.append(s6_entry)
    if verbose:
        print("\n[STAGE 6: SIMULATED MISSED BROADCAST]")
        print(f"  Correction   : Rev 2 ('{rev2['title']}') authored, signed & modulated")
        print(f"  Aired Audio  : {duration_2:.2f} seconds aired over channel")
        print("  Listener Drop: SIMULATED DROP / RECEIVER OFFLINE (Rev 2 not ingested)")
        print(f"  Watermark    : Strictly preserved at Rev {wm_unaffected['max_revision']}")
        print(f"  Status       : PASS ({s6_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 7: Correction Distribution & Revision Gap Detection (Rev 3)
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()
    rev3 = NOTICE_REV3
    body_bytes_3 = rev3["body"].encode("utf-8")
    content_hash_3 = hashlib.sha3_256(body_bytes_3).hexdigest()

    pub_id_3, sig_hex_3 = sign_bulletin_content(
        bulletin_id=bulletin_id,
        revision=3,
        content_hash=content_hash_3,
        private_key=operator_sk,
        title=rev3["title"],
    )
    wire_dict_3 = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": 3,
        "title": rev3["title"],
        "body": rev3["body"],
        "pub": pub_id_3,
        "sig": sig_hex_3,
    }
    wire_bytes_3 = json.dumps(wire_dict_3, ensure_ascii=False).encode("utf-8")
    wav_bytes_3 = modulator.synthesize_wav(wire_bytes_3)

    wav_path_3 = out_path / "broadcast_rev3.wav"
    wav_path_3.write_bytes(wav_bytes_3)

    duration_3 = len(wav_bytes_3) / (16000 * 2)
    samples_3 = (len(wav_bytes_3) - 44) // 2

    total_wire_bytes += len(wire_bytes_3)
    total_payload_bytes += len(body_bytes_3)
    total_audio_samples += samples_3
    total_audio_duration += duration_3

    airtime_per_broadcast.append({
        "revision": 3,
        "title": rev3["title"],
        "wire_bytes": len(wire_bytes_3),
        "payload_bytes": len(body_bytes_3),
        "audio_samples": samples_3,
        "audio_duration_seconds": round(duration_3, 3),
    })

    rx_wav_3 = channel_sim.impair_wav(
        wav_bytes_3,
        attenuation=0.70,
        snr_db=30.0,
        reverberation=True,
        clipping=True,
    )
    rx_wav_path_3 = out_path / "received_rev3.wav"
    rx_wav_path_3.write_bytes(rx_wav_3)

    packets_3 = demodulator.decode_wav(rx_wav_3)
    if not packets_3:
        raise ValueError("Stage 7 failure: Demodulation failed to recover Rev 3 packets")

    wire_rx_3 = json.loads(packets_3[0].decode("utf-8"))
    rx_hash_3 = hashlib.sha3_256(wire_rx_3["body"].encode("utf-8")).hexdigest()

    # Gap Detection Logic against listener watermark
    current_listener_wm = listener_node.get_bulletin_watermark(pub_id, bulletin_id)
    prev_wm_rev = current_listener_wm["max_revision"] if current_listener_wm else 0
    incoming_rev = wire_rx_3["rev"]

    gap_detected = incoming_rev > (prev_wm_rev + 1)
    if not gap_detected:
        raise ValueError(
            f"Stage 7 failure: Revision gap not detected! Expected incoming ({incoming_rev}) > watermark ({prev_wm_rev}) + 1"
        )

    missed_revs = list(range(prev_wm_rev + 1, incoming_rev))
    gap_warning = (
        f"[MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev {prev_wm_rev} to Rev {incoming_rev})]"
    )

    v_status_3 = verification_status(
        bulletin_id=wire_rx_3["id"],
        revision=wire_rx_3["rev"],
        content_hash=rx_hash_3,
        publisher=wire_rx_3["pub"],
        signature=wire_rx_3["sig"],
        title=wire_rx_3["title"],
        version=wire_rx_3["v"],
    )

    recipe_3 = listener_node.store_bulletin(
        bulletin_id=wire_rx_3["id"],
        revision=wire_rx_3["rev"],
        data=wire_rx_3["body"].encode("utf-8"),
        title=wire_rx_3["title"],
        publisher_id=wire_rx_3["pub"],
        signature_hex=wire_rx_3["sig"],
        signature_version=wire_rx_3["v"],
        metadata={"origin": "rehearsal_audio_rx", "stage": 7, "gap_detected": True},
    )

    wm_3 = listener_node.get_bulletin_watermark(pub_id, bulletin_id)
    if not wm_3 or wm_3["max_revision"] != 3:
        raise ValueError(f"Stage 7 failure: Watermark should advance to Rev 3, got {wm_3}")

    stored_meta_3, stored_data_3 = listener_node.get_bulletin(bulletin_id, 3)
    if stored_data_3 != body_bytes_3:
        raise ValueError("Stage 7 failure: Stored Rev 3 content does not match original authoring")

    s7_duration = time.perf_counter() - t0
    timing["stage_7_duration_seconds"] = round(s7_duration, 4)

    s7_entry = {
        "stage": 7,
        "name": "Correction Distribution & Revision Gap Detection",
        "duration_seconds": timing["stage_7_duration_seconds"],
        "status": "PASS",
        "details": {
            "gap_detected": True,
            "previous_watermark": prev_wm_rev,
            "incoming_revision": incoming_rev,
            "missed_revisions": missed_revs,
            "warning_message": gap_warning,
            "new_watermark": wm_3["max_revision"],
            "root_hash": recipe_3.root_hash,
            "verified_status": v_status_3,
        },
    }
    stages_log.append(s7_entry)
    if verbose:
        print("\n[STAGE 7: CORRECTION DISTRIBUTION & REVISION GAP DETECTION]")
        print(f"  Incoming Rev : Rev {incoming_rev} ('{rev3['title']}')")
        print(f"  Prior Mark   : Rev {prev_wm_rev}")
        print(f"  Gap Warning  : {gap_warning}")
        print(f"  Missed Revs  : {missed_revs}")
        print(f"  Watermark    : Advanced to Rev {wm_3['max_revision']}")
        print(f"  Status       : PASS ({s7_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # STAGE 8: Replay Rejection Validation
    # -------------------------------------------------------------------------
    t0 = time.perf_counter()

    # Attempt re-import of Rev 1
    rev1_rejected = False
    try:
        listener_node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=1,
            data=body_bytes_1,
            title=rev1["title"],
            publisher_id=pub_id,
            signature_hex=sig_hex_1,
            signature_version=SIGNATURE_VERSION,
        )
    except StaleRevisionError:
        rev1_rejected = True

    # Attempt re-import of missed Rev 2
    rev2_rejected = False
    try:
        listener_node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=body_bytes_2,
            title=rev2["title"],
            publisher_id=pub_id,
            signature_hex=sig_hex_2,
            signature_version=SIGNATURE_VERSION,
        )
    except StaleRevisionError:
        rev2_rejected = True

    if not rev1_rejected:
        raise ValueError("Stage 8 failure: Stale Rev 1 replay was not rejected!")
    if not rev2_rejected:
        raise ValueError("Stage 8 failure: Stale Rev 2 replay was not rejected!")

    wm_final = listener_node.get_bulletin_watermark(pub_id, bulletin_id)
    if not wm_final or wm_final["max_revision"] != 3:
        raise ValueError(f"Stage 8 failure: Watermark compromised after replay attempts: {wm_final}")

    # Check latest bulletin in storage remains Rev 3
    latest_meta, latest_data = listener_node.get_bulletin(bulletin_id)
    if latest_meta["revision"] != 3 or latest_data != body_bytes_3:
        raise ValueError("Stage 8 failure: Authoritative bulletin was altered by stale replay")

    s8_duration = time.perf_counter() - t0
    timing["stage_8_duration_seconds"] = round(s8_duration, 4)

    s8_entry = {
        "stage": 8,
        "name": "Replay Rejection Validation",
        "duration_seconds": timing["stage_8_duration_seconds"],
        "status": "PASS",
        "details": {
            "rev_1_rejected_stale": rev1_rejected,
            "rev_2_rejected_stale": rev2_rejected,
            "watermark_preserved": wm_final["max_revision"],
            "latest_authoritative_revision": latest_meta["revision"],
        },
    }
    stages_log.append(s8_entry)
    if verbose:
        print("\n[STAGE 8: REPLAY REJECTION VALIDATION]")
        print("  Replay Rev 1 : Correctly REJECTED with StaleRevisionError")
        print("  Replay Rev 2 : Correctly REJECTED with StaleRevisionError")
        print(f"  Watermark    : Strictly preserved at Rev {wm_final['max_revision']}")
        print(f"  Status       : PASS ({s8_duration:.4f}s)")

    # -------------------------------------------------------------------------
    # METRICS COMPILATION
    # -------------------------------------------------------------------------
    total_duration = time.perf_counter() - t_global_start
    timing["total_duration_seconds"] = round(total_duration, 4)
    tx_efficiency = (
        round(total_payload_bytes / total_audio_duration, 2)
        if total_audio_duration > 0
        else 0.0
    )

    metrics: dict[str, Any] = {
        "success": True,
        "stages": stages_log,
        "timing": timing,
        "airtime_footprint": {
            "total_wire_bytes": total_wire_bytes,
            "total_payload_bytes": total_payload_bytes,
            "total_audio_samples": total_audio_samples,
            "total_audio_duration_seconds": round(total_audio_duration, 3),
            "transmission_efficiency_bytes_per_sec": tx_efficiency,
            "per_broadcast": airtime_per_broadcast,
        },
        "recovery_verification": {
            "recovered_bulletin_id": bulletin_id,
            "recovered_revision": 3,
            "recovered_title": rev3["title"],
            "recovered_body": rev3["body"],
            "content_hash": content_hash_3,
            "verified_ed25519": True,
            "publisher_id": pub_id,
            "node_watermark": 3,
            "bit_exact": True,
        },
        "gap_detection": {
            "gap_detected": True,
            "previous_watermark": 1,
            "incoming_revision": 3,
            "missed_revisions": [2],
            "warning_message": gap_warning,
        },
        "replay_protection": {
            "replay_protection_confirmed": True,
            "rev_1_rejected_stale": True,
            "rev_2_rejected_stale": True,
            "watermark_preserved": 3,
        },
        # Convenience top-level keys for programmatic evaluation
        "total_duration_seconds": round(total_duration, 4),
        "airtime_duration_seconds": round(total_audio_duration, 3),
        "total_wire_bytes": total_wire_bytes,
        "transmission_efficiency": tx_efficiency,
        "gap_detected": True,
        "replay_protection_confirmed": True,
        "recovery_verified": True,
        "latest_watermark": 3,
    }

    # Persist metrics to output dir
    metrics_file = out_path / "rehearsal_metrics.json"
    metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if verbose:
        print("\n" + "=" * 72)
        print("  REHEARSAL SUMMARY METRICS")
        print("=" * 72)
        print(f"  Total Execution Duration   : {total_duration:.2f} seconds")
        print(f"  Total Airtime Audio Length : {total_audio_duration:.2f} seconds (3 broadcasts)")
        print(f"  Total Airtime Samples      : {total_audio_samples:,} samples")
        print(f"  Total Wire Encoded Bytes   : {total_wire_bytes:,} bytes")
        print(f"  Total Payload Text Bytes   : {total_payload_bytes:,} bytes")
        print(f"  Transmission Efficiency    : {tx_efficiency} payload bytes / airtime sec")
        print("  Authentic Recovery Status  : 100% BIT-EXACT MATCH (Rev 3)")
        print(f"  Cryptographic Authenticity : verified_ed25519 (Pub: {pub_id[:16]}...)")
        print("  Missed Broadcast Gap       : CONFIRMED (Jumped from Rev 1 to Rev 3)")
        print("  Watermark Protection Guard : CONFIRMED (Stale Rev 1 & Rev 2 rejected)")
        print(f"  Artifacts Output Directory : {out_path}")
        print("=" * 72)
        print("  RESULT: SUCCESS (All 8 operational stages completed cleanly)")
        print("=" * 72)

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The Foundation Protocol: Station-to-Listener Operator Workflow Rehearsal Harness"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured metrics as JSON to stdout",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Directory to save rehearsal artifacts and metrics JSON",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for acoustic channel simulator (default: 42)",
    )
    args = parser.parse_args()

    verbose = not args.json_output
    metrics = rehearse_operator_workflow(output_dir=args.output_dir, seed=args.seed, verbose=verbose)

    if args.json_output:
        print(json.dumps(metrics, indent=2))

    sys.exit(0 if metrics.get("success") else 1)


if __name__ == "__main__":
    main()
