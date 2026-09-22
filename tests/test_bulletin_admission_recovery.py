# SPDX-License-Identifier: Apache-2.0
"""Acceptance failures must leave the previously accepted information intact."""
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator

from tfp_core_v4.bulletin import import_bulletin_package, prepare_bulletin_package
from tfp_core_v4.node import TFPNode


def signed_package(path, *, revision=1, key=None, title="Original headline", body="An unseen bulletin body."):
    return prepare_bulletin_package("admission-test", revision, title, body, path,
                                    private_key=key or Ed25519PrivateKey.generate())


def altered_audio(package, output, **updates):
    packet = AFSKDemodulator().decode_wav((package / "broadcast.wav").read_bytes())[0]
    wire = json.loads(packet)
    wire.update(updates)
    output.write_bytes(AFSKModulator().synthesize_wav(json.dumps(wire).encode()))
    return output


@pytest.mark.parametrize("changes", [{"sig": "00" * 64}, {"title": "Forged headline"}, {"rev": 2}])
def test_failed_verification_cannot_replace_accepted_bulletin(tmp_path, changes):
    package = tmp_path / "package"
    signed_package(package)
    node = TFPNode(db_path=tmp_path / "node.db")
    accepted = import_bulletin_package(package, node)
    before = node.get_bulletin("admission-test")
    tampered = altered_audio(package, tmp_path / "tampered.wav", **changes)
    with pytest.raises(ValueError):
        import_bulletin_package(tampered, node)
    assert TFPNode(db_path=tmp_path / "node.db").get_bulletin("admission-test") == before
    assert len(node.list_recipes()) == 1
    assert accepted["verified_status"] == "verified_ed25519"


def test_caller_cannot_assert_verification_without_valid_signature(tmp_path):
    node = TFPNode(db_path=tmp_path / "node.db")
    with pytest.raises(ValueError):
        node.store_bulletin("claimed", 1, b"unverified", publisher_id="aa" * 32,
                            signature_hex="bb" * 64, verified_status="verified_ed25519")
    assert node.list_bulletins() == []
    assert node.list_recipes() == []


def test_duplicate_is_idempotent_and_conflicting_revision_rejected(tmp_path):
    node = TFPNode(db_path=tmp_path / "node.db")
    node.store_bulletin("same-id", 1, b"first", title="First")
    before = node.get_bulletin("same-id")
    node.store_bulletin("same-id", 1, b"first", title="First")
    assert node.get_bulletin("same-id") == before
    with pytest.raises(ValueError, match="conflict"):
        node.store_bulletin("same-id", 1, b"different", title="Second")
    assert node.get_bulletin("same-id") == before


def test_publisher_change_cannot_take_over_existing_identity(tmp_path):
    node = TFPNode(db_path=tmp_path / "node.db")
    signed_package(tmp_path / "first")
    signed_package(tmp_path / "second", revision=2)
    import_bulletin_package(tmp_path / "first", node)
    with pytest.raises(ValueError, match="publisher"):
        import_bulletin_package(tmp_path / "second", node)
    assert node.get_bulletin("admission-test")[0]["revision"] == 1


def test_export_collision_is_refused_by_default(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "unrelated.txt"
    marker.write_text("Must survive")
    with pytest.raises(FileExistsError):
        signed_package(target)
    assert marker.read_text() == "Must survive"


def test_failed_explicit_replacement_preserves_previous_package(tmp_path, monkeypatch):
    target = tmp_path / "package"
    signed_package(target)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    original = Path.rename

    def fail_install(path, destination):
        if path.name.startswith(".tmp_") and Path(destination) == target:
            raise OSError("Injected Windows replacement failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_install)
    with pytest.raises(OSError, match="Injected"):
        prepare_bulletin_package("admission-test", 2, "Correction", "Changed body", target, overwrite=True)
    assert target.is_dir()
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


def test_successful_replacement_retains_backup(tmp_path):
    target = tmp_path / "package"
    signed_package(target)
    old_audio = (target / "broadcast.wav").read_bytes()
    result = prepare_bulletin_package("admission-test", 2, "Correction", "New body", target, overwrite=True)
    assert (Path(result["previous_package_path"]) / "broadcast.wav").read_bytes() == old_audio
    assert (target / "bulletin.txt").read_text() == "New body"


def test_explicit_replace_refuses_unrelated_directory(tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    (target / "keep.txt").write_text("Preserve")
    with pytest.raises(ValueError, match="TFP bulletin"):
        prepare_bulletin_package("id", 1, "Title", "Body", target, overwrite=True)
    assert (target / "keep.txt").read_text() == "Preserve"


def test_legitimate_correction_and_stale_revision(tmp_path):
    key = Ed25519PrivateKey.generate()
    node = TFPNode(db_path=tmp_path / "node.db")
    for rev in (1, 3):
        signed_package(tmp_path / str(rev), revision=rev, key=key, body=f"Correction {rev}")
        import_bulletin_package(tmp_path / str(rev), node)
    result = TFPNode(db_path=tmp_path / "node.db").get_bulletin("admission-test")
    assert result[1] == b"Correction 3"
    assert result[0]["publisher_trust"] == "not_established"
    signed_package(tmp_path / "2", revision=2, key=key)
    with pytest.raises(ValueError, match="Stale"):
        import_bulletin_package(tmp_path / "2", node)


def test_in_memory_admission_has_same_rules():
    node = TFPNode(db_path="")
    node.store_bulletin("local", 1, b"one")
    with pytest.raises(ValueError, match="conflict"):
        node.store_bulletin("local", 1, b"two")
    assert node.get_bulletin("local")[1] == b"one"


def test_database_failure_rolls_back_both_publication_and_bulletin(tmp_path):
    import sqlite3

    database = tmp_path / "node.db"
    node = TFPNode(db_path=database)
    node.store_bulletin("local", 1, b"accepted")
    before = node.get_bulletin("local")
    recipes_before = dict(node.recipes)
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TRIGGER fail_bulletin BEFORE INSERT ON bulletins
                        BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        node.store_bulletin("local", 2, b"uncommitted correction")
    assert node.recipes == recipes_before
    restarted = TFPNode(db_path=database)
    assert restarted.get_bulletin("local") == before
    assert len(restarted.list_recipes()) == 1


def test_competing_nodes_cannot_overwrite_the_same_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database = tmp_path / "node.db"
    nodes = [TFPNode(db_path=database), TFPNode(db_path=database)]
    ready = Barrier(2)

    def receive(index):
        ready.wait(timeout=5)
        try:
            nodes[index].store_bulletin("race", 1, f"content {index}".encode())
            return index
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = [result for result in executor.map(receive, range(2)) if result is not None]
    assert len(winners) == 1
    restarted = TFPNode(db_path=database)
    assert restarted.get_bulletin("race")[1] == f"content {winners[0]}".encode()
    assert len(restarted.list_recipes()) == 1


def test_failed_rollback_retains_recoverable_backup(tmp_path, monkeypatch, caplog):
    target = tmp_path / "package"
    signed_package(target)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    original = Path.rename

    def fail_install_and_rollback(path, destination):
        if Path(destination) == target:
            raise OSError("Injected install and rollback failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_install_and_rollback)
    with pytest.raises(OSError, match="Injected"):
        prepare_bulletin_package("admission-test", 2, "Correction", "New body", target, overwrite=True)
    backups = list(tmp_path.glob(".previous_package_*"))
    assert len(backups) == 1
    assert {p.name: p.read_bytes() for p in backups[0].iterdir()} == before
    assert str(backups[0]) in caplog.text


def test_legacy_signature_is_rejected_and_legacy_record_is_not_claimed_verified(tmp_path):
    import sqlite3

    package = tmp_path / "package"
    signed_package(package)
    node = TFPNode(db_path=tmp_path / "node.db")
    legacy_audio = altered_audio(package, tmp_path / "legacy.wav", v=1)
    with pytest.raises(ValueError, match="signature"):
        import_bulletin_package(legacy_audio, node)
    assert node.list_bulletins() == []
    import_bulletin_package(package, node)
    with sqlite3.connect(node.db_path) as conn:
        conn.execute("UPDATE bulletins SET metadata_json='{}'")
    assert node.get_bulletin("admission-test")[0]["verified_status"] == "legacy_signature_unverified"
    assert node.list_bulletins()[0]["verified_status"] == "legacy_signature_unverified"


def test_duplicate_provenance_is_not_borrowed_from_another_bulletin(tmp_path):
    package = tmp_path / "signed"
    signed_package(package, body="Shared content")
    node = TFPNode(db_path=tmp_path / "node.db")
    import_bulletin_package(package, node)
    node.store_bulletin("another-id", 1, b"Shared content")
    restarted = TFPNode(db_path=tmp_path / "node.db")
    assert import_bulletin_package(package, restarted)["verified_status"] == "verified_ed25519"
    duplicate = restarted.store_bulletin("another-id", 1, b"Shared content")
    assert duplicate.metadata["bulletin_id"] == "another-id"
    assert duplicate.metadata["verified_status"] == "unsigned"


@pytest.mark.parametrize("damaged", [b"", b"not a WAV", b"RIFF\x00\x00\x00\x00WAVE"])
def test_damaged_audio_does_not_publish_or_crash_error_handler(tmp_path, damaged):
    wav = tmp_path / "damaged.wav"
    wav.write_bytes(damaged)
    node = TFPNode(db_path=tmp_path / "node.db")
    with pytest.raises(ValueError, match="0 valid"):
        import_bulletin_package(wav, node)
    assert node.list_bulletins() == []


@pytest.mark.parametrize("from_environment", [False, True])
def test_memory_database_mode_is_usable_and_isolated(monkeypatch, from_environment):
    monkeypatch.setenv("TFP_DB_PATH", ":memory:")
    node = TFPNode() if from_environment else TFPNode(db_path=":memory:")
    recipe = node.publish(b"Ephemeral content")
    assert node.fetch(recipe.root_hash) == b"Ephemeral content"
    node.store_bulletin("ephemeral", 1, b"Ephemeral bulletin")
    assert node.get_bulletin("ephemeral")[1] == b"Ephemeral bulletin"
    assert TFPNode(db_path=":memory:").get_bulletin("ephemeral") is None
