"""Prepare signed, bounded update packages without installing reader software."""
from pathlib import Path
import shutil
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_core_v4.zim_sync import ZimDeltaEngine
from .manifest import CHUNKER_PARAMS, MAX_ARCHIVE, MAX_ARTIFACT, VerifiedUpdate, canonical, file_digest, key_id, read_bounded, verify_update


def prepare_update(base: Path, target: Path, output_dir: Path, library_id: str,
                   revision: int, signing_key: Path) -> Path:
    base, target, output_dir = map(Path, (base, target, output_dir))
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(output_dir)
    for source in (base, target):
        if source.is_symlink() or not 0 < source.stat().st_size <= MAX_ARCHIVE:
            raise ValueError('Archive exceeds pilot limits or is not a regular path')
    key = Ed25519PrivateKey.from_private_bytes(read_bounded(signing_key, 32))
    public = key.public_key().public_bytes_raw()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tfp-package-', dir=output_dir.parent) as temp:
        stage = Path(temp)
        artifact = stage / 'artifact.tfp'
        ZimDeltaEngine().create_patch(base, target, artifact)
        kind = 'delta'
        if artifact.stat().st_size * 5 > target.stat().st_size * 4:
            artifact.unlink()
            artifact = stage / 'artifact.zim'
            shutil.copyfile(target, artifact)
            kind = 'full'
        if artifact.stat().st_size > MAX_ARTIFACT:
            raise ValueError('Artifact exceeds 16 MiB pilot limit')
        update = VerifiedUpdate(library_id, revision, file_digest(base), file_digest(target), target.stat().st_size,
                                file_digest(artifact), artifact.stat().st_size, kind, CHUNKER_PARAMS, key_id(public))
        raw = canonical(update.body())
        (stage / 'update.json').write_bytes(raw)
        (stage / 'update.sig').write_bytes(key.sign(raw))
        verify_update(stage, {key_id(public): public}, library_id, 0)
        # Exclusive directory creation protects even a concurrent prepare operation.
        output_dir.mkdir()
        try:
            for path in (artifact, stage / 'update.json', stage / 'update.sig'):
                shutil.copyfile(path, output_dir / path.name)
        except BaseException:
            shutil.rmtree(output_dir)
            raise
    return output_dir
