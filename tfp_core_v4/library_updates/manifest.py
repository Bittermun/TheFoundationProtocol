"""Strict, locally authorized library update descriptors."""
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tfp_core_v4.zim_sync import bounded_int, unique_object, valid_hash

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024
MAX_DESCRIPTOR = 4096
CHUNKER_PARAMS = (16384, 65536, 131072)


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def file_digest(path: Path) -> str:
    hasher = hashlib.sha3_256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def read_bounded(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('File exceeds resource limit')
    return raw


def key_id(public_key: bytes) -> str:
    if len(public_key) != 32:
        raise ValueError('Expected 32-byte Ed25519 public key')
    return hashlib.sha3_256(public_key).hexdigest()


@dataclass(frozen=True)
class VerifiedUpdate:
    library_id: str
    revision: int
    base_sha3: str
    target_sha3: str
    target_size: int
    artifact_sha3: str
    artifact_size: int
    artifact_kind: str
    chunker_params: tuple[int, int, int]
    publisher_key_id: str

    @property
    def artifact_name(self) -> str:
        return 'artifact.tfp' if self.artifact_kind == 'delta' else 'artifact.zim'

    def body(self) -> dict:
        return dict(asdict(self), schema_version=1)


def verify_descriptor(package: Path, trusted_keys: dict[str, bytes], library_id: str,
                      accepted_revision: int, *, accepted_descriptor: str | None = None) -> VerifiedUpdate:
    raw = read_bounded(package / 'update.json', MAX_DESCRIPTOR)
    data = json.loads(raw, object_pairs_hook=unique_object)
    fields = set(VerifiedUpdate.__dataclass_fields__) | {'schema_version'}
    if not isinstance(data, dict) or set(data) != fields or type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported update descriptor')
    if not hmac.compare_digest(raw, canonical(data)):
        raise ValueError('Descriptor must be canonical JSON')
    if not isinstance(data['library_id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', data['library_id']):
        raise ValueError('Invalid library ID')
    for field in ('base_sha3', 'target_sha3', 'artifact_sha3', 'publisher_key_id'):
        valid_hash(data[field])
    for field, maximum in (('revision', 2**63-1), ('target_size', MAX_ARCHIVE), ('artifact_size', MAX_ARTIFACT)):
        if bounded_int(data[field], maximum) == 0:
            raise ValueError('Descriptor sizes and revision must be positive')
    if data['artifact_kind'] not in ('delta', 'full') or data['chunker_params'] != list(CHUNKER_PARAMS) or any(type(n) is not int for n in data['chunker_params']):
        raise ValueError('Unsupported artifact or chunker parameters')
    if data['artifact_kind'] == 'full' and (data['target_size'] != data['artifact_size'] or not hmac.compare_digest(data['target_sha3'], data['artifact_sha3'])):
        raise ValueError('Full archive descriptor mismatch')
    public = trusted_keys.get(data['publisher_key_id'])
    if public is None or not hmac.compare_digest(key_id(public), data['publisher_key_id']):
        raise ValueError('Publisher is not locally pinned')
    signature = read_bounded(package / 'update.sig', 64)
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, raw)
    except (InvalidSignature, ValueError) as exc:
        raise ValueError('Invalid publisher signature') from exc
    if data['library_id'] != library_id or data['revision'] < accepted_revision:
        raise ValueError('Wrong library or stale revision')
    if data['revision'] == accepted_revision and (accepted_descriptor is None or not hmac.compare_digest(file_digest(package / 'update.json'), accepted_descriptor)):
        raise ValueError('Equal revision is not an exact accepted duplicate')
    data.pop('schema_version')
    data['chunker_params'] = tuple(data['chunker_params'])
    return VerifiedUpdate(**data)


def verify_artifact(update: VerifiedUpdate, path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != update.artifact_size:
        raise ValueError('Invalid artifact size or path')
    if not hmac.compare_digest(file_digest(path), update.artifact_sha3):
        raise ValueError('Invalid artifact digest')


def verify_update(package: Path, trusted_keys: dict[str, bytes], library_id: str,
                  accepted_revision: int, *, accepted_descriptor: str | None = None) -> VerifiedUpdate:
    update = verify_descriptor(package, trusted_keys, library_id, accepted_revision, accepted_descriptor=accepted_descriptor)
    verify_artifact(update, package / update.artifact_name)
    return update
