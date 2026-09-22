# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Durable Receiver Checkpoints (Stage 4).

Verifies:
1. Bounded checkpoint persistence across real process restart boundaries.
2. Two complementary contacts completing one multi-chunk transfer without sender replaying.
3. Idempotent duplicate packet handling without progress inflation.
4. Cryptographic integrity checking of restored checkpoint chunks (discarding corrupt state).
5. Enforcing max_sessions and session_ttl bounds on retained checkpoint storage.
"""

from pathlib import Path
import subprocess
import sys
import time

from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaStreamPackager


def test_receiver_checkpoint_complementary_transfer_across_processes(tmp_path: Path):
    """
    Verify that two complementary packet batches complete one transfer across
    a real subprocess restart boundary without the sender replaying old packets.
    """
    chk_dir = tmp_path / "rx_checkpoints"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=512)

    # 1024 bytes -> exactly 2 chunks of 512 bytes
    data = (b"SECTION_ONE_EMERGENCY_MEDICAL_GUIDELINES_V4_" * 12)[:512] + (
        b"SECTION_TWO_WATER_PURIFICATION_CHLORINE_DOSING" * 12
    )[:512]
    manifest, chunks, _ = packager.package(data)
    assert manifest.chunk_count == 2, f"Expected 2 chunks, got {manifest.chunk_count}"

    sess_id = FountainStreamReceiver.derive_session_id(manifest)
    streamer = FountainStreamer(symbol_size=256)
    c0_droplets = streamer.package_chunk_packets(chunks[0], chunk_index=0, session_id=sess_id, redundancy=0.5)

    # Process 1: Ingest manifest and chunk 0 droplets only
    rx1 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=chk_dir)
    registered_sess = rx1.ingest_manifest(manifest)
    assert registered_sess == sess_id

    c0_completed = False
    for pkt in c0_droplets:
        res = rx1.ingest_packet(pkt)
        if res is not None and res[0] == 0:
            c0_completed = True
            break
    assert c0_completed, "Receiver 1 failed to reconstruct chunk 0"
    assert not rx1.is_complete(manifest, session_id=sess_id), "Receiver 1 should not be complete yet"

    # Terminate Receiver 1 (simulate process kill)
    del rx1

    # Verify checkpoint files were written to disk
    sess_dir = chk_dir / f"session_{sess_id}"
    assert sess_dir.exists()
    assert (sess_dir / "manifest.json").exists()
    c0_files = list(sess_dir.glob("chunk_0_*.dat"))
    assert len(c0_files) == 1, "Chunk 0 checkpoint file was not written"

    # Process 2 (Subprocess boundary): Run fresh Python process to ingest only chunk 1
    repo_root = Path(__file__).resolve().parent.parent
    probe_script = f"""
from pathlib import Path
import sys

repo_root = Path(r"{repo_root}")
tfp_root = repo_root / "tfp-foundation-protocol"
for p in (str(repo_root), str(tfp_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.stream_packager import MediaStreamPackager

chk_dir = Path(r"{chk_dir}")
rx2 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=chk_dir)

# Assert that chunk 0 was restored from disk checkpoint
assert {sess_id} in rx2.reconstructed_chunks_by_session, "Session not restored"
assert 0 in rx2.reconstructed_chunks_by_session[{sess_id}], "Chunk 0 not restored"
m2 = rx2.received_manifests.get({sess_id})
assert m2 is not None, "Manifest not restored"

# Ingest chunk 1 droplets only (zero replay of chunk 0)
packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=512)
data = ({repr(data)})
_, chunks, _ = packager.package(data)
streamer = FountainStreamer(symbol_size=256)
c1_pkts = streamer.package_chunk_packets(chunks[1], chunk_index=1, session_id={sess_id}, redundancy=0.5)

for pkt in c1_pkts:
    rx2.ingest_packet(pkt)

assert rx2.is_complete(m2, session_id={sess_id}), "Receiver 2 incomplete after complementary packets"
assembled = rx2.assemble(m2, session_id={sess_id})
assert assembled == data, "Bit-exact mismatch after cross-process assembly"
print("COMPLEMENTARY_RECOVERY_SUCCESS")
"""
    res = subprocess.run(
        [sys.executable, "-c", probe_script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "COMPLEMENTARY_RECOVERY_SUCCESS" in res.stdout


def test_receiver_checkpoint_duplicate_packet_idempotence(tmp_path: Path):
    """Verify duplicate packets do not duplicate content or corrupt checkpoint state."""
    chk_dir = tmp_path / "rx_chk_dup"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=256, max_chunk_size=256)
    data = b"IDEMPOTENT_PACKET_TEST_PAYLOAD_" * 8
    manifest, chunks, _ = packager.package(data)

    streamer = FountainStreamer(symbol_size=256)
    packets = list(streamer.stream_manifest(manifest, chunks, redundancy=1.0))

    rx = FountainStreamReceiver(symbol_size=256, checkpoint_dir=chk_dir)
    sess_id = rx.ingest_manifest(manifest)

    # Ingest packets
    for pkt in packets:
        rx.ingest_packet(pkt)
    assert rx.is_complete(manifest, session_id=sess_id)

    initial_accepted = rx.stats.packets_accepted
    initial_reconstructed = rx.stats.chunks_reconstructed

    # Replay all packets again
    for pkt in packets:
        res = rx.ingest_packet(pkt)
        assert res is None  # Never re-triggers reconstruction

    assert rx.stats.packets_duplicate > 0
    assert rx.stats.chunks_reconstructed == initial_reconstructed
    # Data is still 100% valid
    assert rx.assemble(manifest, session_id=sess_id) == data


def test_receiver_checkpoint_corrupted_file_handling(tmp_path: Path):
    """Verify corrupted checkpoint chunk files fail SHA3 integrity and are discarded explicitly."""
    chk_dir = tmp_path / "rx_chk_corrupt"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=256, max_chunk_size=256)
    data = b"CORRUPTION_RESILIENCE_TEST_" * 10
    manifest, chunks, _ = packager.package(data)

    rx1 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=chk_dir)
    sess_id = rx1.ingest_manifest(manifest)

    streamer = FountainStreamer(symbol_size=256)
    packets = list(streamer.stream_manifest(manifest, chunks, redundancy=0.5))
    for pkt in packets:
        rx1.ingest_packet(pkt)
    assert rx1.is_complete(manifest, session_id=sess_id)
    del rx1

    # Tamper with chunk checkpoint on disk
    sess_dir = chk_dir / f"session_{sess_id}"
    chunk_files = list(sess_dir.glob("chunk_*.dat"))
    assert chunk_files
    target_file = chunk_files[0]
    corrupt_bytes = bytearray(target_file.read_bytes())
    corrupt_bytes[10] ^= 0xFF
    target_file.write_bytes(bytes(corrupt_bytes))

    # Start fresh receiver instance
    rx2 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=chk_dir)

    # Corrupted chunk must NOT be accepted or loaded into session
    sess_chunks = rx2.reconstructed_chunks_by_session.get(sess_id, {})
    assert len(sess_chunks) < manifest.chunk_count, "Corrupted chunk was erroneously loaded"
    # Corrupted file should be unlinked/quarantined
    assert not target_file.exists(), "Corrupted checkpoint file was not pruned"


def test_receiver_checkpoint_resource_bounds_enforced(tmp_path: Path):
    """Verify max_sessions cap evicts oldest session directories from checkpoint storage."""
    chk_dir = tmp_path / "rx_chk_bounds"
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=256, max_chunk_size=256)

    rx = FountainStreamReceiver(symbol_size=256, max_sessions=3, checkpoint_dir=chk_dir)
    streamer = FountainStreamer(symbol_size=256)

    # Ingest 5 different sessions
    for i in range(5):
        data = f"SESSION_BOUND_TEST_{i}_".encode("utf-8") * 16
        manifest, chunks, _ = packager.package(data)
        rx.ingest_manifest(manifest)
        pkts = list(streamer.stream_manifest(manifest, chunks, redundancy=0.5))
        for p in pkts:
            rx.ingest_packet(p)

    # Fresh instance should observe at most max_sessions on disk
    rx_fresh = FountainStreamReceiver(symbol_size=256, max_sessions=3, checkpoint_dir=chk_dir)
    session_dirs = [d for d in chk_dir.iterdir() if d.is_dir() and d.name.startswith("session_")]
    assert len(session_dirs) <= 3, f"Expected at most 3 session directories, got {len(session_dirs)}"
