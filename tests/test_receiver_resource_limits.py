# SPDX-License-Identifier: Apache-2.0
"""Resource limits must hold for wire traffic, including announced transfers."""

import hashlib
from dataclasses import replace

import pytest
from tfp_client.lib.media.fountain_streamer import (
    MediaDropletPacket,
    serialize_manifest_packet,
)
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaManifest


def manifest(count=1, size=64):
    return MediaManifest(
        manifest_id="bounded-transfer", media_type="application/octet-stream",
        total_size=count * size, chunk_count=count, merkle_root="unused",
        chunk_hashes=[hashlib.sha3_256(b"A" * size).hexdigest()] * count,
        chunk_sizes=[size] * count,
    )


def packet(**overrides):
    return replace(MediaDropletPacket(
        session_id=7, chunk_index=0, k=2, orig_len=64,
        symbol_size=32, seed=0, payload=b"A" * 32,
    ), **overrides)


def test_manifest_cannot_override_local_chunk_limit():
    receiver = FountainStreamReceiver(symbol_size=32, max_chunks_per_session=2)
    large = manifest(count=10)
    assert receiver.ingest_bytes(serialize_manifest_packet(large, receiver.secret_key)) is None
    assert receiver.received_manifests == {}
    assert receiver._session_timestamps == {}
    sid = receiver.derive_session_id(large)
    for idx in range(10):
        receiver.ingest_bytes(packet(session_id=sid, chunk_index=idx).to_bytes(receiver.secret_key))
    assert len(receiver._droplet_buffers) == 2
    assert len(receiver._chunk_meta) == 2


def test_larger_transfer_can_be_explicitly_enabled():
    receiver = FountainStreamReceiver(symbol_size=32, max_chunks_per_session=3)
    announced = manifest(count=3)
    assert receiver.ingest_bytes(serialize_manifest_packet(announced, receiver.secret_key)) == (-1, b"")
    sid = receiver.derive_session_id(announced)
    for idx in range(3):
        for seed in range(2):
            receiver.ingest_bytes(packet(session_id=sid, chunk_index=idx, seed=seed).to_bytes(receiver.secret_key))
    assert receiver.is_complete()
    assert receiver.assemble() == b"A" * 192


def test_manifest_chunk_cannot_exceed_decoder_capacity():
    receiver = FountainStreamReceiver(symbol_size=32, max_droplets_per_chunk=2)
    assert receiver.ingest_bytes(serialize_manifest_packet(manifest(size=65), receiver.secret_key)) is None
    assert receiver.received_manifests == {}
    assert receiver._session_timestamps == {}


def test_manifest_bounds_packet_length_and_prunes_conflicting_speculation():
    receiver = FountainStreamReceiver(symbol_size=32)
    announced = manifest(size=32)
    sid = receiver.derive_session_id(announced)
    receiver.ingest_bytes(packet(session_id=sid).to_bytes(receiver.secret_key))
    assert (sid, 0) in receiver._droplet_buffers
    receiver.ingest_bytes(serialize_manifest_packet(announced, receiver.secret_key))
    assert (sid, 0) not in receiver._droplet_buffers
    assert (sid, 0) not in receiver._chunk_meta
    receiver.ingest_bytes(packet(session_id=sid).to_bytes(receiver.secret_key))
    assert (sid, 0) not in receiver._droplet_buffers
    assert receiver.ingest_bytes(packet(session_id=sid, k=1, orig_len=32).to_bytes(receiver.secret_key)) == (0, b"A" * 32)


@pytest.mark.parametrize("overrides", [
    {"k": 0}, {"k": 513}, {"orig_len": 0}, {"orig_len": 65},
    {"symbol_size": 64, "payload": b"X" * 64},
])
def test_impossible_or_oversized_wire_packets_allocate_no_state(overrides):
    receiver = FountainStreamReceiver(symbol_size=32)
    assert receiver.ingest_bytes(packet(**overrides).to_bytes(receiver.secret_key)) is None
    assert receiver._droplet_buffers == {}
    assert receiver._chunk_meta == {}
    assert receiver._session_timestamps == {}
    assert receiver.reconstructed_chunks_by_session == {}


@pytest.mark.parametrize("overrides", [
    {"k": 3}, {"orig_len": 63}, {"payload": b"X" * 33}, {"chunk_index": -1},
])
def test_conflicting_packet_cannot_poison_existing_buffer(overrides):
    receiver = FountainStreamReceiver(symbol_size=32, verify_tag=False)
    receiver.ingest_packet(packet())
    assert receiver.ingest_packet(packet(seed=1, **overrides)) is None
    assert set(receiver._droplet_buffers) == {(7, 0)}
    assert len(receiver._droplet_buffers[(7, 0)]) == 1
    assert receiver.ingest_packet(packet(seed=1)) == (0, b"A" * 64)


def test_bad_authenticated_packet_cannot_evict_active_session():
    receiver = FountainStreamReceiver(symbol_size=32, max_sessions=1)
    receiver.ingest_bytes(packet().to_bytes(receiver.secret_key))
    receiver.ingest_packet(packet(session_id=8, auth_tag=b"x" * 16))
    assert set(receiver._session_timestamps) == {7}
    assert set(receiver._droplet_buffers) == {(7, 0)}


def test_late_manifest_removes_all_out_of_bounds_metadata():
    receiver = FountainStreamReceiver(symbol_size=32, verify_tag=False)
    announced = manifest(size=32)
    sid = receiver.derive_session_id(announced)
    receiver.ingest_packet(packet(session_id=sid, chunk_index=5, k=1, orig_len=32))
    assert receiver.reconstructed_chunks_by_session[sid] == {5: b"A" * 32}
    receiver.ingest_bytes(serialize_manifest_packet(announced))
    assert receiver.reconstructed_chunks_by_session[sid] == {}
    assert (sid, 5) not in receiver._chunk_meta


def test_late_manifest_discards_wrong_content_so_valid_retransmission_can_finish():
    receiver = FountainStreamReceiver(symbol_size=32, verify_tag=False)
    announced = manifest(size=32)
    sid = receiver.derive_session_id(announced)
    receiver.ingest_packet(packet(session_id=sid, k=1, orig_len=32, payload=b"X" * 32))
    receiver.ingest_bytes(serialize_manifest_packet(announced))
    assert not receiver.is_complete()
    assert receiver.ingest_packet(packet(session_id=sid, k=1, orig_len=32)) == (0, b"A" * 32)
    assert receiver.assemble() == b"A" * 32


@pytest.mark.parametrize("field", ["max_sessions", "max_chunks_per_session", "max_droplets_per_chunk"])
def test_receiver_rejects_nonpositive_limits(field):
    with pytest.raises(ValueError):
        FountainStreamReceiver(**{field: 0})


def test_manifest_rejects_negative_chunk_sizes_even_when_sum_matches():
    data = manifest(count=2).to_dict()
    data["chunk_sizes"] = [-1, 129]
    with pytest.raises(ValueError):
        MediaManifest.from_dict(data)
