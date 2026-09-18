# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Test Battery for Resilient Media & Video Streaming.

Verifies:
1. FastCDC media boundary chunking and Merkle root integrity.
2. Binary packet wire framing and constant-time anti-pollution HMAC authentication.
3. Bit-exact media recovery under 0%, 10%, 25%, and 40% packet drops.
4. Byzantine attack neutralization (tampered packets rejected without matrix pollution).
5. Asynchronous real UDP loopback streaming and reconstruction.
"""

import asyncio
import os
from pathlib import Path
import random
import socket
import sys
import pytest

# Ensure repository roots are in sys.path
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.stream_packager import MediaManifest, MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import (
    AntiPollutionError,
    FountainStreamer,
    MediaDropletPacket,
)
from tfp_client.lib.media.receiver import FountainStreamReceiver


@pytest.fixture
def sample_video_payload() -> bytes:
    """Generate a pseudo-realistic 48KB media stream."""
    rng = random.Random(42)
    # Synthetic video stream with periodic frame header markers
    frames = []
    for i in range(12):
        header = f"FRAME-{i:04d}-KEYFRAME:".encode("ascii")
        body = rng.randbytes(4000)
        frames.append(header + body)
    return b"".join(frames)


def test_media_packager_fastcdc_merkle(sample_video_payload):
    """Verify FastCDC chunking, Merkle tree generation, and chunk audit proofs."""
    packager = MediaStreamPackager(min_chunk_size=2048, target_chunk_size=8192, max_chunk_size=16384)
    manifest, chunks, merkle = packager.package(
        sample_video_payload,
        media_type="video/mp4",
        metadata={"title": "Emergency Bulletin 01", "bitrate_kbps": 250},
    )

    assert manifest.total_size == len(sample_video_payload)
    assert manifest.chunk_count == len(chunks)
    assert manifest.chunk_count > 1
    assert len(manifest.merkle_root) == 64  # SHA3-256 hex string

    # Verify every chunk against the Merkle tree proof
    for idx, chunk in enumerate(chunks):
        assert packager.verify_chunk(chunk, idx, manifest, merkle_tree=merkle)

    # Verify JSON serialization round-trip
    json_str = manifest.to_json()
    manifest_recovered = MediaManifest.from_json(json_str)
    assert manifest_recovered.manifest_id == manifest.manifest_id
    assert manifest_recovered.chunk_hashes == manifest.chunk_hashes

    # Reassemble and verify byte-for-byte exactness
    chunk_map = {i: c for i, c in enumerate(chunks)}
    assembled = packager.assemble(manifest, chunk_map)
    assert assembled == sample_video_payload


def test_droplet_packet_serialization_and_auth():
    """Verify binary wire framing and constant-time HMAC anti-pollution rejection."""
    secret = b"cluster-secret-key-1234"
    payload = b"X" * 512
    pkt = MediaDropletPacket(
        session_id=101,
        chunk_index=3,
        k=8,
        orig_len=4096,
        symbol_size=512,
        seed=15,
        payload=payload,
    )

    wire_bytes = pkt.to_bytes(secret)
    assert len(wire_bytes) == 40 + 512

    # Normal deserialization with matching secret
    deserialized = MediaDropletPacket.from_bytes(wire_bytes, secret_key=secret)
    assert deserialized.session_id == 101
    assert deserialized.chunk_index == 3
    assert deserialized.seed == 15
    assert deserialized.payload == payload

    # Byzantine tampering: flip 1 byte in payload
    tampered_bytes = bytearray(wire_bytes)
    tampered_bytes[-1] ^= 0xFF

    with pytest.raises(AntiPollutionError):
        MediaDropletPacket.from_bytes(bytes(tampered_bytes), secret_key=secret)


def test_lossless_streaming_reconstruction(sample_video_payload):
    """Verify bit-exact streaming reconstruction without packet loss."""
    packager = MediaStreamPackager(min_chunk_size=4096, target_chunk_size=8192, max_chunk_size=16384)
    manifest, chunks, _ = packager.package(sample_video_payload)

    streamer = FountainStreamer(symbol_size=512)
    receiver = FountainStreamReceiver(symbol_size=512)

    packets = list(streamer.stream_manifest(manifest, chunks, redundancy=0.20))
    assert len(packets) > 0

    for pkt in packets:
        receiver.ingest_packet(pkt)

    assert receiver.is_complete(manifest)
    reconstructed = receiver.assemble(manifest)
    assert reconstructed == sample_video_payload


@pytest.mark.parametrize("loss_rate", [0.10, 0.25, 0.40])
def test_streaming_reconstruction_under_packet_loss(sample_video_payload, loss_rate):
    """
    Verify rateless reconstruction under severe loss channels (10%, 25%, 40% packet loss)
    without an uplink retransmission channel.
    """
    packager = MediaStreamPackager(min_chunk_size=2048, target_chunk_size=4096, max_chunk_size=8192)
    manifest, chunks, _ = packager.package(sample_video_payload)

    streamer = FountainStreamer(symbol_size=256)
    receiver = FountainStreamReceiver(symbol_size=256)

    # Use fixed seed for deterministic drop testing
    rng = random.Random(1337 + int(loss_rate * 100))
    session_id = int.from_bytes(bytes.fromhex(manifest.manifest_id)[:4], "big")

    # Broadcaster continuously emits rateless droplets over the lossy link;
    # receiver accumulates surviving droplets until rank K is reached without NACKs
    for idx, chunk in enumerate(chunks):
        seed = 0
        while idx not in receiver.reconstructed_chunks:
            pkt = streamer.generate_packet(chunk, chunk_index=idx, session_id=session_id, seed=seed)
            if rng.random() >= loss_rate:
                receiver.ingest_packet(pkt)
            seed += 1
            if seed > 200:
                break

    assert receiver.is_complete(manifest), (
        f"Failed to complete at {loss_rate*100}% loss: "
        f"got {len(receiver.reconstructed_chunks)}/{manifest.chunk_count} chunks"
    )
    reconstructed = receiver.assemble(manifest)
    assert reconstructed == sample_video_payload


def test_byzantine_attack_resilience(sample_video_payload):
    """
    Verify that Byzantine attackers injecting forged/poisoned packets fail HMAC
    authentication and are discarded without polluting the elimination matrix.
    """
    secret = b"strong-sovereign-mesh-key"
    packager = MediaStreamPackager(min_chunk_size=4096, target_chunk_size=8192, max_chunk_size=16384)
    manifest, chunks, _ = packager.package(sample_video_payload)

    streamer = FountainStreamer(symbol_size=512, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=512, secret_key=secret)

    valid_packets = list(streamer.stream_manifest(manifest, chunks, redundancy=0.35))
    wire_packets = [p.to_bytes(secret) for p in valid_packets]

    # Inject 15 poisoned Byzantine packets with forged payloads and invalid signatures
    rng = random.Random(999)
    poisoned_packets = []
    for _ in range(15):
        bogus_pkt = MediaDropletPacket(
            session_id=valid_packets[0].session_id,
            chunk_index=rng.randint(0, manifest.chunk_count - 1),
            k=valid_packets[0].k,
            orig_len=valid_packets[0].orig_len,
            symbol_size=512,
            seed=rng.randint(100, 500),
            payload=b"\xDE\xAD\xBE\xEF" * 128,
            auth_tag=b"\x00" * 16,  # bogus tag
        )
        poisoned_packets.append(bogus_pkt.to_bytes(b"wrong-key"))

    all_wire_packets = wire_packets + poisoned_packets
    rng.shuffle(all_wire_packets)

    for raw in all_wire_packets:
        receiver.ingest_bytes(raw)

    assert receiver.stats.packets_rejected_auth == 15
    assert receiver.is_complete(manifest)
    assert receiver.assemble(manifest) == sample_video_payload


@pytest.mark.asyncio
async def test_udp_socket_streaming_live(sample_video_payload):
    """
    Verify real asynchronous UDP multicast/unicast loopback streaming.
    """
    # Find a free ephemeral port
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    temp_sock.bind(("127.0.0.1", 0))
    port = temp_sock.getsockname()[1]
    temp_sock.close()

    packager = MediaStreamPackager(min_chunk_size=4096, target_chunk_size=8192, max_chunk_size=16384)
    manifest, chunks, _ = packager.package(sample_video_payload)

    secret = b"live-udp-secret"
    streamer = FountainStreamer(symbol_size=512, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=512, secret_key=secret)

    packets = list(streamer.stream_manifest(manifest, chunks, redundancy=0.25))

    stop_event = asyncio.Event()
    received_chunks = []

    def on_chunk(idx, chunk):
        received_chunks.append(idx)
        if receiver.is_complete(manifest):
            stop_event.set()

    # Launch UDP listener task
    listen_task = asyncio.create_task(
        receiver.listen_udp(host="127.0.0.1", port=port, on_chunk=on_chunk, stop_event=stop_event)
    )

    # Short sleep to ensure UDP socket is bound
    await asyncio.sleep(0.05)

    # Broadcast packets
    await streamer.broadcast_udp(packets, host="127.0.0.1", port=port)

    # Wait for reconstruction or timeout
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=3.0)
    finally:
        stop_event.set()
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

    assert receiver.is_complete(manifest)
    reconstructed = receiver.assemble(manifest)
    assert reconstructed == sample_video_payload
