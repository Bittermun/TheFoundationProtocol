import hashlib
import importlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def package(tmp_path, changed=True):
    module = importlib.import_module('tfp_core_v4.library_updates.manifest')
    prepare = importlib.import_module('tfp_core_v4.library_updates.prepare').prepare_update
    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / 'publisher.key'
    keyfile.write_bytes(key.private_bytes_raw())
    base, target = tmp_path / 'base.zim', tmp_path / 'target.zim'
    data = hashlib.shake_256(b'fixture').digest(256000)
    base.write_bytes(data)
    target.write_bytes(data[:120000] + (b'change' * 1000 if changed else b'') + data[120000:])
    result = prepare(base, target, tmp_path / 'package', 'school', 1, keyfile)
    public = key.public_key().public_bytes_raw()
    return module, result, {module.key_id(public): public}, target


def test_signed_package_roundtrip_and_delta_selection(tmp_path):
    module, result, trusted, target = package(tmp_path)
    update = module.verify_update(result, trusted, 'school', 0)
    assert update.artifact_kind == 'delta'
    assert update.target_sha3 == hashlib.sha3_256(target.read_bytes()).hexdigest()
    assert update.artifact_size < target.stat().st_size * .8


@pytest.mark.parametrize('field,value', [('revision', 2), ('library_id', 'other'), ('artifact_sha3', '0' * 64), ('chunker_params', [128, 256, 512])])
def test_every_descriptor_field_is_signed(tmp_path, field, value):
    module, result, trusted, _ = package(tmp_path)
    descriptor = result / 'update.json'
    data = json.loads(descriptor.read_bytes())
    data[field] = value
    descriptor.write_bytes(module.canonical(data))
    with pytest.raises(ValueError):
        module.verify_update(result, trusted, 'school', 0)


def test_unpinned_key_wrong_library_and_stale_revision_rejected(tmp_path):
    module, result, trusted, _ = package(tmp_path)
    for keys, library, revision in [({}, 'school', 0), (trusted, 'wrong', 0), (trusted, 'school', 2)]:
        with pytest.raises(ValueError):
            module.verify_update(result, keys, library, revision)


def test_equal_revision_needs_exact_accepted_descriptor(tmp_path):
    module, result, trusted, _ = package(tmp_path)
    with pytest.raises(ValueError):
        module.verify_update(result, trusted, 'school', 1)
    digest = hashlib.sha3_256((result / 'update.json').read_bytes()).hexdigest()
    assert module.verify_update(result, trusted, 'school', 1, accepted_descriptor=digest).revision == 1


def test_corrupt_artifact_rejected(tmp_path):
    module, result, trusted, _ = package(tmp_path)
    artifact = result / 'artifact.tfp'
    artifact.write_bytes(artifact.read_bytes()[:-1] + b'!')
    with pytest.raises(ValueError, match='artifact'):
        module.verify_update(result, trusted, 'school', 0)


def test_full_fallback_for_unrelated_content(tmp_path):
    module, result, trusted, target = package(tmp_path)
    import shutil
    shutil.rmtree(result)
    target.write_bytes(hashlib.shake_256(b'unrelated').digest(1000))
    prepare = importlib.import_module('tfp_core_v4.library_updates.prepare').prepare_update
    prepare(tmp_path / 'base.zim', target, result, 'school', 1, tmp_path / 'publisher.key')
    assert module.verify_update(result, trusted, 'school', 0).artifact_kind == 'full'


def test_duplicate_json_fields_rejected(tmp_path):
    module, result, trusted, _ = package(tmp_path)
    descriptor = result / 'update.json'
    descriptor.write_bytes(b'{"revision":1,' + descriptor.read_bytes()[1:])
    with pytest.raises(ValueError):
        module.verify_update(result, trusted, 'school', 0)
