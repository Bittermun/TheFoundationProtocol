# SPDX-License-Identifier: Apache-2.0
"""Canonical signed bulletin fields and local revision admission policy."""
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

SIGNATURE_VERSION = 2


class BulletinAdmissionError(ValueError):
    """Base exception for bulletin admission failures."""


class StaleRevisionError(BulletinAdmissionError):
    """Raised when an incoming bulletin has a revision lower than the accepted watermark."""


class RevisionConflictError(BulletinAdmissionError):
    """Raised when an incoming bulletin reuses an existing revision with conflicting content."""


class PublisherIdentityConflictError(BulletinAdmissionError):
    """Raised when a bulletin ID is re-issued by an unpinned or conflicting publisher key."""


def validate_identity(bulletin_id, revision, title):
    if not isinstance(bulletin_id, str) or not bulletin_id.strip():
        raise ValueError("bulletin_id must be a nonempty string")
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise ValueError("revision must be a positive safe integer")
    if not isinstance(title, str):
        raise TypeError("title must be a string")


def canonical_envelope(bulletin_id, revision, content_hash, publisher_id, title="", version=SIGNATURE_VERSION):
    title = title or bulletin_id
    validate_identity(bulletin_id, revision, title)
    if version != SIGNATURE_VERSION:
        raise ValueError("Legacy or unsupported signature envelope; reissue using version 2")
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash) or not re.fullmatch(r"[0-9a-f]{64}", publisher_id):
        raise ValueError("Invalid content hash or publisher public key")
    # Array positions are fixed; JSON escaping avoids delimiter ambiguities.
    return json.dumps(["TFP_BULLETIN", version, bulletin_id, revision, title, content_hash, publisher_id],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign_bulletin_content(bulletin_id, revision, content_hash, private_key, *, title=""):
    key = (ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_key))
           if isinstance(private_key, (bytes, bytearray)) else private_key)
    publisher = key.public_key().public_bytes_raw().hex()
    envelope = canonical_envelope(bulletin_id, revision, content_hash, publisher, title)
    return publisher, key.sign(envelope).hex()


def verify_bulletin_signature(bulletin_id, revision, content_hash, publisher_id_hex, signature_hex,
                              *, title="", version=SIGNATURE_VERSION):
    try:
        key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(publisher_id_hex))
        key.verify(bytes.fromhex(signature_hex),
                   canonical_envelope(bulletin_id, revision, content_hash, publisher_id_hex, title, version))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verification_status(bulletin_id, revision, content_hash, publisher, signature, title, version):
    validate_identity(bulletin_id, revision, title)
    if publisher == "unsigned" and signature is None:
        return "unsigned"
    if not signature or publisher == "unsigned" or not verify_bulletin_signature(
        bulletin_id, revision, content_hash, publisher, signature, title=title, version=version,
    ):
        raise ValueError("Bulletin signature verification failed; content was not accepted")
    return "verified_ed25519"


def check_revision(existing, incoming):
    """Return an exact duplicate, or reject conflicts, identity changes and stale arrivals.

    A local ID is pinned to its first publisher. This binding does not establish
    real-world publisher trust. Unsigned publishers remain unauthenticated.
    """
    for previous in existing:
        if previous["publisher_id"] != incoming["publisher_id"]:
            raise PublisherIdentityConflictError("Bulletin publisher identity conflict")
        if previous["revision"] == incoming["revision"]:
            if all(previous[key] == incoming[key] for key in ("content_hash", "title", "publisher_id")):
                return previous
            raise RevisionConflictError("Bulletin revision conflict")
    if existing and incoming["revision"] < max(item["revision"] for item in existing):
        raise StaleRevisionError("Stale bulletin revision was not accepted")
    return None
