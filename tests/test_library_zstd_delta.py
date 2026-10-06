"""Tests for bounded Zstandard delta codec."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import pytest
import zstandard as zstd

from tfp_core_v4.library_updates.zstd_delta import (
    MAX_BASE_DICT_BYTES,
    MAX_TARGET_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_WINDOW_BYTES,
    ZstdDeltaInfo,
    create_zstd_delta,
    apply_zstd_delta,
)


def _file_sha3(path: Path) -> str:
    hasher = hashlib.sha3_256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def test_zstd_roundtrip_is_byte_exact(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)

    assert isinstance(info, ZstdDeltaInfo)
    assert info.target_size == target.stat().st_size
    assert info.base_sha3 == _file_sha3(base)
    assert info.target_sha3 == _file_sha3(target)
    assert info.artifact_size == artifact.stat().st_size
    assert info.artifact_sha3 == _file_sha3(artifact)

    apply_zstd_delta(
        base,
        artifact,
        output,
        base_sha3=info.base_sha3,
        target_sha3=info.target_sha3,
        target_size=info.target_size,
    )

    assert output.exists()
    assert output.read_bytes() == target.read_bytes()


def test_wrong_base_retains_existing_files(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    wrong_base = tmp_path / "wrong_base.zim"
    wrong_base.write_bytes(b"WRONG BASE CONTENT" * 100)
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)

    with pytest.raises(ValueError, match="Base hash mismatch"):
        apply_zstd_delta(
            wrong_base,
            artifact,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )

    assert not output.exists()


def test_existing_output_not_overwritten(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"
    output.write_bytes(b"EXISTING FILE")

    info = create_zstd_delta(base, target, artifact)

    with pytest.raises(FileExistsError):
        apply_zstd_delta(
            base,
            artifact,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )

    assert output.read_bytes() == b"EXISTING FILE"


def test_oversized_dictionary_rejected_before_read(tmp_path: Path) -> None:
    oversized_base = tmp_path / "oversized_base.zim"
    # Create sparse file larger than 16 MiB
    with oversized_base.open("wb") as f:
        f.seek(MAX_BASE_DICT_BYTES + 10)
        f.write(b"X")

    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"

    with pytest.raises(ValueError, match="Base archive exceeds 16 MiB dictionary limit"):
        create_zstd_delta(oversized_base, target, artifact)

    assert not artifact.exists()


def test_input_output_alias_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"

    with pytest.raises(ValueError, match="Output aliases input"):
        create_zstd_delta(base, target, base)

    with pytest.raises(ValueError, match="Output aliases input"):
        create_zstd_delta(base, target, target)

    info = create_zstd_delta(base, target, artifact)

    with pytest.raises(ValueError, match="Output aliases input"):
        apply_zstd_delta(
            base,
            artifact,
            base,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )

    with pytest.raises(ValueError, match="Output aliases input"):
        apply_zstd_delta(
            base,
            artifact,
            artifact,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )


def test_wrong_target_hash_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    bogus_hash = "0" * 64

    with pytest.raises(ValueError, match="Target hash mismatch"):
        apply_zstd_delta(
            base,
            artifact,
            output,
            base_sha3=info.base_sha3,
            target_sha3=bogus_hash,
            target_size=info.target_size,
        )

    assert not output.exists()


def test_truncated_header_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = artifact.read_bytes()
    truncated_art = tmp_path / "truncated.zst"
    truncated_art.write_bytes(raw[:3])  # Truncate header to 3 bytes

    with pytest.raises(ValueError, match="Invalid Zstandard frame header"):
        apply_zstd_delta(
            base,
            truncated_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_truncated_body_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = artifact.read_bytes()
    truncated_art = tmp_path / "truncated.zst"
    truncated_art.write_bytes(raw[: len(raw) - 10])

    with pytest.raises(ValueError, match="Decompression failed or incomplete"):
        apply_zstd_delta(
            base,
            truncated_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_truncated_checksum_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = artifact.read_bytes()
    truncated_art = tmp_path / "truncated.zst"
    truncated_art.write_bytes(raw[: len(raw) - 2])  # Chop off 2 bytes of the 4-byte checksum

    with pytest.raises(ValueError, match="Decompression failed or incomplete"):
        apply_zstd_delta(
            base,
            truncated_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_forged_excessive_content_size_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    output = tmp_path / "reconstructed.zim"

    # Craft a tiny 10-byte frame header declaring 128 MiB (> 64 MiB cap):
    # Magic (4 bytes) + FHD (0x84: FCS_Flag=2 -> 4 bytes FCS, Checksum=1)
    # Window (0x00) + FCS (4 bytes: 0x08000000 = 134217728 bytes = 128 MiB)
    crafted = bytes([0x28, 0xb5, 0x2f, 0xfd, 0x84, 0x00, 0x00, 0x00, 0x00, 0x08])
    bomb_art = tmp_path / "bomb.zst"
    bomb_art.write_bytes(crafted)

    with pytest.raises(ValueError, match="Frame declared content size exceeds 64 MiB"):
        apply_zstd_delta(
            base,
            bomb_art,
            output,
            base_sha3=_file_sha3(base),
            target_sha3="0" * 64,
            target_size=1000,
        )
    assert not output.exists()


def test_oversized_window_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    output = tmp_path / "reconstructed.zim"

    # Craft an 8-byte frame header declaring a 32 MiB window (> 16 MiB cap):
    # Magic (4 bytes) + FHD (0x44: FCS_Flag=1 (2 bytes), Single_Segment=0, Checksum=1)
    # Window_Descriptor (0x78: 15 << 3 -> 32 MiB window)
    # Frame_Content_Size (0xe8 0x03 -> 1000 + 256 = 1256 bytes)
    crafted = bytes([0x28, 0xb5, 0x2f, 0xfd, 0x44, 0x78, 0xe8, 0x03])
    oversized_window_art = tmp_path / "big_window.zst"
    oversized_window_art.write_bytes(crafted)

    with pytest.raises(ValueError, match="Frame window size exceeds 16 MiB"):
        apply_zstd_delta(
            base,
            oversized_window_art,
            output,
            base_sha3=_file_sha3(base),
            target_sha3="0" * 64,
            target_size=1256,
        )
    assert not output.exists()


def test_absent_content_size_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    output = tmp_path / "reconstructed.zim"

    # Compress without writing content size
    cctx = zstd.ZstdCompressor(level=3, write_checksum=True, write_content_size=False)
    compressed = cctx.compress(b"A" * 1000)
    art = tmp_path / "no_size.zst"
    art.write_bytes(compressed)

    with pytest.raises(ValueError, match="Frame does not declare content size"):
        apply_zstd_delta(
            base,
            art,
            output,
            base_sha3=_file_sha3(base),
            target_sha3="0" * 64,
            target_size=1000,
        )
    assert not output.exists()


def test_absent_checksum_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    output = tmp_path / "reconstructed.zim"

    # Compress without writing checksum
    cctx = zstd.ZstdCompressor(level=3, write_checksum=False, write_content_size=True)
    compressed = cctx.compress(b"A" * 1000)
    art = tmp_path / "no_chk.zst"
    art.write_bytes(compressed)

    with pytest.raises(ValueError, match="Frame does not contain checksum"):
        apply_zstd_delta(
            base,
            art,
            output,
            base_sha3=_file_sha3(base),
            target_sha3="0" * 64,
            target_size=1000,
        )
    assert not output.exists()


def test_corrupt_payload_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = bytearray(artifact.read_bytes())
    raw[30] ^= 0xFF
    corrupt_art = tmp_path / "corrupt.zst"
    corrupt_art.write_bytes(raw)

    with pytest.raises(ValueError, match="Decompression failed or incomplete"):
        apply_zstd_delta(
            base,
            corrupt_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_appended_garbage_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = artifact.read_bytes() + b"TRAILING GARBAGE"
    garbage_art = tmp_path / "garbage.zst"
    garbage_art.write_bytes(raw)

    with pytest.raises(ValueError, match="Extra data or concatenated frames"):
        apply_zstd_delta(
            base,
            garbage_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_second_valid_frame_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = artifact.read_bytes()
    double_art = tmp_path / "double.zst"
    double_art.write_bytes(raw + raw)

    with pytest.raises(ValueError, match="Extra data or concatenated frames"):
        apply_zstd_delta(
            base,
            double_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )
    assert not output.exists()


def test_empty_input_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty.zim"
    empty.write_bytes(b"")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"

    with pytest.raises(ValueError, match="Input file is empty or nonregular"):
        create_zstd_delta(empty, target, artifact)


def test_oversized_target_rejected(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    oversized_target = tmp_path / "oversized_target.zim"
    with oversized_target.open("wb") as f:
        f.seek(MAX_TARGET_BYTES + 10)
        f.write(b"X")
    artifact = tmp_path / "artifact.zst"

    with pytest.raises(ValueError, match="Target archive exceeds 64 MiB"):
        create_zstd_delta(base, oversized_target, artifact)


def test_failed_decode_removes_temporary_and_retains_existing(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    artifact = tmp_path / "artifact.zst"
    output = tmp_path / "reconstructed.zim"

    info = create_zstd_delta(base, target, artifact)
    raw = bytearray(artifact.read_bytes())
    raw[30] ^= 0xFF
    corrupt_art = tmp_path / "corrupt.zst"
    corrupt_art.write_bytes(raw)

    with pytest.raises(ValueError, match="Decompression failed or incomplete"):
        apply_zstd_delta(
            base,
            corrupt_art,
            output,
            base_sha3=info.base_sha3,
            target_sha3=info.target_sha3,
            target_size=info.target_size,
        )

    assert not output.exists()
    # Ensure no temporary staging files remain in parent dir
    stage_files = list(tmp_path.glob(".tfp-stage-*"))
    assert len(stage_files) == 0


def test_memory_rss_at_boundary(tmp_path: Path) -> None:
    # 16 MiB base and 64 MiB target boundary test
    import subprocess
    import sys
    try:
        import psutil
    except ImportError:
        pytest.skip("psutil required for RSS monitoring")

    base = tmp_path / "base_boundary.bin"
    target = tmp_path / "target_boundary.bin"
    artifact = tmp_path / "artifact_boundary.zst"
    output = tmp_path / "reconstructed_boundary.bin"

    # Create deterministic 16 MiB base (repeated compressible pattern)
    chunk = b"TheFoundationProtocolDeterministic16MiBBaseBlock" * 200
    with base.open("wb") as f:
        while f.tell() < MAX_BASE_DICT_BYTES:
            f.write(chunk)
        f.truncate(MAX_BASE_DICT_BYTES)

    # Create deterministic 64 MiB target (base + modifications)
    with target.open("wb") as f:
        while f.tell() < MAX_TARGET_BYTES:
            f.write(chunk)
        f.truncate(MAX_TARGET_BYTES)

    # Encode worker script
    code = f"""
import sys
from pathlib import Path
from tfp_core_v4.library_updates.zstd_delta import create_zstd_delta, apply_zstd_delta

base = Path({repr(str(base))})
target = Path({repr(str(target))})
artifact = Path({repr(str(artifact))})
output = Path({repr(str(output))})

info = create_zstd_delta(base, target, artifact)
apply_zstd_delta(base, artifact, output, base_sha3=info.base_sha3, target_sha3=info.target_sha3, target_size=info.target_size)
assert output.stat().st_size == target.stat().st_size
"""
    proc = subprocess.Popen([sys.executable, "-c", code])
    p = psutil.Process(proc.pid)
    peak_rss = 0
    while proc.poll() is None:
        try:
            tree_rss = p.memory_info().rss + sum(c.memory_info().rss for c in p.children(recursive=True))
            peak_rss = max(peak_rss, tree_rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        import time
        time.sleep(0.02)

    ret = proc.wait(timeout=30)
    assert ret == 0
    # Peak RSS must be within 256 MiB cap
    assert peak_rss <= 256 * 1024 * 1024, f"Peak RSS {peak_rss} exceeded 256 MiB"
    assert output.exists()
    assert output.stat().st_size == target.stat().st_size
