import hashlib
import importlib
import json
from pathlib import Path

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


def test_v1_descriptor_compatibility_fixed_key(tmp_path):
    from tfp_core_v4.library_updates.manifest import (
        VerifiedUpdate, canonical, file_digest, key_id, verify_update, CHUNKER_PARAMS
    )
    # Fixed test-only 32-byte Ed25519 private key seed (all 0x42)
    key_bytes = b'\x42' * 32
    key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    pub = key.public_key().public_bytes_raw()
    pub_id = key_id(pub)
    trusted = {pub_id: pub}

    pkg_dir = tmp_path / 'v1_compat_pkg'
    pkg_dir.mkdir()
    artifact = pkg_dir / 'artifact.tfp'
    artifact.write_bytes(b'TEST_ARTIFACT_CONTENT')

    u1 = VerifiedUpdate(
        library_id='compat-lib',
        revision=10,
        base_sha3='a' * 64,
        target_sha3='b' * 64,
        target_size=1000,
        artifact_sha3=file_digest(artifact),
        artifact_size=artifact.stat().st_size,
        artifact_kind='delta',
        chunker_params=CHUNKER_PARAMS,
        publisher_key_id=pub_id,
        schema_version=1,
    )
    body = u1.body()
    assert 'patch_format' not in body
    assert body['schema_version'] == 1
    assert u1.format_name == 'tfpzimp1'
    assert u1.artifact_name == 'artifact.tfp'

    raw_json = canonical(body)
    (pkg_dir / 'update.json').write_bytes(raw_json)
    (pkg_dir / 'update.sig').write_bytes(key.sign(raw_json))

    verified = verify_update(pkg_dir, trusted, 'compat-lib', 0)
    assert verified.schema_version == 1
    assert verified.patch_format is None
    assert verified.format_name == 'tfpzimp1'
    assert verified.artifact_name == 'artifact.tfp'
    assert verified.body() == body


def test_v2_descriptor_zstd_and_full(tmp_path):
    from tfp_core_v4.library_updates.manifest import (
        VerifiedUpdate, canonical, file_digest, key_id, verify_update, CHUNKER_PARAMS
    )
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw()
    pub_id = key_id(pub)
    trusted = {pub_id: pub}

    # Test v2 delta (zstd-rawdict-v1)
    pkg_delta = tmp_path / 'pkg_delta'
    pkg_delta.mkdir()
    art_zstd = pkg_delta / 'artifact.zst'
    art_zstd.write_bytes(b'ZSTD_ARTIFACT_DATA')

    u_delta = VerifiedUpdate(
        library_id='v2-lib',
        revision=5,
        base_sha3='1' * 64,
        target_sha3='2' * 64,
        target_size=2000,
        artifact_sha3=file_digest(art_zstd),
        artifact_size=art_zstd.stat().st_size,
        artifact_kind='delta',
        chunker_params=CHUNKER_PARAMS,
        publisher_key_id=pub_id,
        schema_version=2,
        patch_format='zstd-rawdict-v1',
    )
    assert u_delta.format_name == 'zstd-rawdict-v1'
    assert u_delta.artifact_name == 'artifact.zst'
    raw_delta = canonical(u_delta.body())
    assert b'"patch_format":"zstd-rawdict-v1"' in raw_delta
    assert b'"schema_version":2' in raw_delta
    (pkg_delta / 'update.json').write_bytes(raw_delta)
    (pkg_delta / 'update.sig').write_bytes(key.sign(raw_delta))

    v_delta = verify_update(pkg_delta, trusted, 'v2-lib', 0)
    assert v_delta.schema_version == 2
    assert v_delta.patch_format == 'zstd-rawdict-v1'
    assert v_delta.format_name == 'zstd-rawdict-v1'
    assert v_delta.artifact_name == 'artifact.zst'

    # Test v2 full (none)
    pkg_full = tmp_path / 'pkg_full'
    pkg_full.mkdir()
    art_full = pkg_full / 'artifact.zim'
    art_full.write_bytes(b'FULL_ARCHIVE_DATA')

    u_full = VerifiedUpdate(
        library_id='v2-lib',
        revision=6,
        base_sha3='1' * 64,
        target_sha3=file_digest(art_full),
        target_size=art_full.stat().st_size,
        artifact_sha3=file_digest(art_full),
        artifact_size=art_full.stat().st_size,
        artifact_kind='full',
        chunker_params=CHUNKER_PARAMS,
        publisher_key_id=pub_id,
        schema_version=2,
        patch_format='none',
    )
    assert u_full.format_name == 'none'
    assert u_full.artifact_name == 'artifact.zim'
    raw_full = canonical(u_full.body())
    (pkg_full / 'update.json').write_bytes(raw_full)
    (pkg_full / 'update.sig').write_bytes(key.sign(raw_full))

    v_full = verify_update(pkg_full, trusted, 'v2-lib', 0)
    assert v_full.schema_version == 2
    assert v_full.patch_format == 'none'
    assert v_full.format_name == 'none'
    assert v_full.artifact_name == 'artifact.zim'


def test_v2_unsupported_formats_and_tampering_fail(tmp_path):
    from tfp_core_v4.library_updates.manifest import (
        VerifiedUpdate, canonical, file_digest, key_id, verify_descriptor, CHUNKER_PARAMS
    )
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes_raw()
    pub_id = key_id(pub)
    trusted = {pub_id: pub}

    pkg = tmp_path / 'tamper_pkg'
    pkg.mkdir()

    base_update = VerifiedUpdate(
        library_id='lib',
        revision=1,
        base_sha3='a' * 64,
        target_sha3='b' * 64,
        target_size=500,
        artifact_sha3='c' * 64,
        artifact_size=100,
        artifact_kind='delta',
        chunker_params=CHUNKER_PARAMS,
        publisher_key_id=pub_id,
        schema_version=2,
        patch_format='zstd-rawdict-v1',
    )

    # 1. Unsupported v2 format
    bad_data = base_update.body()
    bad_data['patch_format'] = 'gzip'
    raw = canonical(bad_data)
    (pkg / 'update.json').write_bytes(raw)
    (pkg / 'update.sig').write_bytes(key.sign(raw))
    with pytest.raises(ValueError, match='Unsupported v2 delta patch format'):
        verify_descriptor(pkg, trusted, 'lib', 0)

    # 2. Schema v1 with patch_format added fails
    bad_v1 = dict(base_update.body(), schema_version=1)
    raw = canonical(bad_v1)
    (pkg / 'update.json').write_bytes(raw)
    (pkg / 'update.sig').write_bytes(key.sign(raw))
    with pytest.raises(ValueError, match='Unsupported update descriptor'):
        verify_descriptor(pkg, trusted, 'lib', 0)

    # 3. Schema v2 delta with patch_format='none' fails
    bad_v2_delta = dict(base_update.body(), patch_format='none')
    raw = canonical(bad_v2_delta)
    (pkg / 'update.json').write_bytes(raw)
    (pkg / 'update.sig').write_bytes(key.sign(raw))
    with pytest.raises(ValueError, match='Unsupported v2 delta patch format'):
        verify_descriptor(pkg, trusted, 'lib', 0)

    # 4. Unknown extra field in v2 fails
    extra = dict(base_update.body(), extra_field='unknown')
    raw = canonical(extra)
    (pkg / 'update.json').write_bytes(raw)
    (pkg / 'update.sig').write_bytes(key.sign(raw))
    with pytest.raises(ValueError, match='Unsupported update descriptor'):
        verify_descriptor(pkg, trusted, 'lib', 0)

    # 5. Unsupported schema version (e.g. 3) fails
    v3 = dict(base_update.body(), schema_version=3)
    raw = canonical(v3)
    (pkg / 'update.json').write_bytes(raw)
    (pkg / 'update.sig').write_bytes(key.sign(raw))
    with pytest.raises(ValueError, match='Unsupported update descriptor'):
        verify_descriptor(pkg, trusted, 'lib', 0)


def test_prepare_update_backends_and_selection(tmp_path):
    from tfp_core_v4.library_updates.prepare import prepare_update
    from tfp_core_v4.library_updates.manifest import verify_update, key_id

    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / 'pub.key'
    keyfile.write_bytes(key.private_bytes_raw())
    pub = key.public_key().public_bytes_raw()
    trusted = {key_id(pub): pub}

    base = Path('tests/fixtures/library_update/base.zim')
    target = Path('tests/fixtures/library_update/target.zim')

    # 1. Explicit cdc -> schema v1 delta
    out_cdc = tmp_path / 'pkg_cdc'
    prepare_update(base, target, out_cdc, 'school', 1, keyfile, delta_backend='cdc')
    v_cdc = verify_update(out_cdc, trusted, 'school', 0)
    assert v_cdc.schema_version == 1
    assert v_cdc.artifact_kind == 'delta'
    assert v_cdc.artifact_name == 'artifact.tfp'
    assert (out_cdc / 'artifact.tfp').exists()

    # 2. Explicit zstd -> schema v2 delta
    out_zstd = tmp_path / 'pkg_zstd'
    prepare_update(base, target, out_zstd, 'school', 2, keyfile, delta_backend='zstd')
    v_zstd = verify_update(out_zstd, trusted, 'school', 0)
    assert v_zstd.schema_version == 2
    assert v_zstd.patch_format == 'zstd-rawdict-v1'
    assert v_zstd.artifact_name == 'artifact.zst'
    assert (out_zstd / 'artifact.zst').exists()

    # 3. Auto mode chooses zstd when smaller
    out_auto = tmp_path / 'pkg_auto'
    prepare_update(base, target, out_auto, 'school', 3, keyfile, delta_backend='auto')
    v_auto = verify_update(out_auto, trusted, 'school', 0)
    assert v_auto.schema_version == 2
    assert v_auto.patch_format == 'zstd-rawdict-v1'
    assert (out_auto / 'artifact.zst').exists()

    # 4. Refuse existing output dir
    with pytest.raises(FileExistsError):
        prepare_update(base, target, out_auto, 'school', 4, keyfile, delta_backend='auto')


def test_prepare_update_oversized_base_zstd_and_auto_fallback(tmp_path):
    from tfp_core_v4.library_updates.prepare import prepare_update
    from tfp_core_v4.library_updates.manifest import verify_update, key_id
    from tfp_core_v4.library_updates.zstd_delta import MAX_BASE_DICT_BYTES

    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / 'pub.key'
    keyfile.write_bytes(key.private_bytes_raw())
    pub = key.public_key().public_bytes_raw()
    trusted = {key_id(pub): pub}

    # Create 17 MiB base (> 16 MiB dict limit) and target
    big_base = tmp_path / 'big_base.zim'
    with big_base.open('wb') as f:
        f.seek(MAX_BASE_DICT_BYTES + 1024)
        f.write(b'X')

    target = tmp_path / 'target.zim'
    with target.open('wb') as f:
        f.seek(MAX_BASE_DICT_BYTES + 1024)
        f.write(b'Y')

    # Explicit zstd rejects oversized base
    out_zstd = tmp_path / 'pkg_big_zstd'
    with pytest.raises(ValueError, match='16 MiB dictionary limit'):
        prepare_update(big_base, target, out_zstd, 'school', 1, keyfile, delta_backend='zstd')
    assert not out_zstd.exists()

    # Auto mode skips zstd and falls back to CDC
    out_auto = tmp_path / 'pkg_big_auto'
    prepare_update(big_base, target, out_auto, 'school', 2, keyfile, delta_backend='auto')
    v_auto = verify_update(out_auto, trusted, 'school', 0)
    assert v_auto.schema_version == 1
    assert v_auto.artifact_name == 'artifact.tfp'


def test_prepare_update_detects_input_mutation_during_prep(tmp_path, monkeypatch):
    from tfp_core_v4.library_updates import prepare as prep_module
    from tfp_core_v4.library_updates.prepare import prepare_update

    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / 'pub.key'
    keyfile.write_bytes(key.private_bytes_raw())

    base = tmp_path / 'mutate_base.zim'
    target = tmp_path / 'mutate_target.zim'
    base.write_bytes(b'BASE_DATA' * 100)
    target.write_bytes(b'TARGET_DATA' * 100)

    # Mutate target during creation
    orig_create = prep_module.create_zstd_delta

    def mutating_create_zstd(b, t, out):
        info = orig_create(b, t, out)
        # Mutate target on disk after candidate is created
        target.write_bytes(b'MUTATED_TARGET_DATA' * 100)
        return info

    monkeypatch.setattr(prep_module, 'create_zstd_delta', mutating_create_zstd)

    out_pkg = tmp_path / 'pkg_mutated'
    with pytest.raises(ValueError, match='Input archives modified during preparation'):
        prepare_update(base, target, out_pkg, 'school', 1, keyfile, delta_backend='zstd')
    assert not out_pkg.exists()

