"""
Pinning Manager - Content pinning with decay

Manages the lifecycle of pinned content:
- Pins high-value content for archival
- Applies time-based decay for inactive content
- Evicts low-demand content to free storage
- Integrates with DWCC for economic incentives
"""

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone

from tfp_client.lib.credit.dwcc_calculator import DWCCCalculator, SemanticValueTier


@dataclass
class PinnedContent:
    """Represents a piece of pinned content."""
    content_hash: str
    size_bytes: int
    pinned_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    last_accessed: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    access_count: int = 0
    semantic_tier: SemanticValueTier = SemanticValueTier.MEDIUM
    priority_score: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "pinned_at": self.pinned_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "semantic_tier": self.semantic_tier.value,
            "priority_score": self.priority_score
        }


class PinningManager:
    """
    Manages content pinning with economic decay.
    
    Features:
    - Priority-based pinning (high-demand content gets priority)
    - Time-based decay (inactive content loses priority)
    - Storage quota enforcement
    - Integration with DWCC calculator
    - Eviction callbacks for cleanup
    """
    
    def __init__(
        self,
        max_storage_bytes: int = 1_000_000_000,  # 1 GB default
        decay_rate_per_hour: float = 0.01,
        min_priority_threshold: float = 0.2,
        eviction_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize pinning manager.
        
        Args:
            max_storage_bytes: Maximum storage quota
            decay_rate_per_hour: Priority decay per hour of inactivity
            min_priority_threshold: Minimum priority before eviction consideration
            eviction_callback: Optional callback(hash) when content is evicted
        """
        self.max_storage_bytes = max_storage_bytes
        self.decay_rate_per_hour = decay_rate_per_hour
        self.min_priority_threshold = min_priority_threshold
        self._eviction_callback = eviction_callback
        
        self._pinned: Dict[str, PinnedContent] = {}
        self._total_pinned_bytes: int = 0
        self._lock = threading.RLock()
        
        # DWCC integration
        self._dwcc = DWCCCalculator()
    
    def pin(
        self,
        content_hash: str,
        size_bytes: int,
        semantic_tier: SemanticValueTier = SemanticValueTier.MEDIUM,
        initial_priority: float = 1.0
    ) -> bool:
        """
        Pin content for archival.
        
        Args:
            content_hash: Hash of content to pin
            size_bytes: Size of content in bytes
            semantic_tier: Semantic importance tier
            initial_priority: Initial priority score
            
        Returns:
            True if pinned successfully, False if rejected (e.g., quota exceeded)
        """
        with self._lock:
            # Check if already pinned
            if content_hash in self._pinned:
                return False
            
            # Check storage quota
            if self._total_pinned_bytes + size_bytes > self.max_storage_bytes:
                # Try to make room by evicting low-priority content
                self._evict_low_priority(target_bytes=size_bytes)
                
                # Check again after eviction
                if self._total_pinned_bytes + size_bytes > self.max_storage_bytes:
                    return False
            
            # Pin the content
            pinned = PinnedContent(
                content_hash=content_hash,
                size_bytes=size_bytes,
                semantic_tier=semantic_tier,
                priority_score=initial_priority
            )
            
            self._pinned[content_hash] = pinned
            self._total_pinned_bytes += size_bytes
            
            # Track in DWCC
            self._dwcc.track_request(content_hash, semantic_tier)
            
            return True
    
    def access(self, content_hash: str) -> Optional[PinnedContent]:
        """
        Record an access event for pinned content.
        
        Increases priority and resets decay timer.
        
        Args:
            content_hash: Hash of accessed content
            
        Returns:
            PinnedContent if found, None otherwise
        """
        with self._lock:
            if content_hash not in self._pinned:
                return None
            
            pinned = self._pinned[content_hash]
            pinned.access_count += 1
            pinned.last_accessed = datetime.now(timezone.utc).timestamp()
            
            # Boost priority based on semantic tier
            tier_boost = pinned.semantic_tier.value * 0.1
            pinned.priority_score = min(10.0, pinned.priority_score + tier_boost + 0.1)
            
            # Track request in DWCC
            self._dwcc.track_request(content_hash, pinned.semantic_tier)
            
            return pinned
    
    def unpin(self, content_hash: str) -> bool:
        """
        Unpin content from archival.
        
        Args:
            content_hash: Hash to unpin
            
        Returns:
            True if unpinned, False if not found
        """
        with self._lock:
            if content_hash not in self._pinned:
                return False
            
            pinned = self._pinned.pop(content_hash)
            self._total_pinned_bytes -= pinned.size_bytes
            
            # Mark as unpinned in DWCC
            self._dwcc.unpin_content(content_hash)
            
            return True
    
    def get_priority_score(self, content_hash: str) -> Optional[float]:
        """Get current priority score for content."""
        with self._lock:
            if content_hash not in self._pinned:
                return None
            
            # Apply decay before returning
            self._apply_decay(content_hash)
            return self._pinned[content_hash].priority_score
    
    def apply_decay_all(self) -> List[str]:
        """
        Apply decay to all pinned content.
        
        Returns:
            List of content hashes that fell below threshold
        """
        with self._lock:
            below_threshold = []
            current_time = datetime.now(timezone.utc).timestamp()
            
            for content_hash, pinned in list(self._pinned.items()):
                # Calculate hours since last access
                hours_inactive = (current_time - pinned.last_accessed) / 3600.0
                
                # Apply decay
                decay_amount = self.decay_rate_per_hour * hours_inactive
                pinned.priority_score = max(0.0, pinned.priority_score - decay_amount)
                
                # Reset access timer
                if hours_inactive > 0:
                    pinned.last_accessed = current_time
                
                # Check threshold
                if pinned.priority_score < self.min_priority_threshold:
                    below_threshold.append(content_hash)
            
            return below_threshold
    
    def get_eviction_candidates(self, limit: int = 10) -> List[str]:
        """
        Get list of content hashes recommended for eviction.
        
        Sorted by priority score (lowest first).
        
        Args:
            limit: Maximum number of candidates to return
            
        Returns:
            List of content hashes
        """
        with self._lock:
            # First apply decay
            self.apply_decay_all()
            
            # Sort by priority score
            sorted_items = sorted(
                self._pinned.items(),
                key=lambda x: x[1].priority_score
            )
            
            # Return lowest priority items
            candidates = [
                item[0] for item in sorted_items[:limit]
                if item[1].priority_score < self.min_priority_threshold
            ]
            
            return candidates
    
    def evict(self, content_hash: str) -> bool:
        """
        Evict content from the pinning manager.
        
        Args:
            content_hash: Hash to evict
            
        Returns:
            True if evicted, False if not found
        """
        with self._lock:
            if content_hash not in self._pinned:
                return False
            
            pinned = self._pinned.pop(content_hash)
            self._total_pinned_bytes -= pinned.size_bytes
            
            # Call eviction callback
            if self._eviction_callback:
                try:
                    self._eviction_callback(content_hash)
                except Exception:
                    pass  # Don't let callback errors break eviction
            
            return True
    
    def _evict_low_priority(self, target_bytes: int = 0) -> int:
        """
        Evict low-priority content to free space.
        
        Must be called with lock held.
        
        Args:
            target_bytes: Target bytes to free (0 = just clean up threshold violations)
            
        Returns:
            Bytes freed
        """
        # Apply decay first
        below_threshold = self.apply_decay_all()
        
        freed_bytes = 0
        
        # First evict items below threshold
        for content_hash in below_threshold:
            if content_hash in self._pinned:
                pinned = self._pinned[content_hash]
                freed_bytes += pinned.size_bytes
                self.evict(content_hash)
                
                # Check if we've freed enough
                if target_bytes > 0 and freed_bytes >= target_bytes:
                    return freed_bytes
        
        # If still need more space, evict lowest priority items
        if target_bytes > 0 and freed_bytes < target_bytes:
            sorted_items = sorted(
                self._pinned.items(),
                key=lambda x: x[1].priority_score
            )
            
            for content_hash, pinned in sorted_items:
                if freed_bytes >= target_bytes:
                    break
                
                freed_bytes += pinned.size_bytes
                self.evict(content_hash)
        
        return freed_bytes
    
    def _apply_decay(self, content_hash: str) -> None:
        """Apply decay to a single item. Must be called with lock held."""
        if content_hash not in self._pinned:
            return
        
        pinned = self._pinned[content_hash]
        current_time = datetime.now(timezone.utc).timestamp()
        hours_inactive = (current_time - pinned.last_accessed) / 3600.0
        
        decay_amount = self.decay_rate_per_hour * hours_inactive
        pinned.priority_score = max(0.0, pinned.priority_score - decay_amount)
        pinned.last_accessed = current_time
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pinning statistics."""
        with self._lock:
            by_tier: Dict[str, int] = {}
            total_access_count = 0
            
            for pinned in self._pinned.values():
                tier_name = pinned.semantic_tier.name
                by_tier[tier_name] = by_tier.get(tier_name, 0) + 1
                total_access_count += pinned.access_count
            
            return {
                "pinned_count": len(self._pinned),
                "total_pinned_bytes": self._total_pinned_bytes,
                "max_storage_bytes": self.max_storage_bytes,
                "utilization": self._total_pinned_bytes / self.max_storage_bytes if self.max_storage_bytes > 0 else 0,
                "by_tier": by_tier,
                "total_access_count": total_access_count,
                "dwcc_stats": self._dwcc.get_statistics()
            }
    
    def get_pinned_content(self, content_hash: str) -> Optional[PinnedContent]:
        """Get pinned content by hash."""
        with self._lock:
            return self._pinned.get(content_hash)
    
    def get_all_pinned(self) -> Dict[str, PinnedContent]:
        """Get all pinned content."""
        with self._lock:
            return dict(self._pinned)
