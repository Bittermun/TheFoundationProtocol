# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Stream Lifecycle & Session Isolation Test Suite.

Verifies:
1. Strict session isolation: Reconstructed chunks from Session A do not satisfy Session B.
2. Consecutive transfers: Two independent media streams sent sequentially decode bit-exact.
3. Interleaved transfers: Two concurrent streams with multiplexed wire packets decode independently.
4. Lifecycle management: Explicit reset(session_id) evicts target buffers without affecting other active streams.
"""

from pathlib import Path
import random
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver


def test_consecutive_stream_isolation():
    """Verify two consecutive streams decode bit-exact and do not cross-pollinate."""
    secret = b"lifecycle-test-secret-key-32b-!"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)

    payload_1 = b"EMERGENCY_MEDICAL_PROTOCOL_ALPHA:" * 40
    payload_2 = b"EVACUATION_ROUTE_MAPPING_BETA:" * 40

    manifest_1, chunks_1, _ = packager.package(payload_1)
    manifest_2, chunks_2, _ = packager.package(payload_2)

    assert manifest_1.manifest_id != manifest_2.manifest_id

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    packets_1 = list(streamer.stream_manifest(manifest_1, chunks_1, redundancy=0.50))
    packets_2 = list(streamer.stream_manifest(manifest_2, chunks_2, redundancy=0.50))

    # Ingest stream 1
    for pkt in packets_1:
        receiver.ingest_packet(pkt)

    assert receiver.is_complete(manifest_1), "Stream 1 must be complete"
    # CRITICAL: Stream 2 must NOT be marked complete from stream 1's chunks!
    assert not receiver.is_complete(manifest_2), "Stream 2 must NOT be marked complete from stream 1 chunks"

    assembled_1 = receiver.assemble(manifest_1)
    assert assembled_1 == payload_1, "Stream 1 assembled payload must match"

    # Ingest stream 2
    for pkt in packets_2:
        receiver.ingest_packet(pkt)

    assert receiver.is_complete(manifest_2), "Stream 2 must now be complete"
    assembled_2 = receiver.assemble(manifest_2)
    assert assembled_2 == payload_2, "Stream 2 assembled payload must match"


def test_interleaved_stream_multiplexing():
    """Verify two concurrent streams arriving interleaved decode independently and bit-exact."""
    secret = b"interleaved-stream-key-32b-abcd"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)

    payload_a = b"STREAM_A_CRITICAL_WATER_PURIFICATION_GUIDE" * 25
    payload_b = b"STREAM_B_ANTIBIOTIC_DOSAGE_FIELD_MANUAL_DATA" * 25

    manifest_a, chunks_a, _ = packager.package(payload_a)
    manifest_b, chunks_b, _ = packager.package(payload_b)

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    pkts_a = list(streamer.stream_manifest(manifest_a, chunks_a, redundancy=0.60))
    pkts_b = list(streamer.stream_manifest(manifest_b, chunks_b, redundancy=0.60))

    # Interleave packets: A1, B1, A2, B2, ...
    interleaved = []
    max_len = max(len(pkts_a), len(pkts_b))
    for i in range(max_len):
        if i < len(pkts_a):
            interleaved.append(pkts_a[i])
        if i < len(pkts_b):
            interleaved.append(pkts_b[i])

    # Shuffle slightly to simulate network jitter while preserving session tags
    rng = random.Random(42)
    rng.shuffle(interleaved)

    for pkt in interleaved:
        receiver.ingest_packet(pkt)

    assert receiver.is_complete(manifest_a), "Interleaved stream A must complete"
    assert receiver.is_complete(manifest_b), "Interleaved stream B must complete"

    res_a = receiver.assemble(manifest_a)
    res_b = receiver.assemble(manifest_b)

    assert res_a == payload_a, "Assembled stream A must be bit-exact match"
    assert res_b == payload_b, "Assembled stream B must be bit-exact match"


def test_session_reset_lifecycle():
    """Verify reset(session_id) selectively evicts one session while preserving another."""
    secret = b"reset-lifecycle-key-32b-12345678"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)

    payload_1 = b"SESSION_ONE_VITAL_SIGNS_DATA" * 20
    payload_2 = b"SESSION_TWO_BLOOD_PRESSURE_LOG" * 20

    manifest_1, chunks_1, _ = packager.package(payload_1)
    manifest_2, chunks_2, _ = packager.package(payload_2)

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    pkts_1 = list(streamer.stream_manifest(manifest_1, chunks_1, redundancy=0.40))
    pkts_2 = list(streamer.stream_manifest(manifest_2, chunks_2, redundancy=0.40))

    for p in pkts_1:
        receiver.ingest_packet(p)
    for p in pkts_2:
        receiver.ingest_packet(p)

    assert receiver.is_complete(manifest_1)
    assert receiver.is_complete(manifest_2)

    # Evict session 1 only
    sess_1_id = receiver.derive_session_id(manifest_1)
    sess_2_id = receiver.derive_session_id(manifest_2)
    receiver.reset(session_id=sess_1_id)

    assert not receiver.is_complete(manifest_1), "Session 1 must be cleared after reset"
    assert receiver.is_complete(manifest_2), "Session 2 must remain complete"

    # Assemble session 2 succeeds
    assert receiver.assemble(manifest_2) == payload_2

    # Global reset clears everything
    receiver.reset()
    assert not receiver.is_complete(manifest_2), "Global reset must clear session 2"


def test_shared_first_chunk_cross_session_isolation():
    """
    Regression test: Two different transfers sharing their first chunk.
    Ingesting transfer 1 must NOT cause transfer 2 to report complete.
    """
    secret = b"shared-chunk-regression-secret-1"
    # min_chunk_size=256, target=256, max=256 ensures exact deterministic chunks
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=256, max_chunk_size=256)

    # Identical 256-byte chunk 0, distinct chunk 1
    shared_prefix = b"COMMON_PROTOCOL_HEADER_DATA_PADDING_BYTE_0000" * 6  # 276 bytes -> chunk 0
    payload_1 = shared_prefix + (b"MISSION_CRITICAL_PAYLOAD_ONE_XYZ" * 10)
    payload_2 = shared_prefix + (b"MISSION_CRITICAL_PAYLOAD_TWO_ABC" * 10)

    manifest_1, chunks_1, _ = packager.package(payload_1)
    manifest_2, chunks_2, _ = packager.package(payload_2)

    # Verify chunk 0 is identical between both transfers
    assert chunks_1[0] == chunks_2[0]
    assert manifest_1.chunk_hashes[0] == manifest_2.chunk_hashes[0]
    # But chunk 1 differs
    assert chunks_1[1] != chunks_2[1]
    assert manifest_1.chunk_hashes[1] != manifest_2.chunk_hashes[1]

    streamer = FountainStreamer(symbol_size=64, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=64, secret_key=secret)

    packets_1 = list(streamer.stream_manifest(manifest_1, chunks_1, redundancy=0.50))
    packets_2 = list(streamer.stream_manifest(manifest_2, chunks_2, redundancy=0.50))

    # Ingest only transfer 1
    for p in packets_1:
        receiver.ingest_packet(p)

    assert receiver.is_complete(manifest_1), "Transfer 1 must be complete"
    # REGRESSION CHECK: Transfer 2 shares chunk 0, but must NOT be reported as complete!
    assert not receiver.is_complete(manifest_2), "Transfer 2 must NOT report complete before receiving its unique chunks"

    # Now ingest transfer 2
    for p in packets_2:
        receiver.ingest_packet(p)

    assert receiver.is_complete(manifest_2), "Transfer 2 must be complete after receiving its chunks"
    assert receiver.assemble(manifest_1) == payload_1
    assert receiver.assemble(manifest_2) == payload_2


def test_receiver_lru_session_eviction_bounded_memory():
    """Verify receiver evicts oldest LRU sessions when max_sessions threshold is reached."""
    receiver = FountainStreamReceiver(symbol_size=64, max_sessions=3, verify_tag=False)
    from tfp_client.lib.media.fountain_streamer import MediaDropletPacket

    # Ingest packets from 3 distinct sessions (10, 20, 30)
    for sid in (10, 20, 30):
        pkt = MediaDropletPacket(
            session_id=sid,
            chunk_index=0,
            k=5,
            orig_len=64,
            symbol_size=64,
            seed=0,
            payload=b"A" * 64,
        )
        receiver.ingest_packet(pkt)

    assert set(receiver._session_timestamps.keys()) == {10, 20, 30}
    assert len(receiver.reconstructed_chunks_by_session) <= 3

    # Now ingest a 4th session (40) -> Session 10 (oldest) must be evicted
    pkt_4 = MediaDropletPacket(
        session_id=40,
        chunk_index=0,
        k=5,
        orig_len=64,
        symbol_size=64,
        seed=0,
        payload=b"B" * 64,
    )
    receiver.ingest_packet(pkt_4)

    assert len(receiver.reconstructed_chunks_by_session) <= 3
    assert 10 not in receiver.reconstructed_chunks_by_session, "Session 10 should have been evicted by LRU"
    assert 40 in receiver.reconstructed_chunks_by_session


def test_receiver_max_droplets_per_chunk_bound():
    """Verify receiver bounds droplet buffer size per chunk to prevent memory exhaustion."""
    receiver = FountainStreamReceiver(symbol_size=64, max_droplets_per_chunk=8, verify_tag=False)
    from tfp_client.lib.media.fountain_streamer import MediaDropletPacket

    # Send 20 distinct repair packets for a chunk requiring k=50 (never completes)
    for seed in range(20):
        pkt = MediaDropletPacket(
            session_id=999,
            chunk_index=0,
            k=50,
            orig_len=64,
            symbol_size=64,
            seed=seed,
            payload=bytes([seed % 256] * 64),
        )
        receiver.ingest_packet(pkt)

    buf = receiver._droplet_buffers.get((999, 0), {})
    assert len(buf) <= 8, f"Droplet buffer exceeded max_droplets_per_chunk bound: {len(buf)} > 8"

