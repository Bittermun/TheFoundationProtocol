"""Single-writer journaled catalog activation. Existing phone assets remain untouched."""
from contextlib import contextmanager
from dataclasses import dataclass
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import stat
import sys

from tfp_core_v4.zim_sync import ZimDeltaEngine, new_output, unique_object, valid_hash
from .kiwix import prepare_catalog, probe_reader, validate_zim
from .manifest import MAX_ARCHIVE, canonical, file_digest, key_id, read_bounded, verify_update


@dataclass(frozen=True)
class KiwixConfig:
    library_id: str
    archive_dir: Path
    library_xml: Path
    state_dir: Path
    base_archive: Path
    trusted_public_key: Path
    kiwix_manage: Path
    zimcheck: Path
    serve_base_url: str
    probe_article_path: str
    command_timeout_seconds: float = 10

    def __post_init__(self):
        for name in ('archive_dir', 'library_xml', 'state_dir', 'base_archive', 'trusted_public_key', 'kiwix_manage', 'zimcheck'):
            path = Path(getattr(self, name)).absolute()
            if any(part.is_symlink() for part in [path, *path.parents]):
                raise ValueError('Configured paths cannot contain symlinks')
            object.__setattr__(self, name, path.resolve())
        if not math.isfinite(self.command_timeout_seconds) or self.command_timeout_seconds <= 0:
            raise ValueError('Invalid command deadline')
        if self.base_archive == self.library_xml or self.archive_dir == self.state_dir:
            raise ValueError('Archive, catalog and state paths must be distinct')


@dataclass(frozen=True)
class ActivationResult:
    status: str
    revision: int
    target_path: Path
    recovered: bool = False


def sync_directory(path: Path) -> None:
    if sys.platform != 'win32':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_bytes(path: Path, raw: bytes) -> None:
    if path.is_symlink():
        raise ValueError('Refusing symlink destination')
    previous = path.stat() if path.exists() else None
    fd, name = tempfile.mkstemp(prefix='.tfp-atomic-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if previous:
                if sys.platform != 'win32':
                    os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
                os.chmod(temporary, stat.S_IMODE(previous.st_mode))
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def update_lock(config: KiwixConfig):
    config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = config.state_dir / 'updater.lock'
    if path.is_symlink():
        raise ValueError('Refusing symlink lock')
    with path.open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('another updater owns the library lock') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def accepted_state(config: KiwixConfig) -> dict:
    path = config.state_dir / 'accepted.json'
    if not path.exists():
        return {'revision': 0, 'target_path': str(config.base_archive), 'target_sha3': file_digest(config.base_archive), 'descriptor_sha3': None}
    state = json.loads(read_bounded(path, 4096), object_pairs_hook=unique_object)
    if set(state) != {'revision', 'target_path', 'target_sha3', 'descriptor_sha3'} or type(state['revision']) is not int or state['revision'] <= 0:
        raise ValueError('Invalid accepted library state')
    valid_hash(state['target_sha3'])
    valid_hash(state['descriptor_sha3'])
    expected = config.archive_dir / (state['target_sha3'] + '.zim')
    if Path(state['target_path']) != expected or expected.is_symlink():
        raise ValueError('Accepted state points outside managed archive directory')
    return state


def _recover(config: KiwixConfig) -> bool:
    journal_path = config.state_dir / 'activation.json'
    if not journal_path.exists():
        return False
    journal = json.loads(read_bounded(journal_path, 16384), object_pairs_hook=unique_object)
    backup = config.state_dir / 'catalog.backup'
    original = read_bounded(backup, 1048576)
    if not hmac.compare_digest(file_digest(backup), journal['old_catalog_sha3']):
        raise ValueError('Recovery catalog backup failed integrity check')
    current = file_digest(config.library_xml)
    if not any(hmac.compare_digest(current, digest) for digest in (journal['old_catalog_sha3'], journal['new_catalog_sha3'])):
        raise ValueError('Catalog changed externally; automatic recovery refused')
    accepted = accepted_state(config)
    if hmac.compare_digest(canonical(accepted), canonical(journal['next_state'])) and hmac.compare_digest(current, journal['new_catalog_sha3']):
        if not hmac.compare_digest(file_digest(Path(accepted['target_path'])), accepted['target_sha3']):
            raise ValueError('Accepted archive changed during recovery')
        # Accepted state is written only after reader success; finalize interrupted cleanup.
        journal_path.unlink()
        sync_directory(config.state_dir)
        return True
    previous = journal['previous_state']
    if not hmac.compare_digest(canonical(accepted), canonical(previous)):
        raise ValueError('Accepted state changed externally; recovery refused')
    atomic_bytes(config.library_xml, original)
    journal_path.unlink()
    sync_directory(config.state_dir)
    return True


def recover_activation(config: KiwixConfig) -> ActivationResult:
    with update_lock(config):
        recovered = _recover(config)
        state = accepted_state(config)
        return ActivationResult('recovered' if recovered else 'unchanged', state['revision'], Path(state['target_path']), recovered)


def activate_package(package: Path, config: KiwixConfig) -> ActivationResult:
    with update_lock(config):
        recovered = _recover(config)
        previous = accepted_state(config)
        public = read_bounded(config.trusted_public_key, 32)
        update = verify_update(package, {key_id(public): public}, config.library_id, previous['revision'], accepted_descriptor=previous['descriptor_sha3'])
        base = Path(previous['target_path'])
        if base.stat().st_size > MAX_ARCHIVE or not hmac.compare_digest(file_digest(base), previous['target_sha3']):
            raise ValueError('Accepted base archive changed')
        if update.revision == previous['revision']:
            return ActivationResult('duplicate', update.revision, base, recovered)
        if not hmac.compare_digest(update.base_sha3, previous['target_sha3']):
            raise ValueError('Update does not match accepted base archive')
        config.archive_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        target = config.archive_dir / (update.target_sha3 + '.zim')
        if shutil.disk_usage(config.archive_dir).free < update.target_size + 2 * 1048576:
            raise OSError('Insufficient disk space for retained base and staged update')
        artifact = package / update.artifact_name
        if target.exists():
            if target.is_symlink() or not hmac.compare_digest(file_digest(target), update.target_sha3):
                raise ValueError('Conflicting staged archive')
        elif update.format_name == 'tfpzimp1':
            ZimDeltaEngine(*update.chunker_params).apply_patch(base, artifact, target)
        elif update.format_name == 'zstd-rawdict-v1':
            from .zstd_delta import apply_zstd_delta
            apply_zstd_delta(
                base,
                artifact,
                target,
                base_sha3=update.base_sha3,
                target_sha3=update.target_sha3,
                target_size=update.target_size,
            )
        elif update.format_name == 'none':
            with new_output(target) as out, artifact.open('rb') as source:
                shutil.copyfileobj(source, out, 1048576)
        else:
            raise ValueError(f'Unknown format: {update.format_name}')
        if target.stat().st_size != update.target_size or not hmac.compare_digest(file_digest(target), update.target_sha3):
            raise ValueError('Reconstructed target mismatch')
        # Offline library content is intentionally reader-accessible; state/keys remain private.
        target.chmod(0o644)
        validate_zim(target, config.zimcheck, config.command_timeout_seconds)
        old_catalog = read_bounded(config.library_xml, 1048576)
        fd, name = tempfile.mkstemp(prefix='.tfp-catalog-', suffix='.xml', dir=config.library_xml.parent)
        os.close(fd)
        candidate = Path(name)
        try:
            book_id = prepare_catalog(config.library_xml, candidate, target, config.kiwix_manage, config.command_timeout_seconds)
            new_catalog = read_bounded(candidate, 1048576)
            # Never overwrite catalog edits made during reconstruction/tool execution.
            if not hmac.compare_digest(file_digest(config.library_xml), hashlib_digest(old_catalog)):
                raise ValueError('Catalog changed externally during update')
            next_state = {'revision': update.revision, 'target_path': str(target), 'target_sha3': update.target_sha3, 'descriptor_sha3': file_digest(package / 'update.json')}
            atomic_bytes(config.state_dir / 'catalog.backup', old_catalog)
            journal: dict = {'phase': 'catalog_prepared', 'old_catalog_sha3': hashlib_digest(old_catalog), 'new_catalog_sha3': hashlib_digest(new_catalog), 'previous_state': previous, 'next_state': next_state}
            atomic_bytes(config.state_dir / 'activation.json', canonical(journal))
            try:
                if not hmac.compare_digest(file_digest(config.library_xml), journal['old_catalog_sha3']):
                    raise ValueError('Catalog changed externally before switch')
                atomic_bytes(config.library_xml, new_catalog)
                probe_reader(config.serve_base_url, target, book_id, config.probe_article_path, config.command_timeout_seconds)
                if not hmac.compare_digest(file_digest(config.library_xml), journal['new_catalog_sha3']):
                    raise ValueError('Catalog changed externally during reader probe')
                atomic_bytes(config.state_dir / 'accepted.json', canonical(next_state))
                (config.state_dir / 'activation.json').unlink()
                sync_directory(config.state_dir)
            except BaseException:
                _recover(config)
                raise
        finally:
            candidate.unlink(missing_ok=True)
        return ActivationResult('committed', update.revision, target, recovered)


def hashlib_digest(raw: bytes) -> str:
    import hashlib
    return hashlib.sha3_256(raw).hexdigest()


def load_config(path: Path) -> KiwixConfig:
    data = json.loads(read_bounded(path, 16384), object_pairs_hook=unique_object)
    for field in ('archive_dir', 'library_xml', 'state_dir', 'base_archive', 'trusted_public_key', 'kiwix_manage', 'zimcheck'):
        value = Path(data[field])
        data[field] = value if value.is_absolute() else path.resolve().parent / value
    return KiwixConfig(**data)


def library_status(config: KiwixConfig) -> dict:
    with update_lock(config):
        state = accepted_state(config)
        return dict(state, recovery_required=(config.state_dir / 'activation.json').exists(), status='committed' if state['revision'] else 'bootstrap')
