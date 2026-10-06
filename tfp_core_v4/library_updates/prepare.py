"""Prepare signed, bounded update packages without installing reader software."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_core_v4.zim_sync import ZimDeltaEngine
from .manifest import (
    CHUNKER_PARAMS,
    MAX_ARCHIVE,
    MAX_ARTIFACT,
    VerifiedUpdate,
    canonical,
    file_digest,
    key_id,
    read_bounded,
    verify_update,
)
from .zstd_delta import (
    MAX_BASE_DICT_BYTES,
    apply_zstd_delta,
    create_zstd_delta,
)


def prepare_update(
    base: Path,
    target: Path,
    output_dir: Path,
    library_id: str,
    revision: int,
    signing_key: Path,
    *,
    delta_backend: str = "cdc",
) -> Path:
    if delta_backend not in ("cdc", "zstd", "auto"):
        raise ValueError(f"Unsupported delta backend: {delta_backend}")

    base, target, output_dir = map(Path, (base, target, output_dir))
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(output_dir)

    for source in (base, target):
        if source.is_symlink() or not 0 < source.stat().st_size <= MAX_ARCHIVE:
            raise ValueError("Archive exceeds pilot limits or is not a regular path")

    key = Ed25519PrivateKey.from_private_bytes(read_bounded(signing_key, 32))
    public = key.public_key().public_bytes_raw()
    pub_id = key_id(public)

    output_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".tfp-package-", dir=output_dir.parent) as temp:
        stage = Path(temp)
        initial_base_hash = file_digest(base)
        initial_target_hash = file_digest(target)
        target_size = target.stat().st_size

        selected_kind: str
        selected_format: str | None
        selected_version: int
        artifact_path: Path

        if delta_backend == "cdc":
            candidate = stage / "artifact.tfp"
            ZimDeltaEngine().create_patch(base, target, candidate)
            art_size = candidate.stat().st_size
            if art_size * 5 <= target_size * 4 and art_size <= MAX_ARTIFACT:
                selected_kind = "delta"
                selected_format = None
                selected_version = 1
                artifact_path = candidate
            else:
                candidate.unlink(missing_ok=True)
                if target_size > MAX_ARTIFACT:
                    raise ValueError("Neither delta nor full archive meets 16 MiB limit")
                full_art = stage / "artifact.zim"
                shutil.copyfile(target, full_art)
                selected_kind = "full"
                selected_format = None
                selected_version = 1
                artifact_path = full_art

        elif delta_backend == "zstd":
            if base.stat().st_size > MAX_BASE_DICT_BYTES:
                raise ValueError(
                    f"Base archive exceeds 16 MiB dictionary limit ({base.stat().st_size} bytes)"
                )
            candidate = stage / "artifact.zst"
            info = create_zstd_delta(base, target, candidate)
            if info.artifact_size * 5 <= target_size * 4 and info.artifact_size <= MAX_ARTIFACT:
                # Reconstruct locally to verify before publishing
                rec_path = stage / ".verify_reconstruct.zim"
                try:
                    apply_zstd_delta(
                        base,
                        candidate,
                        rec_path,
                        base_sha3=info.base_sha3,
                        target_sha3=info.target_sha3,
                        target_size=info.target_size,
                    )
                    if file_digest(rec_path) != info.target_sha3 or rec_path.stat().st_size != target_size:
                        raise ValueError("Local reconstruction verification failed")
                finally:
                    rec_path.unlink(missing_ok=True)
                selected_kind = "delta"
                selected_format = "zstd-rawdict-v1"
                selected_version = 2
                artifact_path = candidate
            else:
                candidate.unlink(missing_ok=True)
                if target_size > MAX_ARTIFACT:
                    raise ValueError("Neither delta nor full archive meets 16 MiB limit")
                full_art = stage / "artifact.zim"
                shutil.copyfile(target, full_art)
                selected_kind = "full"
                selected_format = None
                selected_version = 1
                artifact_path = full_art

        else:  # auto mode
            candidates: list[dict] = []

            # 1. CDC candidate
            cdc_file = stage / "candidate.tfp"
            ZimDeltaEngine().create_patch(base, target, cdc_file)
            cdc_size = cdc_file.stat().st_size
            if cdc_size * 5 <= target_size * 4 and cdc_size <= MAX_ARTIFACT:
                u_cdc = VerifiedUpdate(
                    library_id=library_id,
                    revision=revision,
                    base_sha3=initial_base_hash,
                    target_sha3=initial_target_hash,
                    target_size=target_size,
                    artifact_sha3=file_digest(cdc_file),
                    artifact_size=cdc_size,
                    artifact_kind="delta",
                    chunker_params=CHUNKER_PARAMS,
                    publisher_key_id=pub_id,
                    schema_version=1,
                    patch_format=None,
                )
                pkg_size = cdc_size + len(canonical(u_cdc.body())) + 64
                candidates.append({
                    "backend": "cdc",
                    "file": cdc_file,
                    "kind": "delta",
                    "format": None,
                    "version": 1,
                    "pkg_size": pkg_size,
                })

            # 2. Zstd candidate
            if base.stat().st_size <= MAX_BASE_DICT_BYTES:
                zstd_file = stage / "candidate.zst"
                zinfo = create_zstd_delta(base, target, zstd_file)
                if zinfo.artifact_size * 5 <= target_size * 4 and zinfo.artifact_size <= MAX_ARTIFACT:
                    rec_path = stage / ".verify_reconstruct.zim"
                    try:
                        apply_zstd_delta(
                            base,
                            zstd_file,
                            rec_path,
                            base_sha3=zinfo.base_sha3,
                            target_sha3=zinfo.target_sha3,
                            target_size=zinfo.target_size,
                        )
                        if file_digest(rec_path) != zinfo.target_sha3 or rec_path.stat().st_size != target_size:
                            raise ValueError("Local reconstruction verification failed")
                    finally:
                        rec_path.unlink(missing_ok=True)
                    u_zstd = VerifiedUpdate(
                        library_id=library_id,
                        revision=revision,
                        base_sha3=initial_base_hash,
                        target_sha3=initial_target_hash,
                        target_size=target_size,
                        artifact_sha3=file_digest(zstd_file),
                        artifact_size=zinfo.artifact_size,
                        artifact_kind="delta",
                        chunker_params=CHUNKER_PARAMS,
                        publisher_key_id=pub_id,
                        schema_version=2,
                        patch_format="zstd-rawdict-v1",
                    )
                    pkg_size = zinfo.artifact_size + len(canonical(u_zstd.body())) + 64
                    candidates.append({
                        "backend": "zstd",
                        "file": zstd_file,
                        "kind": "delta",
                        "format": "zstd-rawdict-v1",
                        "version": 2,
                        "pkg_size": pkg_size,
                    })

            if candidates:
                # Rank by package size; tie-break in favor of CDC
                # Sort key: (pkg_size, 0 if backend == 'cdc' else 1)
                candidates.sort(key=lambda c: (c["pkg_size"], 0 if c["backend"] == "cdc" else 1))
                winner = candidates[0]
                selected_kind = winner["kind"]
                selected_format = winner["format"]
                selected_version = winner["version"]
                dest_name = "artifact.zst" if winner["backend"] == "zstd" else "artifact.tfp"
                final_art = stage / dest_name
                winner["file"].rename(final_art)
                artifact_path = final_art
                # Clean up unused candidates
                for c in candidates[1:]:
                    c["file"].unlink(missing_ok=True)
            else:
                if target_size > MAX_ARTIFACT:
                    raise ValueError("Neither delta nor full archive meets 16 MiB limit")
                full_art = stage / "artifact.zim"
                shutil.copyfile(target, full_art)
                selected_kind = "full"
                selected_format = None
                selected_version = 1
                artifact_path = full_art

        if artifact_path.stat().st_size > MAX_ARTIFACT:
            raise ValueError("Artifact exceeds 16 MiB pilot limit")

        # Bind signed hashes to bytes actually encoded. Detect input changes between creation and signing.
        current_base_hash = file_digest(base)
        current_target_hash = file_digest(target)
        if current_base_hash != initial_base_hash or current_target_hash != initial_target_hash or target.stat().st_size != target_size:
            raise ValueError("Input archives modified during preparation")

        update = VerifiedUpdate(
            library_id=library_id,
            revision=revision,
            base_sha3=current_base_hash,
            target_sha3=current_target_hash,
            target_size=target_size,
            artifact_sha3=file_digest(artifact_path),
            artifact_size=artifact_path.stat().st_size,
            artifact_kind=selected_kind,
            chunker_params=CHUNKER_PARAMS,
            publisher_key_id=pub_id,
            schema_version=selected_version,
            patch_format=selected_format,
        )

        raw = canonical(update.body())
        (stage / "update.json").write_bytes(raw)
        (stage / "update.sig").write_bytes(key.sign(raw))
        verify_update(stage, {pub_id: public}, library_id, 0)

        # Exclusive directory creation protects against concurrent prepare
        output_dir.mkdir()
        try:
            for path in (artifact_path, stage / "update.json", stage / "update.sig"):
                shutil.copyfile(path, output_dir / path.name)
        except BaseException:
            shutil.rmtree(output_dir)
            raise

    return output_dir
