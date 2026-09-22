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


@pytest.mark.parametrize("override_manifest_id", [False, True])
def test_explicit_session_can_complete_again_after_reset(override_manifest_id):
    manifest, chunks, _ = MediaStreamPackager(32, 64, 64).package(b"A" * 128)
    if override_manifest_id:
        manifest.manifest_id = 1001
    receiver = FountainStreamReceiver(symbol_size=32)
    packets = list(FountainStreamer(symbol_size=32).stream_manifest(manifest, chunks, session_id=1001))
    for _ in range(2):
        for packet in packets:
            receiver.ingest_packet(packet)
        assert receiver.is_complete(manifest, session_id=1001)
        assert receiver.assemble(manifest, session_id=1001) == b"A" * 128
        receiver.reset(1001)


def test_explicit_session_checkpoint_survives_restart(tmp_path):
    manifest, chunks, _ = MediaStreamPackager(32, 64, 64).package(b"A" * 128)
    original_id = manifest.manifest_id
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    for packet in FountainStreamer(symbol_size=32).stream_manifest(manifest, chunks, session_id=1001):
        receiver.ingest_packet(packet)
    assert receiver.is_complete(manifest, session_id=1001)
    assert manifest.manifest_id == original_id
    restarted = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert restarted.assemble() == b"A" * 128
    assert restarted.assemble(manifest, session_id=1001) == b"A" * 128
    restarted.reset(1001)
    assert restarted.latest_manifest is None
    assert not restarted.is_complete()


def test_checkpoint_session_override_is_authenticated(tmp_path):
    _, sid = checkpoint(tmp_path)
    session = tmp_path / f"session_{sid}"
    record_path = session / "manifest.json"
    record = json.loads(record_path.read_bytes())
    record["session_id"] = 1001
    record_path.write_text(json.dumps(record))
    session.rename(tmp_path / "session_1001")
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert receiver.received_manifests == {}


def test_older_authenticated_checkpoint_without_explicit_session_still_loads(tmp_path):
    import hmac

    _, sid = checkpoint(tmp_path)
    path = tmp_path / f"session_{sid}" / "manifest.json"
    record = json.loads(path.read_bytes())
    record.pop("session_id")
    record.pop("auth_tag")
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["auth_tag"] = hmac.new(b"tfp-default-streaming-salt", encoded, hashlib.sha3_256).hexdigest()
    path.write_text(json.dumps(record))
    restarted = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert restarted.assemble() == b"A" * 128


@pytest.mark.parametrize("session_id", [-1, 2**32, True, "1001"])
def test_invalid_explicit_session_cannot_allocate_checkpoint(tmp_path, session_id):
    manifest, _, _ = MediaStreamPackager(32, 64, 64).package(b"A" * 128)
    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert receiver.ingest_manifest(manifest, session_id=session_id) is None
    assert receiver.received_manifests == {}
    assert list(tmp_path.iterdir()) == []


def test_newest_checkpoint_remains_default_after_restart(tmp_path):
    import os
    import time

    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    for payload, age in [(b"A" * 128, 10), (b"B" * 128, 0)]:
        manifest, chunks, _ = MediaStreamPackager(32, 64, 64).package(payload)
        sid = receiver.ingest_manifest(manifest)
        for packet in FountainStreamer(symbol_size=32).stream_manifest(manifest, chunks):
            receiver.ingest_packet(packet)
        timestamp = time.time() - age
        os.utime(tmp_path / f"session_{sid}", (timestamp, timestamp))
    assert receiver.assemble() == b"B" * 128
    restarted = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    assert restarted.assemble() == b"B" * 128
    assert restarted.reconstructed_chunks == receiver.reconstructed_chunks


def test_expired_checkpoints_are_pruned_across_restarts(tmp_path):
    import os
    import time

    for payload in (b"A" * 128, b"B" * 128, b"C" * 128):
        receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path, max_sessions=1)
        manifest, _, _ = MediaStreamPackager(32, 64, 64).package(payload)
        sid = receiver.ingest_manifest(manifest)
        assert len(list(tmp_path.glob("session_*"))) == 1
        timestamp = time.time() - 1000
        os.utime(tmp_path / f"session_{sid}", (timestamp, timestamp))


def test_restart_prunes_excess_valid_sessions_but_preserves_unknown_context(tmp_path):
    import os
    import time

    receiver = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path)
    valid_sessions = []
    for index in range(3):
        manifest, _, _ = MediaStreamPackager(32, 64, 64).package(bytes([index]) * 128)
        sid = receiver.ingest_manifest(manifest)
        valid_sessions.append(sid)
        timestamp = time.time() - 10 + index
        os.utime(tmp_path / f"session_{sid}", (timestamp, timestamp))
    legacy = tmp_path / "session_7"
    legacy.mkdir()
    (legacy / "manifest.json").write_text("{}")
    foreign = FountainStreamReceiver(symbol_size=32, secret_key=b"another-key", checkpoint_dir=tmp_path)
    manifest, _, _ = MediaStreamPackager(32, 64, 64).package(b"foreign" * 20)
    foreign_sid = foreign.ingest_manifest(manifest)
    foreign_dir = tmp_path / f"session_{foreign_sid}"
    timestamp = time.time() - 1000
    os.utime(foreign_dir, (timestamp, timestamp))

    restarted = FountainStreamReceiver(symbol_size=32, checkpoint_dir=tmp_path, max_sessions=1)
    assert list(restarted.received_manifests) == [valid_sessions[-1]]
    assert {path.name for path in tmp_path.iterdir()} == {
        f"session_{valid_sessions[-1]}", legacy.name, foreign_dir.name,
    }
