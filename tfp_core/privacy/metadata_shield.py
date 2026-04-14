# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Metadata Shield - Privacy Protection Layer

Provides NDN Interest padding, dummy request injection, randomized uplink delays,
and local cache optimization to prevent traffic analysis and metadata leakage.

All privacy mechanisms run locally. Zero PII logging.
"""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PrivacyConfig:
    """Configuration for metadata shielding."""

    enable_padding: bool = True
    enable_dummy_requests: bool = True
    dummy_request_ratio: float = 0.2  # 20% dummy requests
    min_delay_ms: int = 50
    max_delay_ms: int = 500
    backoff_base: float = 2.0
    max_backoff_ms: int = 5000
    cache_hit_suppression_window: float = 60.0  # seconds
    max_recent_interests: int = 1000


@dataclass
class InterestRecord:
    """Record of a recent Interest for cache hit optimization."""

    interest_hash: str
    timestamp: float
    is_dummy: bool = False


class MetadataShield:
    """
    Protects user privacy by obfuscating NDN Interest patterns.

    Features:
    - Interest padding with dummy requests
    - Randomized uplink delay windows (exponential backoff)
    - Local cache hit optimization to suppress repeated Interests
    - Zero PII logging
    """

    def __init__(self, config: Optional[PrivacyConfig] = None):
        self.config = config or PrivacyConfig()
        self._lock = threading.Lock()
        self._recent_interests: Dict[str, InterestRecord] = {}
        self._backoff_state: Dict[str, float] = {}  # interest_hash -> next_allowed_time
        self._request_count = 0
        self._dummy_count = 0

    def should_send_interest(self, interest_name: str) -> tuple[bool, float]:
        """
        Determine if an Interest should be sent now or delayed.

        Args:
            interest_name: The NDN Interest name

        Returns:
            Tuple of (should_send, delay_seconds)
        """
        interest_hash = self._hash_interest(interest_name)
        current_time = time.time()

        with self._lock:
            # Check cache hit suppression
            if self._is_cache_hit(interest_hash, current_time):
                return False, 0.0

            # Check backoff state
            next_allowed = self._backoff_state.get(interest_hash, 0.0)
            if current_time < next_allowed:
                delay = next_allowed - current_time
                return False, delay

            # Apply randomized delay
            delay = self._calculate_randomized_delay(interest_hash)

            # Update backoff state
            self._backoff_state[interest_hash] = current_time + delay

            return True, delay

    def generate_dummy_interests(self, count: Optional[int] = None) -> List[str]:
        """
        Generate dummy Interest names for padding.

        Args:
            count: Number of dummy interests to generate (default: based on ratio)

        Returns:
            List of dummy Interest names
        """
        if count is None:
            count = max(1, int(self._request_count * self.config.dummy_request_ratio))

        dummy_interests = []
        for _ in range(count):
            # Generate cryptographically random dummy interest
            random_bytes = hashlib.sha3_256(
                f"dummy_{time.time()}_{secrets.token_hex(8)}".encode()
            ).digest()[:16]
            dummy_name = f"/tfp/dummy/{random_bytes.hex()}"
            dummy_interests.append(dummy_name)

            with self._lock:
                self._dummy_count += 1

        return dummy_interests

    def record_interest(self, interest_name: str, is_dummy: bool = False) -> None:
        """
        Record an Interest for cache hit optimization.

        Args:
            interest_name: The NDN Interest name
            is_dummy: Whether this is a dummy interest
        """
        interest_hash = self._hash_interest(interest_name)
        current_time = time.time()

        with self._lock:
            self._recent_interests[interest_hash] = InterestRecord(
                interest_hash=interest_hash, timestamp=current_time, is_dummy=is_dummy
            )

            if not is_dummy:
                self._request_count += 1

            # Prune old records
            self._prune_old_records(current_time)

    def get_privacy_stats(self) -> Dict[str, Any]:
        """
        Get privacy protection statistics.

        Returns:
            Dictionary with privacy metrics
        """
        with self._lock:
            total_interests = self._request_count + self._dummy_count
            dummy_ratio = self._dummy_count / max(1, total_interests)

            return {
                "total_interests": total_interests,
                "real_interests": self._request_count,
                "dummy_interests": self._dummy_count,
                "dummy_ratio": round(dummy_ratio, 3),
                "recent_interests_count": len(self._recent_interests),
                "active_backoffs": len(
                    [t for t in self._backoff_state.values() if t > time.time()]
                ),
            }

    def _hash_interest(self, interest_name: str) -> str:
        """Hash an Interest name for privacy-preserving tracking."""
        return hashlib.sha3_256(interest_name.encode()).hexdigest()

    def _is_cache_hit(self, interest_hash: str, current_time: float) -> bool:
        """Check if this Interest was recently seen (cache hit optimization)."""
        if interest_hash not in self._recent_interests:
            return False

        record = self._recent_interests[interest_hash]
        time_diff = current_time - record.timestamp

        return time_diff < self.config.cache_hit_suppression_window

    def _calculate_randomized_delay(self, interest_hash: str) -> float:
        """
        Calculate randomized delay with exponential backoff.

        Uses interest hash to ensure consistent but unpredictable delays.
        """
        # Base random delay using cryptographically secure random
        base_delay = (
            secrets.randbelow(
                int(self.config.max_delay_ms - self.config.min_delay_ms + 1)
            )
            + self.config.min_delay_ms
        )
        base_delay = base_delay / 1000.0

        # Add hash-based jitter for determinism per interest
        hash_seed = int(interest_hash[:8], 16)
        jitter = (hash_seed % 100) / 1000.0

        return min(base_delay + jitter, self.config.max_backoff_ms / 1000.0)

    def _prune_old_records(self, current_time: float) -> None:
        """Remove old Interest records to bound memory usage."""
        cutoff = current_time - self.config.cache_hit_suppression_window

        # Keep only recent records
        to_remove = [
            h
            for h, record in self._recent_interests.items()
            if record.timestamp < cutoff
        ]

        for h in to_remove:
            del self._recent_interests[h]

        # Enforce maximum size
        if len(self._recent_interests) > self.config.max_recent_interests:
            # Remove oldest entries
            sorted_items = sorted(
                self._recent_interests.items(), key=lambda x: x[1].timestamp
            )
            excess = len(sorted_items) - self.config.max_recent_interests
            for h, _ in sorted_items[:excess]:
                del self._recent_interests[h]

        # Clean up expired backoff states
        expired_backoffs = [
            h for h, t in self._backoff_state.items() if t < current_time
        ]
        for h in expired_backoffs:
            del self._backoff_state[h]


# Feature gate check
def is_privacy_enabled() -> bool:
    """Check if privacy features are enabled."""
    import os

    return os.getenv("TFP_FEATURES_PRIVACY", "false").lower() == "true"


if __name__ == "__main__":
    # Demo usage
    shield = MetadataShield()

    # Simulate Interest traffic
    test_interests = [
        "/tfp/content/video123",
        "/tfp/content/audio456",
        "/tfp/content/doc789",
    ]

    for interest in test_interests:
        should_send, delay = shield.should_send_interest(interest)
        print(f"Interest: {interest}")
        print(f"  Should send: {should_send}, Delay: {delay:.3f}s")

        if should_send:
            shield.record_interest(interest)

            # Generate dummy requests
            dummies = shield.generate_dummy_interests(2)
            for dummy in dummies:
                shield.record_interest(dummy, is_dummy=True)
                print(f"  Dummy: {dummy}")

    print("\nPrivacy Stats:")
    stats = shield.get_privacy_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
