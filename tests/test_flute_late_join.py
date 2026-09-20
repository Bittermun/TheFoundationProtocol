"""
FLUTE (RFC 6726 Section 3.3) Interleaved Manifest & Late-Joining Receiver Tests.

Verifies:
1. stream_manifest_wire_packets interleaves manifest announcements throughout droplet streams.
2. A receiver that misses all opening manifests still recovers the manifest from interleaved packets and completes transfer.
3. Bit-exact assembly succeeds even with late joiners.
"""

import sys
from pathlib import Path

_tfp_root = Path(__file__).resolve().parent.parent / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.media.fountain_streamer import FountainStreamer, MANIFEST_MAGIC
from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.receiver import FountainStreamReceiver


def test_flute_manifest_interleaving_distribution():
    """Verify that manifests are transmitted initially, periodically, and at stream close."""
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=1024)
    data = b"FLUTE Protocol Periodic Announcement Test Data " * 40
    manifest, chunks, _ = packager.package(data)

    streamer = FountainStreamer(symbol_size=128, secret_key=b"flute-key")
    wire_packets = list(
        streamer.stream_manifest_wire_packets(
            manifest,
            chunks,
            redundancy=0.50,
            repeat_manifest=2,
            manifest_interval=6,
        )
    )

    manifest_indices = [i for i, pkt in enumerate(wire_packets) if pkt.startswith(MANIFEST_MAGIC)]
    # Must have initial manifests at 0, 1
    assert 0 in manifest_indices
    assert 1 in manifest_indices
    # Must have interleaved manifests throughout
    assert any(i > 2 for i in manifest_indices)
    # Must have closing manifest
    assert manifest_indices[-1] == len(wire_packets) - 1


def test_late_joining_receiver_reconstruction():
    """
    Simulate a late-joining receiver:
    Drop the first 10 packets completely (missing all initial manifests and initial droplets).
    Receiver must latch onto an interleaved manifest and assemble bit-exact payload.
    """
    packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=2048)
    original_data = b"Critical Offline Disaster Response Directive: Emergency Mesh Deployment." * 30
    manifest, chunks, _ = packager.package(original_data)

    secret = b"late-join-secret-salt"
    streamer = FountainStreamer(symbol_size=128, secret_key=secret)
    receiver = FountainStreamReceiver(symbol_size=128, secret_key=secret)

    wire_packets = list(
        streamer.stream_manifest_wire_packets(
            manifest,
            chunks,
            redundancy=1.5,  # Broadcast redundancy so late joiner gets enough rateless repair droplets
            repeat_manifest=3,
            manifest_interval=8,
        )
    )

    # Late joiner starts listening from packet index 8 (missing all 3 initial manifests)
    late_stream = wire_packets[8:]
    assert not late_stream[0].startswith(MANIFEST_MAGIC)  # starts on data droplet

    for raw in late_stream:
        receiver.ingest_bytes(raw)

    session_id = receiver.derive_session_id(manifest)
    assert receiver.is_complete(manifest, session_id=session_id)
    recovered = receiver.assemble(manifest, session_id=session_id)
    assert recovered == original_data
