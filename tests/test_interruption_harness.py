# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Persistence Interruption Harness for TFP Node & Receiver Checkpoints.

Adversarially validates that interrupted operations (simulating power failure,
SIGKILL, un-fsynced write aborts, and disk exhaustion) cannot leave the node
or receiver in an unrecoverable, inconsistent, or corrupted state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from tfp_client.lib.media.fountain_streamer import FountainStreamer, MediaDropletPacket
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaManifest, MediaStreamPackager
from tfp_core_v4.bulletin import import_bulletin_package, prepare_bulletin_package
from tfp_core_v4.node import TFPNode


class ConnectionWrapper:
    """Delegating wrapper around sqlite3.Connection to inject crash faults."""

    def __init__(self, real_conn, crash_on_commit: bool = False, crash_on_chunks: bool = False):
        self._conn = real_conn
        self.crash_on_commit = crash_on_commit
        self.crash_on_chunks = crash_on_chunks

    def __getattr__(self, item):
        return getattr(self._conn, item)

    def commit(self):
        if self.crash_on_commit:
            raise InterruptedError("SIMULATED_POWER_CUT_BEFORE_COMMIT")
        return self._conn.commit()

    def executemany(self, sql, params):
        if self.crash_on_chunks and "INSERT OR REPLACE INTO chunks" in sql:
            raise sqlite3.OperationalError("disk I/O error (simulated out of space)")
        return self._conn.executemany(sql, params)

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def cursor(self):
        return self._conn.cursor()

    def close(self):
        return self._conn.close()


def test_node_store_bulletin_crash_before_commit_rolls_back_cleanly(tmp_path: Path):
    """
    Simulate a power cut or crash immediately prior to SQLite commit during store_bulletin.
    Verifies that no partial data is visible, memory caches remain isolated,
    and a subsequent retry succeeds cleanly.
    """
    db_file = tmp_path / "crash_before_commit.db"
    node = TFPNode(db_path=db_file)

    payload = b"CRITICAL ADVISORY: Boil water before use."
    bulletin_id = "BULLETIN-INTERRUPT-001"
    rev = 1

    real_connect = sqlite3.connect

    def crashing_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        return ConnectionWrapper(conn, crash_on_commit=True)

    with patch("sqlite3.connect", crashing_connect):
        with pytest.raises(InterruptedError, match="SIMULATED_POWER_CUT"):
            node.store_bulletin(
                bulletin_id=bulletin_id,
                revision=rev,
                data=payload,
                title="Boil Water Notice",
            )

    # Check database state directly: should be completely rolled back
    verify_conn = sqlite3.connect(str(db_file))
    cur = verify_conn.cursor()
    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"

    cur.execute("SELECT COUNT(*) FROM bulletins")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM recipes")
    assert cur.fetchone()[0] == 0

    cur.execute("SELECT COUNT(*) FROM chunks")
    assert cur.fetchone()[0] == 0
    verify_conn.close()

    # Verify that re-opening the node on a fresh instance recovers cleanly
    recovered_node = TFPNode(db_path=db_file)
    assert recovered_node.get_bulletin(bulletin_id, revision=rev) is None

    # Now retry the operation without crash: it must succeed idempotently
    recipe = recovered_node.store_bulletin(
        bulletin_id=bulletin_id,
        revision=rev,
        data=payload,
        title="Boil Water Notice",
    )
    assert recipe is not None

    meta, content = recovered_node.get_bulletin(bulletin_id, revision=rev)
    assert meta["bulletin_id"] == bulletin_id
    assert content == payload


def test_node_crash_during_chunk_persistence_preserves_database_integrity(tmp_path: Path):
    """
    Simulate an I/O error or disk-full during chunk insertions in _persist_content.
    Verifies that the entire transaction aborts without leaving orphan chunk rows.
    """
    db_file = tmp_path / "crash_chunk_io.db"
    node = TFPNode(db_path=db_file)

    payload = b"X" * 4096  # Multiple chunks under FastCDC
    bulletin_id = "BULLETIN-MULTI-CHUNK"

    real_connect = sqlite3.connect

    def crashing_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        return ConnectionWrapper(conn, crash_on_chunks=True)

    with patch("sqlite3.connect", crashing_connect):
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            node.store_bulletin(
                bulletin_id=bulletin_id,
                revision=1,
                data=payload,
                title="Large Bulletin",
            )

    # Reconnect and verify integrity
    verify_conn = sqlite3.connect(str(db_file))
    cur = verify_conn.cursor()
    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    cur.execute("SELECT COUNT(*) FROM chunks")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM bulletins")
    assert cur.fetchone()[0] == 0
    verify_conn.close()


def test_receiver_truncated_manifest_checkpoint_recovery(tmp_path: Path):
    """
    Simulate a crash while writing manifest.json in checkpoint_dir.
    The receiver on restart must cleanly ignore the partial manifest
    without raising JSONDecodeError or crashing the process.
    """
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    session_id = 0xA1B2C3D4
    sdir = checkpoint_dir / f"session_{session_id}"
    sdir.mkdir(parents=True, exist_ok=True)

    # Write truncated/malformed manifest
    (sdir / "manifest.json").write_text('{"manifest_id": "bad', encoding="utf-8")

    # Also place a chunk in the directory
    (sdir / "chunk_0_12345678.dat").write_bytes(b"partial chunk data")

    # Receiver startup must not crash
    receiver = FountainStreamReceiver(checkpoint_dir=checkpoint_dir)
    assert session_id not in receiver.received_manifests
    assert len(receiver.reconstructed_chunks_by_session) == 0


def test_receiver_truncated_chunk_checkpoint_recovery(tmp_path: Path):
    """
    Simulate a power failure while writing a chunk checkpoint file.
    The chunk file has fewer bytes than declared in the manifest.
    On restart, the receiver must discard the truncated chunk file,
    re-read surviving valid chunks, and accept retransmission.
    """
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Create authentic 2-chunk payload via MediaStreamPackager
    packager = MediaStreamPackager(min_chunk_size=256, target_chunk_size=512, max_chunk_size=512)
    data = (b"CHUNK_0_BYTES_" * 37)[:512] + (b"CHUNK_1_BYTES_" * 37)[:512]
    manifest, chunks, _ = packager.package(data)
    assert manifest.chunk_count == 2
    session_id = FountainStreamReceiver.derive_session_id(manifest)

    # Process 1: Setup checkpoint session with valid manifest and chunk 0
    rx1 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=checkpoint_dir)
    assert rx1.ingest_manifest(manifest) == session_id
    rx1._save_chunk_checkpoint(session_id, 0, chunks[0])
    del rx1

    # Write chunk 1: truncated (only 50 bytes instead of 512, simulating crash during write)
    sdir = checkpoint_dir / f"session_{session_id}"
    chunk1_hash = manifest.chunk_hashes[1]
    truncated_cfile = sdir / f"chunk_1_{chunk1_hash}.dat"
    truncated_cfile.write_bytes(b"B" * 50)

    # Start receiver 2: must load chunk 0, discard truncated chunk 1
    receiver = FountainStreamReceiver(symbol_size=256, checkpoint_dir=checkpoint_dir)
    assert session_id in receiver.received_manifests
    recovered_chunks = receiver.reconstructed_chunks_by_session.get(session_id, {})
    assert 0 in recovered_chunks
    assert recovered_chunks[0] == chunks[0]
    assert 1 not in recovered_chunks
    assert receiver.is_complete(manifest, session_id=session_id) is False

    # The truncated file should have been unlinked or ignored
    # Now provide genuine chunk 1 droplets over the stream
    streamer = FountainStreamer(symbol_size=256)
    c1_droplets = streamer.package_chunk_packets(chunks[1], chunk_index=1, session_id=session_id, redundancy=0.5)
    for pkt in c1_droplets:
        receiver.ingest_packet(pkt)
        if receiver.is_complete(manifest, session_id=session_id):
            break

    assert receiver.is_complete(manifest, session_id=session_id) is True
    assembled = receiver.assemble(manifest, session_id=session_id)
    assert assembled == data


def test_receiver_corrupted_payload_checkpoint_recovery(tmp_path: Path):
    """
    Simulate bit rot or malicious modification of a chunk file where the file size
    matches expected size, but bytes fail SHA3-256 verification.
    The receiver must detect the hash mismatch, unlink the corrupt file, and not admit it.
    """
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    packager = MediaStreamPackager(min_chunk_size=128, target_chunk_size=256, max_chunk_size=256)
    data = (b"Authentic payload bytes." * 15)[:256]
    manifest, chunks, _ = packager.package(data)
    session_id = FountainStreamReceiver.derive_session_id(manifest)

    # Process 1: Setup checkpoint session with valid manifest
    rx1 = FountainStreamReceiver(symbol_size=256, checkpoint_dir=checkpoint_dir)
    assert rx1.ingest_manifest(manifest) == session_id
    del rx1

    # Simulate chunk corruption: same length (256 bytes), completely corrupted content
    sdir = checkpoint_dir / f"session_{session_id}"
    chunk_hash = manifest.chunk_hashes[0]
    corrupt_cfile = sdir / f"chunk_0_{chunk_hash}.dat"
    corrupt_cfile.write_bytes(b"Z" * 256)

    receiver = FountainStreamReceiver(symbol_size=256, checkpoint_dir=checkpoint_dir)
    recovered = receiver.reconstructed_chunks_by_session.get(session_id, {})
    assert 0 not in recovered
    assert receiver.is_complete(manifest, session_id=session_id) is False
    # Corrupt file must be deleted upon failed verification
    assert not corrupt_cfile.exists()


def test_interrupted_package_preparation_safe_recovery(tmp_path: Path):
    """
    Simulate an error or abort during prepare_bulletin_package with overwrite=True.
    Verifies that the original package is preserved in its previous backup directory.
    """
    pkg_dir = tmp_path / "bulletin_pkg"
    prepare_bulletin_package(
        bulletin_id="ORIGINAL-001",
        revision=1,
        title="Original Title",
        content_text="Original content text.",
        output_dir=pkg_dir,
    )
    assert (pkg_dir / "bulletin.txt").read_text(encoding="utf-8") == "Original content text."

    # Now attempt replacement with a simulated crash in the middle
    original_write = Path.write_text

    def failing_write(self_path, text, encoding="utf-8"):
        if "instructions.txt" in str(self_path):
            raise OSError("Simulated disk write failure on instructions.txt")
        return original_write(self_path, text, encoding=encoding)

    with patch.object(Path, "write_text", failing_write):
        with pytest.raises(OSError, match="Simulated disk write failure"):
            prepare_bulletin_package(
                bulletin_id="REPLACED-002",
                revision=2,
                title="Replaced Title",
                content_text="Replaced content text.",
                output_dir=pkg_dir,
                overwrite=True,
            )

    # The original package directory should still exist intact!
    assert pkg_dir.exists()
    assert (pkg_dir / "bulletin.txt").read_text(encoding="utf-8") == "Original content text."
    metadata = json.loads((pkg_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["bulletin_id"] == "ORIGINAL-001"
