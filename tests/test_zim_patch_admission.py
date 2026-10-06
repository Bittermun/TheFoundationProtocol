import hashlib
import json
import struct
import tracemalloc

import pytest

from tfp_core_v4.zim_sync import ZimDeltaEngine, ZIM_PATCH_MAGIC


def pair(tmp_path):
    base, target, patch = [tmp_path / name for name in ('base', 'target', 'patch')]
    base.write_bytes(b'a' * 40000)
    target.write_bytes(b'a' * 20000 + b'b' * 20000)
    ZimDeltaEngine().create_patch(base, target, patch)
    return base, target, patch


def rewrite(patch, change):
    raw = patch.read_bytes()
    length = struct.unpack('!I', raw[8:12])[0]
    header = json.loads(raw[12:12 + length])
    change(header)
    encoded = json.dumps(header).encode()
    patch.write_bytes(ZIM_PATCH_MAGIC + struct.pack('!I', len(encoded)) + encoded + raw[12 + length:])


def test_wrong_base_rejected_even_for_all_novel_target(tmp_path):
    base, target, patch = pair(tmp_path)
    base.write_bytes(b'wrong base')
    with pytest.raises(ValueError, match='base'):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_preexisting_output_survives(tmp_path):
    base, _, patch = pair(tmp_path)
    out = tmp_path / 'out'
    out.write_bytes(b'accepted')
    with pytest.raises(FileExistsError):
        ZimDeltaEngine().apply_patch(base, patch, out)
    assert out.read_bytes() == b'accepted'


@pytest.mark.parametrize('field,value', [('target_size', True), ('target_size', -1), ('novel_chunk_count', -1), ('target_chunk_hashes', ['../evil']), ('total_novel_bytes', '123')])
def test_malformed_header_rejected_before_output(tmp_path, field, value):
    base, _, patch = pair(tmp_path)
    rewrite(patch, lambda h: h.update({field: value}))
    with pytest.raises(ValueError):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_header_length_capped(tmp_path):
    base, _, patch = pair(tmp_path)
    patch.write_bytes(ZIM_PATCH_MAGIC + struct.pack('!I', 2**32 - 1))
    with pytest.raises(ValueError):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')


def test_trailing_records_rejected(tmp_path):
    base, _, patch = pair(tmp_path)
    with patch.open('ab') as stream:
        stream.write(b'extra')
    with pytest.raises(ValueError):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')


def test_nondefault_chunker_parameters_cannot_be_guessed(tmp_path):
    base, target, patch = pair(tmp_path)
    patch.unlink()
    ZimDeltaEngine(128, 256, 512).create_patch(base, target, patch)
    with pytest.raises(ValueError, match='chunker'):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')
    ZimDeltaEngine(128, 256, 512).apply_patch(base, patch, tmp_path / 'out')
    assert (tmp_path / 'out').read_bytes() == target.read_bytes()


def test_failed_integrity_does_not_install_partial_output(tmp_path):
    base, _, patch = pair(tmp_path)
    rewrite(patch, lambda h: h.update(target_sha3=hashlib.sha3_256(b'wrong').hexdigest()))
    with pytest.raises((ValueError, RuntimeError)):
        ZimDeltaEngine().apply_patch(base, patch, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.timeout(120)
def test_creation_spools_payload_instead_of_retaining_archive(tmp_path):
    base, target, patch = [tmp_path / name for name in ('base', 'target', 'patch')]
    base.write_bytes(b'base')
    # Distinct content by block; deliberately no archive-sized fixture in measured allocation.
    with target.open('wb') as stream:
        for i in range(512):
            stream.write(hashlib.shake_256(str(i).encode()).digest(16384))
    tracemalloc.start()
    try:
        ZimDeltaEngine().create_patch(base, target, patch)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 6 * 1024 * 1024


def test_stream_chunks_preserves_subminimum_file(tmp_path):
    source = tmp_path / 'small'
    source.write_bytes(b'small archive')
    assert b''.join(chunk for _, chunk, _ in ZimDeltaEngine()._stream_chunks(source)) == b'small archive'


def test_referenced_base_chunks_obey_custom_limit(tmp_path):
    from tfp_core_v4.zim_sync import ZimPatchLimits
    base, target, patch = pair(tmp_path)
    patch.unlink()
    target.write_bytes(base.read_bytes())
    engine = ZimDeltaEngine(128, 256, 512)
    engine.create_patch(base, target, patch)
    with pytest.raises(ValueError, match='chunk'):
        engine.apply_patch(base, patch, tmp_path / 'out', limits=ZimPatchLimits(max_chunk_bytes=100))
