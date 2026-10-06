"""Bounded Zstandard archive-delta codec for offline library updates.

Applies bounded Zstandard compression with raw-content dictionary mode,
strict single-frame admission, and exact SHA3-256 integrity verification.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path

import zstandard as zstd

from tfp_core_v4.zim_sync import check_output, new_output, valid_hash

MAX_BASE_DICT_BYTES: int = 16 * 1024 * 1024      # 16 MiB
MAX_TARGET_BYTES: int = 64 * 1024 * 1024         # 64 MiB
MAX_ARTIFACT_BYTES: int = 16 * 1024 * 1024       # 16 MiB
MAX_WINDOW_BYTES: int = 16 * 1024 * 1024         # 16 MiB (16,384 KiB)
COMPRESSION_LEVEL: int = 3
WINDOW_LOG: int = 24                             # 2^24 = 16 MiB window


@dataclass(frozen=True)
class ZstdDeltaInfo:
    base_sha3: str
    target_sha3: str
    target_size: int
    artifact_sha3: str
    artifact_size: int


def _validate_input_file(path: Path, max_bytes: int, label: str) -> int:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is empty or nonregular")
    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{label} is empty or nonregular")
    if size > max_bytes:
        raise ValueError(f"{label} exceeds resource limit ({size} > {max_bytes})")
    return size


def create_zstd_delta(base: Path, target: Path, output: Path) -> ZstdDeltaInfo:
    base = Path(base)
    target = Path(target)
    output = Path(output)

    if any(output.resolve() == source.resolve() for source in (base, target)):
        raise ValueError("Output aliases input")
    check_output(output, base, target)

    if base.is_symlink() or not base.is_file() or base.stat().st_size == 0:
        raise ValueError("Input file is empty or nonregular: base")
    if target.is_symlink() or not target.is_file() or target.stat().st_size == 0:
        raise ValueError("Input file is empty or nonregular: target")

    base_size = base.stat().st_size
    if base_size > MAX_BASE_DICT_BYTES:
        raise ValueError(f"Base archive exceeds 16 MiB dictionary limit ({base_size} bytes)")

    target_size = target.stat().st_size
    if target_size > MAX_TARGET_BYTES:
        raise ValueError(f"Target archive exceeds 64 MiB ({target_size} bytes)")

    base_bytes = base.read_bytes()
    if len(base_bytes) != base_size:
        raise ValueError("Base file changed during read")

    target_bytes = target.read_bytes()
    if len(target_bytes) != target_size:
        raise ValueError("Target file changed during read")

    base_sha3 = hashlib.sha3_256(base_bytes).hexdigest()
    target_sha3 = hashlib.sha3_256(target_bytes).hexdigest()

    cdict = zstd.ZstdCompressionDict(base_bytes, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    cparams = zstd.ZstdCompressionParameters.from_level(
        COMPRESSION_LEVEL,
        window_log=WINDOW_LOG,
        write_checksum=True,
        write_content_size=True,
    )
    cctx = zstd.ZstdCompressor(dict_data=cdict, compression_params=cparams)
    payload = cctx.compress(target_bytes)

    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Artifact exceeds 16 MiB limit ({len(payload)} bytes)")

    artifact_sha3 = hashlib.sha3_256(payload).hexdigest()
    artifact_size = len(payload)

    with new_output(output) as stream:
        stream.write(payload)

    return ZstdDeltaInfo(
        base_sha3=base_sha3,
        target_sha3=target_sha3,
        target_size=target_size,
        artifact_sha3=artifact_sha3,
        artifact_size=artifact_size,
    )


def apply_zstd_delta(
    base: Path,
    artifact: Path,
    output: Path,
    *,
    base_sha3: str,
    target_sha3: str,
    target_size: int,
) -> None:
    base = Path(base)
    artifact = Path(artifact)
    output = Path(output)

    if any(output.resolve() == source.resolve() for source in (base, artifact)):
        raise ValueError("Output aliases input")
    check_output(output, base, artifact)

    valid_hash(base_sha3)
    valid_hash(target_sha3)
    if type(target_size) is not int or not 0 < target_size <= MAX_TARGET_BYTES:
        raise ValueError(f"Target size must be positive and at most {MAX_TARGET_BYTES}")

    if base.is_symlink() or not base.is_file() or base.stat().st_size == 0:
        raise ValueError("Input file is empty or nonregular: base")
    if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size == 0:
        raise ValueError("Input file is empty or nonregular: artifact")

    if base.stat().st_size > MAX_BASE_DICT_BYTES:
        raise ValueError(f"Base archive exceeds 16 MiB dictionary limit ({base.stat().st_size} bytes)")
    if artifact.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Artifact exceeds 16 MiB limit ({artifact.stat().st_size} bytes)")

    base_bytes = base.read_bytes()
    actual_base_sha3 = hashlib.sha3_256(base_bytes).hexdigest()
    if not hmac.compare_digest(actual_base_sha3, base_sha3):
        raise ValueError("Base hash mismatch")

    artifact_bytes = artifact.read_bytes()

    try:
        params = zstd.get_frame_parameters(artifact_bytes)
    except Exception as exc:
        raise ValueError("Invalid Zstandard frame header") from exc

    if params is None or params.content_size in (zstd.CONTENTSIZE_UNKNOWN, zstd.CONTENTSIZE_ERROR):
        raise ValueError("Frame does not declare content size")
    if params.content_size > MAX_TARGET_BYTES:
        raise ValueError("Frame declared content size exceeds 64 MiB")
    if params.content_size != target_size:
        raise ValueError(f"Frame declared content size {params.content_size} does not match target size {target_size}")
    if params.window_size > MAX_WINDOW_BYTES:
        raise ValueError("Frame window size exceeds 16 MiB")
    if not params.has_checksum:
        raise ValueError("Frame does not contain checksum")
    if params.dict_id != 0:
        raise ValueError("Frame requires unexpected dictionary ID")

    ddict = zstd.ZstdCompressionDict(base_bytes, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    dctx = zstd.ZstdDecompressor(dict_data=ddict, max_window_size=MAX_WINDOW_BYTES)
    dobj = dctx.decompressobj()

    try:
        decompressed = dobj.decompress(artifact_bytes)
        decompressed += dobj.flush()
        # Enforce full frame and checksum verification via decompress
        dctx.decompress(artifact_bytes, max_output_size=target_size)
    except Exception as exc:
        raise ValueError("Decompression failed or incomplete") from exc

    if len(dobj.unused_data) > 0:
        raise ValueError("Extra data or concatenated frames detected")

    if len(decompressed) != target_size:
        raise ValueError("Decompressed size does not match target size")

    actual_target_sha3 = hashlib.sha3_256(decompressed).hexdigest()
    if not hmac.compare_digest(actual_target_sha3, target_sha3):
        raise ValueError("Target hash mismatch")

    with new_output(output) as stream:
        stream.write(decompressed)
