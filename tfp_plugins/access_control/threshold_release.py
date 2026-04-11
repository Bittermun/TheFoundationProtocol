"""
Threshold Release Plugin Stub

Implements multi-signature key release for collaborative content
unlocking. Core does NOT enforce - this is purely a plugin pattern.
"""

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ThresholdRelease:
    """A threshold release configuration."""

    release_id: str
    content_hash: str
    required_signatures: int  # M of N
    authorized_keys: Set[str]  # Public keys that can sign
    signatures_collected: Dict[str, str]  # key_id -> signature
    created_at: float
    expires_at: Optional[float]
    released: bool = False
    released_at: Optional[float] = None


@dataclass
class SignatureContribution:
    """Record of a signature contribution."""

    release_id: str
    contributor_key: str
    signature: str
    timestamp: float


class ThresholdReleaser:
    """
    Manage multi-signature threshold releases.

    Use case: Content is encrypted with a key that's split among
    multiple parties. When M-of-N parties sign, the key is released.

    Core principle: This manages KEY RELEASE, not content blocking.
    Content hashes always resolve; decryption requires the key.
    """

    def __init__(self):
        self._releases: Dict[str, ThresholdRelease] = {}
        self._contributions: Dict[str, List[SignatureContribution]] = defaultdict(list)

    def create_release(
        self,
        content_hash: str,
        required_signatures: int,
        authorized_keys: List[str],
        duration_hours: Optional[float] = None,
    ) -> ThresholdRelease:
        """Create a new threshold release."""
        release_id = hashlib.sha3_256(
            f"{content_hash}:{time.time()}:{','.join(sorted(authorized_keys))}".encode()
        ).hexdigest()[:16]

        now = time.time()
        expires_at = None
        if duration_hours:
            expires_at = now + (duration_hours * 3600)

        release = ThresholdRelease(
            release_id=release_id,
            content_hash=content_hash,
            required_signatures=required_signatures,
            authorized_keys=set(authorized_keys),
            signatures_collected={},
            created_at=now,
            expires_at=expires_at,
        )

        self._releases[release_id] = release
        return release

    def contribute_signature(
        self, release_id: str, key_id: str, signature: str
    ) -> Tuple[bool, str]:
        """
        Contribute a signature to a threshold release.

        Returns:
            (success, message) - success=True if signature accepted
        """
        if release_id not in self._releases:
            return False, "Release not found"

        release = self._releases[release_id]

        if release.released:
            return False, "Release already completed"

        if release.expires_at and time.time() > release.expires_at:
            return False, "Release expired"

        if key_id not in release.authorized_keys:
            return False, "Key not authorized"

        if key_id in release.signatures_collected:
            return False, "Key already contributed"

        # In production: verify signature cryptographically
        # Here we accept any non-empty signature
        if not signature:
            return False, "Empty signature"

        # Accept signature
        release.signatures_collected[key_id] = signature

        contribution = SignatureContribution(
            release_id=release_id,
            contributor_key=key_id,
            signature=signature,
            timestamp=time.time(),
        )
        self._contributions[release_id].append(contribution)

        # Check if threshold reached
        if len(release.signatures_collected) >= release.required_signatures:
            release.released = True
            release.released_at = time.time()
            return (
                True,
                f"Threshold reached! Release complete ({len(release.signatures_collected)}/{release.required_signatures})",
            )

        remaining = release.required_signatures - len(release.signatures_collected)
        return (
            True,
            f"Signature accepted ({len(release.signatures_collected)}/{release.required_signatures}, {remaining} remaining)",
        )

    def check_release_status(self, release_id: str) -> Optional[Dict]:
        """Check status of a threshold release."""
        if release_id not in self._releases:
            return None

        release = self._releases[release_id]

        return {
            "release_id": release_id,
            "content_hash": release.content_hash,
            "required": release.required_signatures,
            "collected": len(release.signatures_collected),
            "authorized_count": len(release.authorized_keys),
            "released": release.released,
            "released_at": release.released_at,
            "expires_at": release.expires_at,
            "expired": release.expires_at and time.time() > release.expires_at,
            "contributors": list(release.signatures_collected.keys()),
        }

    def get_release_key(self, release_id: str) -> Optional[str]:
        """
        Get the released key if threshold is met.

        In production: this would reconstruct the decryption key
        from the threshold signatures. Here we return a synthetic
        key if released.
        """
        if release_id not in self._releases:
            return None

        release = self._releases[release_id]

        if not release.released:
            return None

        # Synthetic key generation (in production: actual key reconstruction)
        sig_data = "".join(sorted(release.signatures_collected.values()))
        return hashlib.sha3_256(sig_data.encode()).hexdigest()

    def get_pending_releases(self) -> List[ThresholdRelease]:
        """Get all unreleased threshold releases."""
        return [
            r
            for r in self._releases.values()
            if not r.released and (not r.expires_at or time.time() <= r.expires_at)
        ]

    def cancel_release(self, release_id: str) -> bool:
        """Cancel a threshold release."""
        if release_id in self._releases:
            del self._releases[release_id]
            if release_id in self._contributions:
                del self._contributions[release_id]
            return True
        return False


def create_multi_sig_release(
    releaser: ThresholdReleaser,
    content_hash: str,
    threshold: int,
    participants: List[str],
    duration_days: float = 7,
) -> ThresholdRelease:
    """Helper to create a multi-sig release."""
    return releaser.create_release(
        content_hash=content_hash,
        required_signatures=threshold,
        authorized_keys=participants,
        duration_hours=duration_days * 24,
    )
