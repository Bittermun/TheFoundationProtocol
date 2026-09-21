# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acceptance tests for Receiver Single-Transfer Bounding & Anti-Exhaustion Protections.

Proves that:
1. MediaManifest.from_dict enforces chunk_count == len(chunk_hashes) and sum(sizes) == total_size.
2. Given a 1-chunk manifest, emitting 100 out-of-bounds chunk_index values (1..100) rejects
   all packets without allocating any buffers in _droplet_buffers or _chunk_meta.
3. Untrusted streams without a prior manifest cannot allocate more than max_chunks_per_session.
4. Speculative chunk allocations beyond manifest.chunk_count are immediately pruned upon
   manifest packet ingestion.
"""

import pytest
from tfp_client.lib.media.fountain_streamer import MediaDropletPacket, serialize_manifest_packet
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaManifest


def test_manifest_from_dict_bounds_validation():
    """Verify that MediaManifest.from_dict rejects inconsistent counts and sizes."""
    # Chunk count mismatch
    with pytest.raises(ValueError, match="chunk_count"):
        MediaManifest.from_dict({
            "manifest_id": "m1",
            "media_type": "text/plain",
            "total_size": 100,
            "chunk_count": 2,  # Claims 2 but only 1 hash provided
            "merkle_root": "root1",
            "chunk_hashes": ["hash1"],
            "chunk_sizes": [100],
        })

    # Total size mismatch
    with pytest.raises(ValueError, match="total_size"):
        MediaManifest.from_dict({
            "manifest_id": "m2",
            "media_type": "text/plain",
            "total_size": 250,  # Claims 250 but sum is 200
            "chunk_count": 2,
            "merkle_root": "root2",
            "chunk_hashes": ["h1", "h2"],
            "chunk_sizes": [100, 100],
        })


def test_receiver_single_transfer_bounds_rejects_flood():
    """
    Given a 1-chunk manifest, verify that emitting 100 out-of-bounds chunk_indices
    does not create any buffer allocations.
    """
    receiver = FountainStreamReceiver(symbol_size=256, verify_tag=False)

    manifest = MediaManifest(
        manifest_id="test_stream_single_chunk",
        media_type="text/plain",
        total_size=128,
        chunk_count=1,
        merkle_root="dummy_root",
        chunk_hashes=["hash0"],
        chunk_sizes=[128],
    )

    session_id = receiver.derive_session_id(manifest)
    manifest_bytes = serialize_manifest_packet(manifest, secret_key=receiver.secret_key)
    # Ingest manifest
    res = receiver.ingest_bytes(manifest_bytes)
    assert res == (-1, b"")
    assert session_id in receiver.received_manifests

    # Now emit 100 out-of-bounds packets with chunk_index in 1..100
    for bad_chunk_idx in range(1, 101):
        pkt = MediaDropletPacket(
            session_id=session_id,
            chunk_index=bad_chunk_idx,
            k=1,
            orig_len=128,
            symbol_size=256,
            seed=42 + bad_chunk_idx,
            payload=b"A" * 256,
        )
        res = receiver.ingest_packet(pkt)
        assert res is None

    # Crucial assertion: ZERO buffers or metadata allocated for bad_chunk_idx
    allocated_keys = [k for k in receiver._droplet_buffers if k[0] == session_id]
    assert len(allocated_keys) == 0
    assert len([k for k in receiver._chunk_meta if k[0] == session_id]) == 0


def test_receiver_pre_manifest_flood_bounded():
    """
    Verify that an untrusted stream without a manifest cannot allocate more than
    max_chunks_per_session distinct chunk indices.
    """
    max_chunks = 16
    receiver = FountainStreamReceiver(symbol_size=256, verify_tag=False, max_chunks_per_session=max_chunks)
    untrusted_session_id = 99999

    # Attempt to send packets across 50 distinct chunk indices (k=4 so packets remain in droplet buffers)
    for c_idx in range(50):
        pkt = MediaDropletPacket(
            session_id=untrusted_session_id,
            chunk_index=c_idx,
            k=4,
            orig_len=512,
            symbol_size=256,
            seed=1000 + c_idx,
            payload=b"X" * 256,
        )
        receiver.ingest_packet(pkt)

    tracked_chunks = {k[1] for k in receiver._droplet_buffers if k[0] == untrusted_session_id}
    assert len(tracked_chunks) == max_chunks
    assert max(tracked_chunks) == max_chunks - 1


def test_receiver_prunes_speculative_chunks_on_manifest_arrival():
    """
    Verify that when a manifest arrives, any speculative chunk buffers with
    chunk_index >= manifest.chunk_count are immediately pruned.
    """
    receiver = FountainStreamReceiver(symbol_size=256, verify_tag=False)

    manifest = MediaManifest(
        manifest_id="eventual_manifest",
        media_type="text/plain",
        total_size=100,
        chunk_count=1,
        merkle_root="eventual_root",
        chunk_hashes=["h0"],
        chunk_sizes=[100],
    )
    session_id = receiver.derive_session_id(manifest)

    # Ingest a valid chunk (chunk_index=0) and an out-of-bounds speculative chunk (chunk_index=5)
    pkt0 = MediaDropletPacket(session_id=session_id, chunk_index=0, k=2, orig_len=100, symbol_size=256, seed=1, payload=b"0"*256)
    pkt5 = MediaDropletPacket(session_id=session_id, chunk_index=5, k=2, orig_len=100, symbol_size=256, seed=2, payload=b"5"*256)
    receiver.ingest_packet(pkt0)
    receiver.ingest_packet(pkt5)

    assert (session_id, 0) in receiver._droplet_buffers
    assert (session_id, 5) in receiver._droplet_buffers

    # Now manifest arrives declaring chunk_count=1
    manifest_bytes = serialize_manifest_packet(manifest, secret_key=receiver.secret_key)
    receiver.ingest_bytes(manifest_bytes)

    # (session_id, 0) should remain, while (session_id, 5) must be pruned
    assert (session_id, 0) in receiver._droplet_buffers
    assert (session_id, 5) not in receiver._droplet_buffers
    assert (session_id, 5) not in receiver._chunk_meta
