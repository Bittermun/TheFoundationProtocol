# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Demand-Weighted Caching Credits (DWCC) Calculator

Implements the economic formula for Bridge 3: Popularity→Persistence Economic Loop

Formula: DWCC = base_rate × (requests × storage_duration × semantic_value)

Where:
- requests: Number of times content was requested in epoch
- storage_duration: How long content has been pinned (seconds)
- semantic_value: Tag-based importance multiplier (from tag index)
- base_rate: Network-wide credit rate per unit

This creates self-sustaining archival:
- High-demand content earns pinning rewards
- Low-demand content ages out naturally
- Network self-optimizes storage toward what's actually used
"""

import dataclasses
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SemanticValueTier(Enum):
    """Semantic value tiers based on tag importance."""

    CRITICAL = 5.0  # Emergency info, public safety
    HIGH = 3.0  # News, education, healthcare
    MEDIUM = 1.5  # Entertainment, general info
    LOW = 0.5  # Redundant, outdated content
    DECAY = 0.1  # Near eviction threshold


@dataclasses.dataclass
class DWCCEntry:
    """Tracks metrics for a single content hash."""

    content_hash: str
    requests: int = 0
    first_seen: float = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    last_requested: float = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    pinned: bool = True
    semantic_tier: SemanticValueTier = SemanticValueTier.MEDIUM
    total_earned: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "content_hash": self.content_hash,
            "requests": self.requests,
            "first_seen": self.first_seen,
            "last_requested": self.last_requested,
            "pinned": self.pinned,
            "semantic_tier": self.semantic_tier.value,
            "total_earned": self.total_earned,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DWCCEntry":
        """Deserialize from dictionary."""
        return cls(
            content_hash=data["content_hash"],
            requests=data.get("requests", 0),
            first_seen=data.get("first_seen", datetime.now(timezone.utc).timestamp()),
            last_requested=data.get(
                "last_requested", datetime.now(timezone.utc).timestamp()
            ),
            pinned=data.get("pinned", True),
            semantic_tier=SemanticValueTier(data.get("semantic_tier", 1.5)),
            total_earned=data.get("total_earned", 0.0),
        )


class DWCCCalculator:
    """
    Calculates Demand-Weighted Caching Credits for content archival.

    Implements the hybrid economic model:
    - 50% compute/PoSI credits
    - 50% archival pinning credits based on demand

    Nodes earn credits for storing high-demand hashes.
    Credits decay if pinned content isn't requested.
    """

    def __init__(
        self,
        base_rate: float = 1.0,
        decay_rate: float = 0.01,  # Per hour decay for unrequested content
        min_pin_reward: float = 0.1,
        max_pin_reward: float = 100.0,
    ):
        """
        Initialize DWCC calculator.

        Args:
            base_rate: Base credit rate per request-hour
            decay_rate: Hourly decay rate for inactive pins
            min_pin_reward: Minimum reward per epoch
            max_pin_reward: Maximum reward per epoch per content
        """
        self.base_rate = base_rate
        self.decay_rate = decay_rate
        self.min_pin_reward = min_pin_reward
        self.max_pin_reward = max_pin_reward

        self._entries: Dict[str, DWCCEntry] = {}

    def track_request(
        self, content_hash: str, semantic_tier: Optional[SemanticValueTier] = None
    ) -> None:
        """
        Track a content request event.

        Args:
            content_hash: Hash of requested content
            semantic_tier: Optional semantic importance tier
        """
        now = datetime.now(timezone.utc).timestamp()

        if content_hash not in self._entries:
            self._entries[content_hash] = DWCCEntry(
                content_hash=content_hash,
                semantic_tier=semantic_tier or SemanticValueTier.MEDIUM,
            )

        entry = self._entries[content_hash]
        entry.requests += 1
        entry.last_requested = now

        if semantic_tier:
            entry.semantic_tier = semantic_tier

    def calculate_dwcc(
        self, content_hash: str, current_time: Optional[float] = None
    ) -> float:
        """
        Calculate DWCC reward for a content hash.

        Formula: DWCC = base_rate × (requests × storage_duration × semantic_value)

        Args:
            content_hash: Hash to calculate reward for
            current_time: Optional timestamp (defaults to now)

        Returns:
            Credit reward amount
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc).timestamp()

        if content_hash not in self._entries:
            return 0.0

        entry = self._entries[content_hash]

        # Calculate storage duration in hours
        storage_hours = (current_time - entry.first_seen) / 3600.0

        # Apply decay for inactivity
        hours_since_last_request = (current_time - entry.last_requested) / 3600.0
        decay_multiplier = max(0.1, 1.0 - (self.decay_rate * hours_since_last_request))

        # Calculate raw DWCC
        raw_dwcc = (
            self.base_rate
            * entry.requests
            * storage_hours
            * entry.semantic_tier.value
            * decay_multiplier
        )

        # Clamp to min/max bounds
        clamped = max(self.min_pin_reward, min(self.max_pin_reward, raw_dwcc))

        return clamped

    def process_epoch(self, epoch_duration_hours: float = 1.0) -> Dict[str, float]:
        """
        Process an epoch and calculate rewards for all pinned content.

        Args:
            epoch_duration_hours: Duration of epoch in hours

        Returns:
            Dict mapping content_hash → credit reward
        """
        current_time = datetime.now(timezone.utc).timestamp()
        rewards: Dict[str, float] = {}

        for content_hash, entry in self._entries.items():
            if entry.pinned:
                reward = self.calculate_dwcc(content_hash, current_time)
                rewards[content_hash] = reward
                entry.total_earned += reward

        return rewards

    def get_eviction_candidates(self, threshold_requests: int = 1) -> List[str]:
        """
        Get list of content hashes that are candidates for eviction.

        Low-demand content with minimal requests becomes unpinned.

        Args:
            threshold_requests: Max requests before considered for eviction

        Returns:
            List of content hashes ready for eviction
        """
        current_time = datetime.now(timezone.utc).timestamp()
        candidates = []

        for content_hash, entry in self._entries.items():
            if not entry.pinned:
                continue

            # Check if below request threshold
            if entry.requests < threshold_requests:
                # Check if decayed significantly
                hours_inactive = (current_time - entry.last_requested) / 3600.0
                if hours_inactive > 24:  # 24 hours inactive
                    candidates.append(content_hash)

        return candidates

    def unpin_content(self, content_hash: str) -> bool:
        """
        Unpin content from archival (marks for eviction).

        Args:
            content_hash: Hash to unpin

        Returns:
            True if unpinned, False if not found
        """
        if content_hash in self._entries:
            self._entries[content_hash].pinned = False
            return True
        return False

    def get_entry(self, content_hash: str) -> Optional[DWCCEntry]:
        """Get entry for a content hash."""
        return self._entries.get(content_hash)

    def get_all_entries(self) -> Dict[str, DWCCEntry]:
        """Get all tracked entries."""
        return dict(self._entries)

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall statistics."""
        if not self._entries:
            return {
                "total_tracked": 0,
                "pinned_count": 0,
                "total_requests": 0,
                "total_earned": 0.0,
                "by_tier": {},
            }

        by_tier: Dict[str, int] = {}
        total_requests = 0
        total_earned = 0.0
        pinned_count = 0

        for entry in self._entries.values():
            tier_name = entry.semantic_tier.name
            by_tier[tier_name] = by_tier.get(tier_name, 0) + 1
            total_requests += entry.requests
            total_earned += entry.total_earned
            if entry.pinned:
                pinned_count += 1

        return {
            "total_tracked": len(self._entries),
            "pinned_count": pinned_count,
            "unpinned_count": len(self._entries) - pinned_count,
            "total_requests": total_requests,
            "total_earned": total_earned,
            "by_tier": by_tier,
        }
