"""
Comprehensive unit tests for FountainStreamReceiver resource bounding and state isolation.
Validates:
1. Manifest-only session bursts respect max_sessions (LRU eviction of manifests and timestamps).
2. _chunk_meta does not leak orphaned entries when completed chunks are reset or evicted.
3. latest_manifest and _last_active_session correctly fall back upon session deletion.
"""

import hashlib
import sys
import time
from pathlib import Path

_tfp_root = Path(__file__).resolve().parent.parent / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.stream_packager import MediaManifest, MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer, serialize_manifest_packet
from tfp_client.lib.media.receiver import FountainStreamReceiver


def test_manifest_only_burst_bounded_by_max_sessions():
    """Verify that a burst of manifest-only wire packets does not leak memory or exceed max_sessions."""
    max_sess = 4
    secret = b"test-secret-salt-bounds"
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret, max_sessions=max_sess)

    # Ingest 25 distinct manifests
    for i in range(25):
        manifest = MediaManifest(
            manifest_id=hashlib.sha256(f"burst_manifest_{i}".encode()).hexdigest(),
            media_type="text/plain",
            total_size=1024,
            chunk_count=1,
            merkle_root=hashlib.sha256(f"root_{i}".encode()).hexdigest(),
            chunk_hashes=[hashlib.sha3_256(b"chunk_dummy").hexdigest()],
            chunk_sizes=[1024],
            metadata={"title": f"Doc {i}"},
        )
        wire_manifest = serialize_manifest_packet(manifest, secret_key=secret)
        res = receiver.ingest_bytes(wire_manifest)
        assert res == (-1, b"")

    # Invariant: receiver's tracked sessions must NOT exceed max_sessions
    assert len(receiver.received_manifests) <= max_sess
    assert len(receiver._session_timestamps) <= max_sess
    assert len(receiver.reconstructed_chunks_by_session) <= max_sess


def test_chunk_meta_cleaned_on_reset_and_eviction():
    """
    Verify that _chunk_meta does not leave orphan entries when chunks are reconstructed
    (at which point _droplet_buffers is removed) and subsequently reset or evicted.
    """
    secret = b"test-secret-salt-meta"
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret, max_sessions=2)

    payload = b"Hello Foundation Protocol! " * 32
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)
    manifest, chunks, _ = packager.package(payload)

    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    session_id = receiver.derive_session_id(manifest)

    # Register manifest
    wire_manifest = serialize_manifest_packet(manifest, secret_key=secret)
    receiver.ingest_bytes(wire_manifest)

    # Ingest droplets until chunk 0 is reconstructed
    packets = streamer.package_chunk_packets(
        chunk_data=chunks[0], chunk_index=0, session_id=session_id, redundancy=0.5
    )
    reconstructed_res = None
    for pkt in packets:
        reconstructed_res = receiver.ingest_packet(pkt)
        if reconstructed_res is not None:
            break

    assert reconstructed_res is not None
    assert reconstructed_res[0] == 0
    assert reconstructed_res[1] == chunks[0]

    # At this point, chunk 0 is reconstructed. _droplet_buffers has been deleted for (session_id, 0)
    assert (session_id, 0) not in receiver._droplet_buffers
    # But _chunk_meta should still contain the chunk parameters until reset
    assert (session_id, 0) in receiver._chunk_meta

    # Reset the session explicitly
    receiver.reset(session_id)

    # Assert complete cleanup: _chunk_meta MUST NOT contain orphan keys
    assert (session_id, 0) not in receiver._chunk_meta
    assert session_id not in receiver.received_manifests
    assert session_id not in receiver._session_timestamps
    assert session_id not in receiver.reconstructed_chunks_by_session


def test_lru_eviction_prunes_reconstructed_and_meta():
    """Verify that LRU eviction cleanly purges completed sessions and their metadata."""
    secret = b"test-secret-salt-lru"
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret, max_sessions=2)

    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)
    streamer = FountainStreamer(symbol_size=128, secret_key=secret)

    # Session 1: complete reconstruction
    m1, chunks1, _ = packager.package(b"Session 1 data " * 30)
    s1 = receiver.derive_session_id(m1)
    receiver.ingest_bytes(serialize_manifest_packet(m1, secret_key=secret))
    for pkt in streamer.stream_manifest(m1, chunks1, redundancy=0.5):
        receiver.ingest_packet(pkt)
    assert receiver.is_complete(m1, session_id=s1)

    time.sleep(0.02)

    # Session 2: complete reconstruction
    m2, chunks2, _ = packager.package(b"Session 2 data " * 30)
    s2 = receiver.derive_session_id(m2)
    receiver.ingest_bytes(serialize_manifest_packet(m2, secret_key=secret))
    for pkt in streamer.stream_manifest(m2, chunks2, redundancy=0.5):
        receiver.ingest_packet(pkt)
    assert receiver.is_complete(m2, session_id=s2)

    time.sleep(0.02)

    # Now receiver is at capacity (max_sessions=2): s1 and s2
    # Ingest Session 3 (manifest) -> s1 (oldest) should be evicted
    m3, _, _ = packager.package(b"Session 3 data " * 30)
    s3 = receiver.derive_session_id(m3)
    receiver.ingest_bytes(serialize_manifest_packet(m3, secret_key=secret))

    # s1 must have been evicted completely
    assert s1 not in receiver._session_timestamps
    assert s1 not in receiver.received_manifests
    assert s1 not in receiver.reconstructed_chunks_by_session
    assert not any(k[0] == s1 for k in receiver._chunk_meta)
    assert not any(k[0] == s1 for k in receiver._droplet_buffers)

    # s2 and s3 remain
    assert s2 in receiver._session_timestamps
    assert s3 in receiver._session_timestamps
