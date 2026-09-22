# SPDX-License-Identifier: Apache-2.0
import hashlib
import json

import pytest
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaStreamPackager


@pytest.mark.parametrize("manifest_text", [None, "{broken", "{}"])
def test_untrusted_checkpoint_cannot_restore_unbounded_chunks(tmp_path, manifest_text):
    session = tmp_path / "session_7"
    session.mkdir()
    if manifest_text is not None:
        (session / "manifest.json").write_text(manifest_text)
    data = b"checkpoint"
    digest = hashlib.sha3_256(data).hexdigest()
    for idx in range(100):
        (session / f"chunk_{idx}_{digest}.dat").write_bytes(data)
    receiver = FountainStreamReceiver(max_chunks_per_session=2, checkpoint_dir=tmp_path)
    assert sum(len(chunks) for chunks in receiver.reconstructed_chunks_by_session.values()) <= 2
    assert receiver.reconstructed_chunks_by_session == {}  # Missing context is not accepted content.


def checkpoint(tmp_path):
    manifest, chunks, _ = MediaStreamPackager(32, 64, 64).package(b"A" * 128)
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    sid = receiver.ingest_manifest(manifest)
    for packet in FountainStreamer(symbol_size=32).stream_manifest(manifest, chunks):
        receiver.ingest_packet(packet)
    return manifest, sid


def test_checkpoint_context_must_match_receiver(tmp_path):
    checkpoint(tmp_path)
    receiver = FountainStreamReceiver(symbol_size=64, checkpoint_dir=tmp_path)
    assert receiver.reconstructed_chunks_by_session == {}
    assert receiver.received_manifests == {}


def test_checkpoint_indices_must_match_manifest(tmp_path):
    _manifest, sid = checkpoint(tmp_path)
    session = tmp_path / f"session_{sid}"
    chunk = next(session.glob("chunk_0_*.dat"))
    for idx in (-1, 2, 100):
        (session / chunk.name.replace("chunk_0_", f"chunk_{idx}_")).write_bytes(chunk.read_bytes())
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert set(receiver.reconstructed_chunks_by_session[sid]) == {0, 1}


def test_over_limit_valid_manifest_is_not_downgraded_to_speculative_restore(tmp_path):
    checkpoint(tmp_path)
    receiver = FountainStreamReceiver(symbol_size=32, max_chunks_per_session=1, checkpoint_dir=tmp_path)
    assert receiver.reconstructed_chunks_by_session == {}
    assert receiver.received_manifests == {}


def test_changed_authentication_context_is_not_restored(tmp_path):
    checkpoint(tmp_path)
    receiver = FountainStreamReceiver(symbol_size=32, secret_key=b"different-key", checkpoint_dir=tmp_path)
    assert receiver.reconstructed_chunks_by_session == {}


def test_oversized_chunk_is_rejected_before_reading(tmp_path, monkeypatch):
    from pathlib import Path
    _manifest, sid = checkpoint(tmp_path)
    chunk = next((tmp_path / f"session_{sid}").glob("chunk_0_*.dat"))
    chunk.write_bytes(b"X" * 10_000)
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != chunk, "Oversized checkpoint must not be read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert 0 not in receiver.reconstructed_chunks_by_session[sid]


def test_explicit_session_can_complete_again_after_reset():
    manifest, chunks, _ = MediaStreamPackager(32, 64, 64).package(b"A" * 128)
    manifest.manifest_id = 1001
    receiver = FountainStreamReceiver(symbol_size=32)
    packets = list(FountainStreamer(symbol_size=32).stream_manifest(manifest, chunks, session_id=1001))
    for _ in range(2):
        for packet in packets:
            receiver.ingest_packet(packet)
        assert receiver.is_complete(manifest, session_id=1001)
        assert receiver.assemble(manifest, session_id=1001) == b"A" * 128
        receiver.reset(1001)
