# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Shard manager for content distribution across P2P mesh network.

This module handles optimal shard distribution across peers,
considering bandwidth, storage, reputation, and latency.
"""

import asyncio
import hashlib
import hmac as _hmac
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime

from ..peer.peer_repository import PeerRepository
from ..peer.peer_models import Peer, PeerCapabilities, PeerFilters
from ..fountain.raptorq_ffi import RealRaptorQAdapter, RaptorQError

log = logging.getLogger(__name__)


@dataclass
class DistributionPlan:
    """Plan for distributing content shards across peers."""
    
    content_hash: str
    total_shards: int
    required_shards: int  # Minimum shards needed for reconstruction
    shard_assignments: Dict[int, List[str]] = field(default_factory=dict)  # shard_index -> [peer_ids]
    redundancy_factor: int = 3
    estimated_time_ms: float = 0.0
    
    def __post_init__(self):
        """Validate distribution plan."""
        if self.required_shards > self.total_shards:
            raise ValueError("Required shards cannot exceed total shards")


@dataclass
class DistributionResult:
    """Result of content distribution operation."""
    
    success: bool
    content_hash: str
    shards_distributed: int
    shards_failed: int
    peer_ids: List[str]
    distribution_time_ms: float
    errors: List[str] = field(default_factory=list)


class ShardManager:
    """
    Manages content shard distribution across peer network.
    
    Uses existing RaptorQ fountain coding for encoding and optimizes
    distribution based on peer capabilities, reputation, and network conditions.
    """
    
    def __init__(
        self,
        peer_repo: PeerRepository,
        raptorq_adapter: Optional[RealRaptorQAdapter] = None
    ):
        self._peer_repo = peer_repo
        self._raptorq_adapter = raptorq_adapter or RealRaptorQAdapter()
        self._distribution_cache: Dict[str, DistributionPlan] = {}
        self._cache_ttl = 300  # 5 minutes
    
    async def calculate_optimal_distribution(
        self,
        content_hash: str,
        content_size: int,
        redundancy: int = 3,
        preferred_peers: Optional[List[str]] = None
    ) -> DistributionPlan:
        """
        Calculate optimal shard distribution across peers.
        
        Args:
            content_hash: Content identifier
            content_size: Size of content in bytes
            redundancy: Redundancy multiplier (3x = each shard on 3 peers)
            preferred_peers: Preferred peer IDs for distribution
            
        Returns:
            Distribution plan with shard assignments
        """
        start_time = time.time()
        
        # Check cache first
        cache_key = f"{content_hash}:{redundancy}"
        if cache_key in self._distribution_cache:
            cached_time, cached_plan = self._distribution_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                log.debug("Returning cached distribution plan for %s", content_hash)
                return cached_plan
        
        # Get available peers with storage capability
        from ..peer.peer_models import PeerFilters
        filters = PeerFilters(
            status="active",
            has_storage=True,
            min_reputation=50,
            limit=100
        )
        
        available_peers = await self._peer_repo.list_peers(filters)
        
        if not available_peers:
            raise ValueError("No peers available with storage capability")
        
        # Calculate number of shards needed
        shard_size = self._raptorq_adapter.shard_size
        total_shards = (content_size + shard_size - 1) // shard_size
        required_shards = total_shards
        
        # Calculate number of peers needed for redundancy
        peers_needed = max(1, (total_shards * redundancy) // len(available_peers))
        if peers_needed > len(available_peers):
            log.warning(
                "Not enough peers for %dx redundancy: need %d, have %d",
                redundancy, peers_needed, len(available_peers)
            )
        
        # Score peers based on multiple factors
        scored_peers = self._score_peers(available_peers, content_size)
        
        # Prioritize preferred peers
        if preferred_peers:
            scored_peers = self._prioritize_peers(scored_peers, preferred_peers)
        
        # Select top peers
        selected_peers = scored_peers[:min(len(scored_peers), peers_needed)]
        
        # Assign shards to peers
        shard_assignments = self._assign_shards(
            total_shards,
            selected_peers,
            redundancy
        )
        
        plan = DistributionPlan(
            content_hash=content_hash,
            total_shards=total_shards,
            required_shards=required_shards,
            shard_assignments=shard_assignments,
            redundancy_factor=redundancy,
            estimated_time_ms=(time.time() - start_time) * 1000
        )
        
        # Cache the plan
        self._distribution_cache[cache_key] = (time.time(), plan)
        
        log.info(
            "Calculated distribution plan for %s: %d shards across %d peers (redundancy=%d)",
            content_hash,
            total_shards,
            len(selected_peers),
            redundancy
        )
        
        return plan
    
    def _score_peers(
        self,
        peers: List[Peer],
        content_size: int
    ) -> List[Tuple[float, Peer]]:
        """
        Score peers based on capabilities and network conditions.
        
        Args:
            peers: List of available peers
            content_size: Size of content to distribute
            
        Returns:
            List of (score, peer) tuples sorted by score descending
        """
        scored = []
        
        for peer in peers:
            if not peer.capabilities:
                continue
            
            score = 0.0
            
            # Reputation score (0-100 points) - 40% weight
            score += peer.reputation_score * 0.4
            
            # Bandwidth score - 25% weight
            # Normalize bandwidth: 1000 kbps = 1.0, cap at 10000 kbps
            bandwidth_score = min(peer.capabilities.bandwidth_kbps / 10000.0, 1.0) * 25
            score += bandwidth_score
            
            # Storage score - 20% weight
            storage_score = 20 if peer.capabilities.storage else 0
            score += storage_score
            
            # Availability score - 15% weight
            # Based on last_seen time (more recent = higher score)
            if peer.last_seen:
                hours_since_seen = (datetime.now() - peer.last_seen).total_seconds() / 3600
                availability_score = max(0, 15 - hours_since_seen)
                score += availability_score
            else:
                score += 15  # Assume available if last_seen is unknown
            
            scored.append((score, peer))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored
    
    def _prioritize_peers(
        self,
        scored_peers: List[Tuple[float, Peer]],
        preferred_peers: List[str]
    ) -> List[Tuple[float, Peer]]:
        """
        Prioritize preferred peers in the scored list.
        
        Args:
            scored_peers: List of (score, peer) tuples
            preferred_peers: Peer IDs to prioritize
            
        Returns:
            Reordered list with preferred peers first
        """
        preferred_set = set(preferred_peers)
        
        # Separate preferred and non-preferred
        preferred = []
        non_preferred = []
        
        for score, peer in scored_peers:
            if peer.peer_id in preferred_set:
                preferred.append((score, peer))
            else:
                non_preferred.append((score, peer))
        
        # Return preferred first, then non-preferred
        return preferred + non_preferred
    
    def _assign_shards(
        self,
        total_shards: int,
        peers: List[Tuple[float, Peer]],
        redundancy: int
    ) -> Dict[int, List[str]]:
        """
        Assign shards to peers with redundancy.
        
        Args:
            total_shards: Total number of shards
            peers: List of (score, peer) tuples
            redundancy: Redundancy multiplier
            
        Returns:
            Dictionary mapping shard_index to list of peer_ids
        """
        shard_assignments: Dict[int, List[str]] = {}
        peer_ids = [peer.peer_id for _, peer in peers]
        
        # Assign each shard to redundancy number of peers
        for shard_index in range(total_shards):
            # Use round-robin assignment for even distribution
            assigned_peers = []
            
            for i in range(redundancy):
                peer_index = (shard_index * redundancy + i) % len(peer_ids)
                assigned_peers.append(peer_ids[peer_index])
            
            shard_assignments[shard_index] = assigned_peers
        
        return shard_assignments
    
    async def distribute_shards(
        self,
        content_hash: str,
        content_data: bytes,
        hmac_key: Optional[bytes] = None,
        redundancy: float = 0.05
    ) -> DistributionResult:
        """
        Execute content distribution across peer network.
        
        Args:
            content_hash: Content identifier
            content_data: Raw content bytes
            hmac_key: Optional HMAC key for shard integrity
            redundancy: Redundancy fraction for RaptorQ encoding
            
        Returns:
            Distribution result with success/failure information
        """
        start_time = time.time()
        
        try:
            # Encode content into shards using RaptorQ
            shards = self._raptorq_adapter.encode(
                content_data,
                redundancy=redundancy,
                hmac_key=hmac_key
            )
            
            log.info("Encoded %s into %d shards", content_hash, len(shards))
            
            # Calculate distribution plan
            plan = await self.calculate_optimal_distribution(
                content_hash,
                len(content_data),
                redundancy=int(redundancy * 10)  # Convert to integer multiplier
            )
            
            # Distribute shards to peers
            shards_distributed = 0
            shards_failed = 0
            peer_ids_used: Set[str] = set()
            errors = []
            
            for shard_index, shard_data in enumerate(shards):
                assigned_peers = plan.shard_assignments.get(shard_index, [])
                
                for peer_id in assigned_peers:
                    try:
                        # In a real implementation, this would send the shard to the peer
                        # For now, we simulate successful distribution
                        await self._peer_repo.register_shard(
                            content_hash=content_hash,
                            shard_index=shard_index,
                            shard_hash=hashlib.sha256(shard_data).hexdigest(),
                            size_bytes=len(shard_data),
                            parity_shard=shard_index >= plan.required_shards
                        )
                        
                        await self._peer_repo.register_shard_location(
                            content_hash=content_hash,
                            shard_index=shard_index,
                            peer_id=peer_id,
                            availability_score=1.0
                        )
                        
                        shards_distributed += 1
                        peer_ids_used.add(peer_id)
                        
                    except Exception as e:
                        shards_failed += 1
                        errors.append(f"Shard {shard_index} to peer {peer_id}: {str(e)}")
                        log.error("Failed to distribute shard %d to peer %s: %s", 
                                shard_index, peer_id, e)
            
            # Update content distribution status
            await self._update_distribution_status(
                content_hash,
                "completed" if shards_failed == 0 else "partial"
            )
            
            distribution_time = (time.time() - start_time) * 1000
            
            result = DistributionResult(
                success=shards_failed == 0,
                content_hash=content_hash,
                shards_distributed=shards_distributed,
                shards_failed=shards_failed,
                peer_ids=list(peer_ids_used),
                distribution_time_ms=distribution_time,
                errors=errors
            )
            
            log.info(
                "Distribution completed for %s: %d shards distributed, %d failed in %.0fms",
                content_hash,
                shards_distributed,
                shards_failed,
                distribution_time
            )
            
            return result
            
        except RaptorQError as e:
            log.error("RaptorQ encoding failed for %s: %s", content_hash, e)
            return DistributionResult(
                success=False,
                content_hash=content_hash,
                shards_distributed=0,
                shards_failed=0,
                peer_ids=[],
                distribution_time_ms=(time.time() - start_time) * 1000,
                errors=[f"RaptorQ encoding failed: {str(e)}"]
            )
        except Exception as e:
            log.error("Distribution failed for %s: %s", content_hash, e)
            return DistributionResult(
                success=False,
                content_hash=content_hash,
                shards_distributed=0,
                shards_failed=0,
                peer_ids=[],
                distribution_time_ms=(time.time() - start_time) * 1000,
                errors=[f"Distribution failed: {str(e)}"]
            )
    
    async def _update_distribution_status(self, content_hash: str, status: str) -> bool:
        """
        Update distribution status in database.
        
        Args:
            content_hash: Content identifier
            status: Distribution status (pending, in_progress, completed, partial, failed)
            
        Returns:
            True if update was successful
        """
        # This would update the content table's distribution_status column
        # For now, we'll just log it
        log.info("Distribution status for %s: %s", content_hash, status)
        return True
    
    async def get_distribution_status(self, content_hash: str) -> Dict[str, any]:
        """
        Get current distribution status for content.
        
        Args:
            content_hash: Content identifier
            
        Returns:
            Dictionary with distribution status information
        """
        # Get shard locations from repository
        shard_locations = await self._peer_repo.get_shard_peers(content_hash)
        
        # Calculate distribution percentage
        # (This is a simplified calculation - real implementation would use actual plan)
        total_shards = len(shard_locations)
        distributed_peers = len(set(loc.peer_id for loc in shard_locations))
        
        return {
            "content_hash": content_hash,
            "status": "in_progress" if total_shards > 0 else "pending",
            "total_shards": total_shards,
            "distributed_peers": distributed_peers,
            "shard_locations": [
                {
                    "shard_index": loc.shard_index,
                    "peer_id": loc.peer_id,
                    "availability_score": loc.availability_score
                }
                for loc in shard_locations
            ]
        }