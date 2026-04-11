"""
TFP Mutualistic Defense System v2.8

Replaces global reputation with Local Trust Caches + Gossip Verification + Domain-Specific Weighting.
Addresses: Sybil attacks, false positives, audit fatigue, censorship via metadata.

Key Principles:
1. No permanent slashing (mistakes pause rights, don't burn credits)
2. Local trust > Global consensus (users curate their own auditor lists)
3. Randomized sampling (catches low-volume malware)
4. Versioned heuristic packs (signed, rollback-capable)
5. Tag decay (requires fresh attestations)
"""

import hashlib
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class TrustLevel(Enum):
    """Trust levels for auditors and content."""

    UNKNOWN = 0
    SUSPICIOUS = 1
    NEUTRAL = 2
    TRUSTED = 3
    HIGHLY_TRUSTED = 4


@dataclass
class AuditorProfile:
    """Local cache entry for an auditor's reputation."""

    auditor_id: str
    trust_level: TrustLevel = TrustLevel.NEUTRAL
    accuracy_score: float = 0.5  # 0.0 to 1.0
    total_audits: int = 0
    correct_audits: int = 0
    false_positives: int = 0
    last_interaction: float = field(default_factory=time.time)
    domain_expertise: Dict[str, float] = field(
        default_factory=dict
    )  # category -> score
    cooldown_until: float = 0.0  # Timestamp when cooldown ends

    def update_accuracy(self, was_correct: bool, category: str = None):
        """Update accuracy metrics after verification."""
        self.total_audits += 1
        if was_correct:
            self.correct_audits += 1
        else:
            self.false_positives += 1
        self.accuracy_score = self.correct_audits / max(1, self.total_audits)

        # Update domain expertise if category provided and audit was correct
        if category and was_correct:
            current = self.domain_expertise.get(category, 0.5)
            self.domain_expertise[category] = min(1.0, current + 0.05)

        # Adjust trust level based on accuracy
        if self.accuracy_score >= 0.95 and self.total_audits >= 50:
            self.trust_level = TrustLevel.HIGHLY_TRUSTED
        elif self.accuracy_score >= 0.85 and self.total_audits >= 20:
            self.trust_level = TrustLevel.TRUSTED
        elif self.accuracy_score < 0.6 and self.total_audits >= 10:
            self.trust_level = TrustLevel.SUSPICIOUS

    def is_on_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def apply_cooldown(self, duration_hours: float = 24.0):
        """Apply temporary cooldown instead of slashing."""
        self.cooldown_until = time.time() + (duration_hours * 3600)

    def get_domain_weight(self, category: str) -> float:
        """Get trust weight for specific content category."""
        return self.domain_expertise.get(category, 0.5)


@dataclass
class ContentTag:
    """Metadata tag for content with decay mechanism."""

    content_hash: str
    tag_type: str  # 'malware', 'toxic', 'misleading', 'safe'
    confidence: float  # 0.0 to 1.0
    attestations: List[str] = field(default_factory=list)  # Auditor IDs
    created_at: float = field(default_factory=time.time)
    last_refreshed: float = field(default_factory=time.time)
    decay_rate: float = 0.1  # Confidence loss per day
    half_life_days: float = 7.0  # Confidence halves every N days

    def decay(self) -> float:
        """Apply time-based decay to confidence. Returns new confidence."""
        age_days = (time.time() - self.last_refreshed) / 86400.0
        decay_factor = 0.5 ** (age_days / self.half_life_days)
        self.confidence *= decay_factor
        return self.confidence

    def needs_refresh(self) -> bool:
        """Check if tag needs fresh attestation."""
        return self.decay() < 0.5 or len(self.attestations) < 2

    def add_attestation(self, auditor_id: str):
        """Add new attestation and refresh timestamp."""
        if auditor_id not in self.attestations:
            self.attestations.append(auditor_id)
        self.last_refreshed = time.time()
        self.confidence = min(1.0, self.confidence + 0.1)


@dataclass
class HeuristicPack:
    """Versioned heuristic rules for malware detection."""

    version: str
    signature: str  # Cryptographic signature
    rules: Dict[str, dict]  # rule_id -> {pattern, threshold, category}
    created_at: float = field(default_factory=time.time)
    is_active: bool = True

    def verify_signature(self, public_key: bytes) -> bool:
        """Verify pack signature before applying."""
        # Simplified: In production, use Ed25519
        import hashlib

        data = f"{self.version}:{str(self.rules)}".encode()
        expected_hash = hashlib.sha3_256(data).hexdigest()
        return self.signature == expected_hash[:16]


class LocalTrustCache:
    """
    Personal trust cache maintained by each user.
    No global consensus required.
    """

    def __init__(self, device_id: str, max_auditors: int = 1000):
        self.device_id = device_id
        self.max_auditors = max_auditors
        self.auditors: Dict[str, AuditorProfile] = {}
        self.trusted_pinned: Set[str] = set()  # Manually pinned trusted auditors

    def get_auditor(self, auditor_id: str) -> Optional[AuditorProfile]:
        return self.auditors.get(auditor_id)

    def update_auditor(self, auditor_id: str, was_correct: bool, category: str = None):
        """Update auditor metrics based on outcome."""
        if auditor_id not in self.auditors:
            self.auditors[auditor_id] = AuditorProfile(auditor_id=auditor_id)

        profile = self.auditors[auditor_id]
        profile.update_accuracy(was_correct)
        profile.last_interaction = time.time()

        if category and was_correct:
            # Improve domain expertise
            current = profile.domain_expertise.get(category, 0.5)
            profile.domain_expertise[category] = min(1.0, current + 0.05)

        # Evict lowest-trust if over capacity (unless pinned)
        if len(self.auditors) > self.max_auditors:
            self._evict_lowest_trust()

    def _evict_lowest_trust(self):
        """Remove lowest-trust unpinned auditor."""
        candidates = [
            (aid, prof)
            for aid, prof in self.auditors.items()
            if aid not in self.trusted_pinned
        ]
        if candidates:
            worst = min(candidates, key=lambda x: x[1].accuracy_score)
            del self.auditors[worst[0]]

    def pin_auditor(self, auditor_id: str):
        """Manually pin an auditor as trusted."""
        self.trusted_pinned.add(auditor_id)
        if auditor_id in self.auditors:
            self.auditors[auditor_id].trust_level = TrustLevel.HIGHLY_TRUSTED

    def get_trusted_auditors(
        self, category: str = None, min_level: TrustLevel = TrustLevel.TRUSTED
    ) -> List[str]:
        """Get list of trusted auditors, optionally filtered by domain."""
        result = []
        for aid, profile in self.auditors.items():
            if (
                profile.trust_level.value >= min_level.value
                and not profile.is_on_cooldown()
            ):
                if category is None or profile.get_domain_weight(category) >= 0.7:
                    result.append(aid)
        return result


class GossipVerifier:
    """
    Lightweight gossip protocol for sharing trust signals.
    Does NOT enforce consensus, just shares observations.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.received_signals: List[dict] = []
        self.signal_expiry_hours = 24.0

    def broadcast_trust_signal(self, auditor_id: str, outcome: bool, category: str):
        """Create and broadcast a trust signal."""
        signal = {
            "reporter": self.device_id,
            "auditor": auditor_id,
            "outcome": outcome,
            "category": category,
            "timestamp": time.time(),
            "signature": self._sign_signal(auditor_id, outcome),
        }
        # In production: broadcast via NDN
        return signal

    def receive_trust_signal(self, signal: dict) -> bool:
        """Process incoming trust signal."""
        # Verify signature
        if not self._verify_signal(signal):
            return False

        # Check expiry
        age_hours = (time.time() - signal["timestamp"]) / 3600.0
        if age_hours > self.signal_expiry_hours:
            return False

        self.received_signals.append(signal)
        return True

    def aggregate_signals(self, auditor_id: str) -> Tuple[float, int]:
        """Aggregate received signals for an auditor."""
        recent = [
            s
            for s in self.received_signals
            if s["auditor"] == auditor_id
            and (time.time() - s["timestamp"]) / 3600.0 < self.signal_expiry_hours
        ]
        if not recent:
            return 0.5, 0

        positive = sum(1 for s in recent if s["outcome"])
        return positive / len(recent), len(recent)

    def _sign_signal(self, auditor_id: str, outcome: bool) -> str:
        """Sign trust signal (simplified)."""
        data = f"{self.device_id}:{auditor_id}:{outcome}".encode()
        return hashlib.sha3_256(data).hexdigest()[:16]

    def _verify_signal(self, signal: dict) -> bool:
        """Verify signal signature (simplified)."""
        expected = hashlib.sha3_256(
            f"{signal['reporter']}:{signal['auditor']}:{signal['outcome']}".encode()
        ).hexdigest()[:16]
        return signal["signature"] == expected


class MutualisticAuditor:
    """
    Main auditing engine with mutualistic defense mechanisms.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.trust_cache = LocalTrustCache(device_id)
        self.gossip = GossipVerifier(device_id)
        self.active_tags: Dict[str, ContentTag] = {}
        self.heuristic_packs: Dict[str, HeuristicPack] = {}

        # Randomized sampling configuration
        self.sample_rate_low_volume = 0.03  # 3% of sub-100-request content
        self.request_velocity_cap = 50  # Max requests/minute before rate limiting

    def audit_content(
        self,
        content_hash: str,
        content_data: bytes,
        category: str,
        request_count: int,
        auditor_id: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        Audit content with randomized sampling and domain-specific weighting.
        """
        # Check if already tagged
        existing_tag = self.active_tags.get(content_hash)
        if existing_tag and not existing_tag.needs_refresh():
            return {
                "status": "cached",
                "tags": [existing_tag.tag_type],
                "confidence": existing_tag.confidence,
            }

        # Randomized sampling for low-volume content using cryptographically secure random
        should_audit = (
            request_count >= 100  # High-demand: always audit
            or secrets.randbelow(100)
            < (self.sample_rate_low_volume * 100)  # Low-demand: random sample
        )

        if not should_audit:
            return {"status": "skipped", "reason": "low_volume_no_sample"}

        # Run heuristic analysis
        heuristic_result = self._run_heuristics(content_data, category)

        # Get trusted auditors for this domain
        trusted_auditors = self.trust_cache.get_trusted_auditors(category)

        # Combine heuristic + human audits
        final_confidence = heuristic_result["confidence"]
        final_tags = heuristic_result["tags"]

        if trusted_auditors:
            # Weight by domain expertise
            weighted_votes = []
            for aid in trusted_auditors[:5]:  # Top 5 trusted
                profile = self.trust_cache.get_auditor(aid)
                weight = profile.get_domain_weight(category) * profile.accuracy_score
                weighted_votes.append(weight)

            if weighted_votes:
                avg_weight = sum(weighted_votes) / len(weighted_votes)
                final_confidence = (final_confidence + avg_weight) / 2

        # Apply or update tag
        if final_confidence > 0.7:
            tag_type = "malware" if heuristic_result.get("is_malware") else "suspicious"
            if content_hash not in self.active_tags:
                self.active_tags[content_hash] = ContentTag(
                    content_hash=content_hash,
                    tag_type=tag_type,
                    confidence=final_confidence,
                )
            else:
                self.active_tags[content_hash].confidence = final_confidence
                self.active_tags[content_hash].last_refreshed = time.time()

        return {
            "status": "audited",
            "tags": final_tags,
            "confidence": final_confidence,
            "heuristic_match": heuristic_result.get("matched_rules", []),
        }

    def _run_heuristics(self, data: bytes, category: str) -> dict:
        """Run versioned heuristic packs on content."""
        tags = []
        confidence = 0.5
        matched_rules = []
        is_malware = False

        # Check entropy for steganography
        entropy = self._calculate_entropy(data)
        if entropy > 7.8:  # High entropy suggests encryption/compression
            tags.append("high_entropy")
            confidence += 0.2

        # Apply active heuristic packs
        for pack_id, pack in self.heuristic_packs.items():
            if not pack.is_active:
                continue

            for rule_id, rule in pack.rules.items():
                if rule.get("category") != category:
                    continue

                # Simple pattern matching (in production: use regex/ML)
                if rule["pattern"] in data.hex():
                    matched_rules.append(f"{pack_id}:{rule_id}")
                    if rule.get("severity") == "critical":
                        is_malware = True
                        tags.append("malware")
                        confidence = min(1.0, confidence + 0.4)

        return {
            "tags": tags,
            "confidence": min(1.0, confidence),
            "matched_rules": matched_rules,
            "is_malware": is_malware,
            "entropy": entropy,
        }

    def _calculate_entropy(self, data: bytes) -> float:
        """Calculate Shannon entropy of data."""
        if not data:
            return 0.0

        freq = defaultdict(int)
        for byte in data:
            freq[byte] += 1

        entropy = 0.0
        for count in freq.values():
            p = count / len(data)
            entropy -= p * (p and (p * 0.693147) or 0)  # ln(2) approximation

        return entropy / 0.693147  # Normalize to bits

    def report_audit_outcome(self, auditor_id: str, was_correct: bool, category: str):
        """
        Report audit outcome to update auditor reputation.
        Uses cooldown instead of slashing.
        """
        profile = self.trust_cache.get_auditor(auditor_id)
        if not profile:
            return

        self.trust_cache.update_auditor(auditor_id, was_correct, category)

        if not was_correct and profile.false_positives >= 5:
            # Apply cooldown instead of slashing
            profile.apply_cooldown(duration_hours=48.0)

    def update_heuristic_pack(self, pack: HeuristicPack, public_key: bytes) -> bool:
        """Install new heuristic pack after signature verification."""
        if not pack.verify_signature(public_key):
            return False

        # Deactivate old packs in same version family
        version_prefix = pack.version.split(".")[0]
        for existing in self.heuristic_packs.values():
            if existing.version.startswith(version_prefix):
                existing.is_active = False

        self.heuristic_packs[pack.version] = pack
        return True

    def decay_all_tags(self):
        """Apply decay to all active tags."""
        for tag in list(self.active_tags.values()):
            if tag.decay() < 0.3:
                # Remove very low-confidence tags
                del self.active_tags[tag.content_hash]


# Example usage and integration points
if __name__ == "__main__":
    # Initialize auditor for device
    auditor = MutualisticAuditor(device_id="device_123")

    # Pin trusted community auditors
    auditor.trust_cache.pin_auditor("community_auditor_1")
    auditor.trust_cache.pin_auditor("security_researcher_42")

    # Simulate content audit
    fake_video = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000  # Fake PNG with high entropy
    result = auditor.audit_content(
        content_hash="abc123",
        content_data=fake_video,
        category="video",
        request_count=150,
        auditor_id="volunteer_auditor",
    )

    print(f"Audit result: {result}")

    # Report outcome (e.g., user confirmed malware)
    auditor.report_audit_outcome(
        "volunteer_auditor", was_correct=True, category="video"
    )

    # Decay tags periodically
    auditor.decay_all_tags()

    print(f"Active tags: {len(auditor.active_tags)}")
    print("Mutualistic defense system ready.")
