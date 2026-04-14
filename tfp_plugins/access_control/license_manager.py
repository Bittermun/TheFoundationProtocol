# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
License Manager Plugin Stub

Implements time-locks, paywalls, and community gates.
This is a PLUGIN - core does NOT enforce access control.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


class LicenseType(Enum):
    """Types of licenses."""

    TIME_LOCKED = "time_locked"
    PAYWALL = "paywall"
    COMMUNITY_GATE = "community_gate"
    OPEN = "open"


@dataclass
class License:
    """License definition."""

    content_hash: str
    license_type: LicenseType
    creator_id: str
    unlock_conditions: Dict
    created_at: float
    expires_at: Optional[float] = None
    price_credits: int = 0
    allowed_groups: Optional[Set[str]] = None


@dataclass
class AccessGrant:
    """Granted access to content."""

    content_hash: str
    user_id: str
    granted_at: float
    expires_at: Optional[float]
    grant_reason: str


class LicenseManager:
    """
    Manage content licenses and access grants.

    Core principle: This plugin MANAGES access but does not BLOCK
    hash resolution. Content hashes always resolve; decryption keys
    are what's controlled.
    """

    def __init__(self):
        self._licenses: Dict[str, License] = {}
        self._grants: Dict[str, List[AccessGrant]] = {}  # content_hash -> grants
        self._user_groups: Dict[str, Set[str]] = {}  # user_id -> groups

    def create_license(
        self,
        content_hash: str,
        license_type: LicenseType,
        creator_id: str,
        unlock_conditions: Optional[Dict] = None,
        duration_hours: Optional[float] = None,
        price_credits: int = 0,
        allowed_groups: Optional[List[str]] = None,
    ) -> License:
        """Create a new license for content."""
        now = time.time()
        expires_at = None
        if duration_hours:
            expires_at = now + (duration_hours * 3600)

        license_obj = License(
            content_hash=content_hash,
            license_type=license_type,
            creator_id=creator_id,
            unlock_conditions=unlock_conditions or {},
            created_at=now,
            expires_at=expires_at,
            price_credits=price_credits,
            allowed_groups=set(allowed_groups) if allowed_groups else None,
        )

        self._licenses[content_hash] = license_obj
        return license_obj

    def check_access(
        self, content_hash: str, user_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a user has access to content.

        Returns:
            (has_access, reason) - reason explains why access was granted/denied
        """
        if content_hash not in self._licenses:
            return True, "No license required (open content)"

        license_obj = self._licenses[content_hash]

        # Check existing grants
        if content_hash in self._grants:
            for grant in self._grants[content_hash]:
                if grant.user_id == user_id:
                    if grant.expires_at is None or grant.expires_at > time.time():
                        return True, f"Access granted: {grant.grant_reason}"
                    # Grant expired

        # Check license type
        if license_obj.license_type == LicenseType.OPEN:
            return True, "Open content"

        elif license_obj.license_type == LicenseType.TIME_LOCKED:
            unlock_time = license_obj.unlock_conditions.get("unlock_at", 0)
            if time.time() >= unlock_time:
                return True, "Time lock expired"
            else:
                remaining = unlock_time - time.time()
                return False, f"Time locked ({remaining / 3600:.1f}h remaining)"

        elif license_obj.license_type == LicenseType.PAYWALL:
            # In production: check if user has paid
            # Here we just check if they have a grant
            return False, "Payment required"

        elif license_obj.license_type == LicenseType.COMMUNITY_GATE:
            user_groups = self._user_groups.get(user_id, set())
            allowed = license_obj.allowed_groups or set()
            if user_groups & allowed:  # Intersection
                return True, "Community member"
            else:
                return False, "Community gate closed"

        return False, "Unknown license type"

    def grant_access(
        self,
        content_hash: str,
        user_id: str,
        reason: str,
        duration_hours: Optional[float] = None,
    ) -> AccessGrant:
        """Grant access to a user."""
        now = time.time()
        expires_at = None
        if duration_hours:
            expires_at = now + (duration_hours * 3600)

        grant = AccessGrant(
            content_hash=content_hash,
            user_id=user_id,
            granted_at=now,
            expires_at=expires_at,
            grant_reason=reason,
        )

        if content_hash not in self._grants:
            self._grants[content_hash] = []
        self._grants[content_hash].append(grant)

        return grant

    def register_user_group(self, user_id: str, group: str) -> None:
        """Register a user as part of a community group."""
        if user_id not in self._user_groups:
            self._user_groups[user_id] = set()
        self._user_groups[user_id].add(group)

    def get_license(self, content_hash: str) -> Optional[License]:
        """Get license info for content."""
        return self._licenses.get(content_hash)

    def get_user_grants(self, user_id: str) -> List[AccessGrant]:
        """Get all grants for a user."""
        grants = []
        for content_grants in self._grants.values():
            for grant in content_grants:
                if grant.user_id == user_id:
                    grants.append(grant)
        return grants


# Example usage patterns for creators
def create_time_locked_content(
    manager: LicenseManager, content_hash: str, creator_id: str, unlock_timestamp: float
) -> License:
    """Create time-locked content."""
    return manager.create_license(
        content_hash=content_hash,
        license_type=LicenseType.TIME_LOCKED,
        creator_id=creator_id,
        unlock_conditions={"unlock_at": unlock_timestamp},
    )


def create_paywalled_content(
    manager: LicenseManager, content_hash: str, creator_id: str, price_credits: int
) -> License:
    """Create paywalled content."""
    return manager.create_license(
        content_hash=content_hash,
        license_type=LicenseType.PAYWALL,
        creator_id=creator_id,
        price_credits=price_credits,
    )


def create_community_content(
    manager: LicenseManager,
    content_hash: str,
    creator_id: str,
    allowed_groups: List[str],
) -> License:
    """Create community-gated content."""
    return manager.create_license(
        content_hash=content_hash,
        license_type=LicenseType.COMMUNITY_GATE,
        creator_id=creator_id,
        allowed_groups=allowed_groups,
    )
