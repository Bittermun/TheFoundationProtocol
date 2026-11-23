"""Bounded creator-pack carriers for the school-library profiles."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import version
from io import BytesIO
import json
from pathlib import Path
import re
import struct
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from tfp_core_v4.library_updates.manifest import canonical, read_bounded
from tfp_core_v4.zim_sync import new_output, unique_object

MAX_PACK = 16 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
MAX_MEMBER = 1024 * 1024
MAX_FILES = 34
MAX_REVISION = (1 << 53) - 1
SHA3_PROFILE = "cp-sha3-ed25519-v1"
HASHES = {SHA3_PROFILE: "sha3-256", "cp-sha256-ed25519-v1": "sha256"}
LICENSES = ("CC0-1.0", "CC-BY-4.0", "Apache-2.0", "MIT")
PROFILE_ROLES = {
    "tfp.school-builder.v1": ("recipe", "payload/recipe.json"),
    "tfp.school-lexicon.v1": ("dictionary", "payload/dictionary.zdict"),
    "tfp.school-content.v1": ("index", "payload/index.json"),
    "tfp.school-kit.v1": ("kit", "payload/kit.json"),
}
MANIFEST_FIELDS = {
    "format", "envelope_version", "id", "version", "revision", "profile", "crypto_profile",
    "publisher_key_id", "title", "summary", "license", "authors", "files", "entrypoints",
    "dependencies", "requires", "permissions", "provenance",
}
DEVICE = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])", re.IGNORECASE)


def digest(raw: bytes, profile: str) -> str:
    algorithm = HASHES[profile]
    return f"{algorithm}:" + hashlib.new(algorithm, raw).hexdigest()


def is_digest(value, profile=None) -> bool:
    if not isinstance(value, str):
        return False
    kind, _, hex_value = value.partition(":")
    return (kind == HASHES[profile] if profile else kind in HASHES.values()) and bool(
        re.fullmatch(r"[0-9a-f]{64}", hex_value)
    )


def is_id(value) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}/[a-z0-9][a-z0-9_-]{0,63}", value)
    )


def is_version(value) -> bool:
    # School profiles initially publish stable SemVer releases.
    return isinstance(value, str) and len(value) <= 60 and bool(
        re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value)
    )


def plain(value, maximum, minimum=1) -> bool:
    return isinstance(value, str) and minimum <= len(value) <= maximum and all(
        ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF for char in value
    )


def exact(value, fields) -> bool:
    return isinstance(value, dict) and value.keys() == set(fields)


def parse_object(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def artifact_ref(manifest: dict, raw: bytes) -> dict:
    return {
        "id": manifest["id"], "version": manifest["version"], "profile": manifest["profile"],
        "digest": digest(raw, manifest["crypto_profile"]),
    }


@dataclass(frozen=True)
class Pack:
    manifest: dict
    raw: bytes
    payload: dict[str, bytes]

    @property
    def ref(self) -> dict:
        return artifact_ref(self.manifest, self.raw)


def _reference_key(ref):
    return ref["id"], ref["version"], ref["digest"]


def _validate_refs(refs, maximum):
    if not isinstance(refs, list) or len(refs) > maximum:
        raise ValueError("Invalid artifact references")
    for ref in refs:
        if not (exact(ref, ("id", "version", "profile", "digest"))
                and is_id(ref["id"]) and is_version(ref["version"])
                and isinstance(ref["profile"], str) and ref["profile"] in PROFILE_ROLES
                and is_digest(ref["digest"])):
            raise ValueError("Invalid artifact reference")
    keys = [_reference_key(ref) for ref in refs]
    if keys != sorted(set(keys)) or len({key[:2] for key in keys}) != len(keys):
        raise ValueError("Duplicate, conflicting or unsorted artifact references")


def _media(path, profile):
    if path == PROFILE_ROLES[profile][1]:
        return "application/zstd-dictionary" if path.endswith(".zdict") else "application/json"
    if profile == "tfp.school-content.v1" and re.fullmatch(r"payload/article-[0-9]{3}\.zst", path):
        return "application/zstd"
    raise ValueError("Unsupported file for school creator profile")


def _validate_manifest(data):
    if not exact(data, MANIFEST_FIELDS):
        raise ValueError("Invalid creator manifest fields")
    profile, crypto = data["profile"], data["crypto_profile"]
    if not isinstance(crypto, str) or crypto not in HASHES:
        raise ValueError("Unsupported creator pack crypto profile")
    if not isinstance(profile, str) or profile not in PROFILE_ROLES:
        raise ValueError("Unsupported school creator profile")
    if not (data["format"] == "creator-pack" and type(data["envelope_version"]) is int
            and data["envelope_version"] == 1 and is_id(data["id"]) and is_version(data["version"])
            and type(data["revision"]) is int and 1 <= data["revision"] <= MAX_REVISION
            and plain(data["title"], 120) and plain(data["summary"], 240, 0)
            and data["license"] in LICENSES and is_digest(data["publisher_key_id"], crypto)
            and data["requires"] == [] and data["permissions"] == []):
        raise ValueError("Invalid school creator metadata")
    authors = data["authors"]
    if not isinstance(authors, list) or not 1 <= len(authors) <= 20 or not all(plain(a, 120) for a in authors):
        raise ValueError("Invalid creator authors")
    role, entrypoint = PROFILE_ROLES[profile]
    if data["entrypoints"] != [{"role": role, "path": entrypoint}]:
        raise ValueError("Invalid school creator entrypoint")
    files = data["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Invalid creator inventory size")
    paths = []
    for member in files:
        if not (exact(member, ("path", "media_type", "size", "digest", "license"))
                and isinstance(member["path"], str)
                and member["media_type"] == _media(member["path"], profile)
                and member["license"] in LICENSES and is_digest(member["digest"], crypto)
                and type(member["size"]) is int and 1 <= member["size"] <= MAX_MEMBER):
            raise ValueError("Invalid creator inventory")
        paths.append(member["path"])
    if paths != sorted(set(paths)) or entrypoint not in paths:
        raise ValueError("Invalid or unsorted creator inventory")
    _validate_refs(data["dependencies"], 2)
    provenance = data["provenance"]
    if not exact(provenance, ("parents", "created_with")):
        raise ValueError("Invalid creator provenance")
    _validate_refs(provenance["parents"], 1)
    tools = provenance["created_with"]
    if not isinstance(tools, list) or not 1 <= len(tools) <= 3:
        raise ValueError("Invalid provenance tools")
    tool_names = []
    for tool in tools:
        if not (exact(tool, ("tool", "version")) and tool["tool"] in ("tfp.school-kit", "zstandard", "zstd")
                and is_version(tool["version"])):
            raise ValueError("Invalid provenance tool")
        tool_names.append(tool["tool"])
    if tool_names != sorted(set(tool_names)):
        raise ValueError("Invalid provenance tool order")


def make_pack(kind, artifact_id, release, revision, title, summary, license_id, public, payload,
              *, dependencies=(), parent=None, tool_versions=()) -> Pack:
    profile = f"tfp.school-{kind}.v1"
    role, path = PROFILE_ROLES[profile]
    tools = [("tfp.school-kit", version("tfp")), *tool_versions]
    data = {
        "format": "creator-pack", "envelope_version": 1, "id": artifact_id,
        "version": release, "revision": revision, "profile": profile, "crypto_profile": SHA3_PROFILE,
        "publisher_key_id": digest(public, SHA3_PROFILE), "title": title, "summary": summary,
        "license": license_id, "authors": [artifact_id.partition("/")[0]], "requires": [], "permissions": [],
        "files": [
            {"path": name, "size": len(raw), "digest": digest(raw, SHA3_PROFILE),
             "media_type": _media(name, profile), "license": license_id}
            for name, raw in sorted(payload.items())
        ],
        "entrypoints": [{"role": role, "path": path}],
        "dependencies": sorted(dependencies, key=_reference_key),
        "provenance": {
            "parents": [parent] if parent else [],
            "created_with": [{"tool": name, "version": value} for name, value in sorted(tools)],
        },
    }
    _validate_manifest(data)
    raw = canonical(data)
    if len(raw) > MAX_MANIFEST:
        raise ValueError("Creator manifest exceeds size limit")
    return Pack(data, raw, payload)


def read_public(path: Path) -> bytes:
    raw = read_bounded(path, 32)
    if len(raw) != 32:
        raise ValueError("Expected a raw 32-byte Ed25519 public key")
    return raw


def read_secret(path: Path) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(read_bounded(path, 32))


def write_pack(pack: Pack, path: Path, key: Ed25519PrivateKey | None = None) -> None:
    files = {"manifest.json": pack.raw, **pack.payload}
    if key is not None:
        if digest(key.public_key().public_bytes_raw(), pack.manifest["crypto_profile"]) != pack.manifest["publisher_key_id"]:
            raise ValueError("Signing key does not match declared publisher")
        files["signature.ed25519"] = key.sign(pack.raw)
    with new_output(path) as target:
        with ZipFile(target, "w", allowZip64=False) as archive:
            for name, content in sorted(files.items()):
                entry = ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, content, compress_type=ZIP_STORED)
        if target.tell() > MAX_PACK:
            raise ValueError("Creator pack exceeds size limit")


def _check_zip_directory(raw):
    # Stored school packs use one disk, no ZIP64, and no archive comment.
    # Check the directory count before ZipFile allocates entries.
    end = struct.Struct("<4s4H2LH")
    if len(raw) < end.size:
        raise ValueError("Invalid creator pack carrier")
    magic, disk, directory_disk, here, total, size, offset, comment = end.unpack_from(raw, len(raw) - end.size)
    if (magic != b"PK\x05\x06" or disk or directory_disk or comment or here != total
            or not 2 <= total <= MAX_FILES + 2 or offset + size != len(raw) - end.size
            or size > total * 512):
        raise ValueError("Invalid creator pack directory")


def read_pack(path: Path, *, public: bytes | None = None, expected_id=None, expected_profile=None) -> Pack:
    """Read an inert draft or verify a signed pack against an explicit local pin."""
    raw_pack = read_bounded(path, MAX_PACK)
    _check_zip_directory(raw_pack)
    try:
        with ZipFile(BytesIO(raw_pack)) as archive:
            entries = archive.infolist()
            names = {item.filename for item in entries}
            if not 2 <= len(entries) <= MAX_FILES + 2 or len(names) != len(entries):
                raise ValueError("Invalid creator pack inventory")
            for item in entries:
                unix_type = (item.external_attr >> 16) & 0o170000
                if (item.compress_type != ZIP_STORED or item.compress_size != item.file_size
                        or item.file_size > MAX_MEMBER or item.flag_bits & 1
                        or item.orig_filename != item.filename or item.is_dir()
                        or unix_type not in (0, 0o100000)):
                    raise ValueError("Invalid creator pack member")
            reserved = {"manifest.json", "signature.ed25519"} if public is not None else {"manifest.json"}
            if not reserved <= names:
                raise ValueError("Missing creator manifest or signature")
            if archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
                raise ValueError("Creator manifest exceeds size limit")
            raw = archive.read("manifest.json")
            data = parse_object(raw)
            _validate_manifest(data)
            if raw != canonical(data):
                raise ValueError("Creator manifest is not canonical")
            if expected_id is not None and data["id"] != expected_id:
                raise ValueError("Artifact ID is outside the local publisher pin")
            if expected_profile is not None and data["profile"] != expected_profile:
                raise ValueError("Unexpected creator artifact profile")
            crypto = data["crypto_profile"]
            if public is not None:
                if not is_id(expected_id) or digest(public, crypto) != data["publisher_key_id"]:
                    raise ValueError("Publisher key does not match the local pin")
                if archive.getinfo("signature.ed25519").file_size != 64:
                    raise ValueError("Invalid Ed25519 signature length")
                Ed25519PublicKey.from_public_bytes(public).verify(archive.read("signature.ed25519"), raw)
            if names != reserved | {record["path"] for record in data["files"]}:
                raise ValueError("Unexpected or missing creator pack members")
            payload = {}
            for record in data["files"]:
                name = record["path"]
                if archive.getinfo(name).file_size != record["size"]:
                    raise ValueError("Invalid creator member size")
                item = archive.read(name)
                if len(item) != record["size"] or digest(item, crypto) != record["digest"]:
                    raise ValueError("Invalid creator member digest")
                payload[name] = item
    except InvalidSignature as exc:
        raise ValueError("Invalid creator pack signature") from exc
    except (BadZipFile, NotImplementedError, EOFError) as exc:
        raise ValueError("Invalid creator pack carrier") from exc
    return Pack(data, raw, payload)
