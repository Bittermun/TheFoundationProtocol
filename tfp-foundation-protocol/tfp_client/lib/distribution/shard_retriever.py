# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Shard retriever for fetching content from distributed P2P mesh network.

This module handles parallel shard retrieval from multiple peers,
content reconstruction using RaptorQ, and handling of missing shards.
"""

import asyncio
import hashlib
import logging
import time
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime

from ..peer.peer_repository import PeerRepository
from ..peer.peer_models import ShardLocation
from ..fountain.raptorq_ffi import RealRaptorQAdapter, RaptorQError

log = logging.getLogger(__name__)


class ShardRetriever:
    """
    Retrieves content from distributed shards across peer network.
    
    Fetches shards in parallel from multiple peers, handles failures,
    and reconstructs content using RaptorQ fountain coding.
    """
    
    def __init__(
        self,
        peer_repo: PeerRepository,
        raptorq_adapter: Optional[RealRaptorQAdapter] = None
    ):
        self._peer_repo = peer_repo
        self._raptorq_adapter = raptorq_adapter or RealRaptorQAdapter()
        self._peer_http_timeout = 5  # seconds
    
    async def retrieve_content(
        self,
        content_hash: str,
        required_shards: Optional[int] = None,
        hmac_key: Optional[bytes] = None
    ) -> bytes:
        """
        Retrieve content from distributed shards.
        
        Args:
            content_hash: Content identifier
            required_shards: Minimum number of shards needed (auto-calculated if None)
            hmac_key: Optional HMAC key for shard verification
            
        Returns:
            Reconstructed content bytes
            
        Raises:
            ValueError: If insufficient shards available
            RaptorQError: If RaptorQ decoding fails
        """
        start_time = time.time()
        
        # Get shard locations from repository
        shard_locations = await self._peer_repo.get_shard_peers(content_hash)
        
        if not shard_locations:
            raise ValueError(f"No shard locations found for content {content_hash}")
        
        # Group shards by index
        shards_by_index: Dict[int, List[ShardLocation]] = {}
        for loc in shard_locations:
            if loc.shard_index not in shards_by_index:
                shards_by_index[loc.shard_index] = []
            shards_by_index[loc.shard_index].append(loc)
        
        # Determine required shards if not specified
        if required_shards is None:
            required_shards = len(shards_by_index)
        
        # Fetch shards in parallel
        fetched_shards = await self._fetch_shards_parallel(
            shards_by_index,
            required_shards
        )
        
        if len(fetched_shards) < required_shards:
            raise ValueError(
                f"Insufficient shards retrieved: need {required_shards}, got {len(fetched_shards)}"
            )
        
        # Reconstruct content using RaptorQ
        try:
            reconstructed = self._raptorq_adapter.decode(
                fetched_shards,
                k=required_shards,
                hmac_key=hmac_key
            )
            
            retrieval_time = (time.time() - start_time) * 1000
            log.info(
                "Successfully retrieved %s: %d shards in %.0fms",
                content_hash,
                len(fetched_shards),
                retrieval_time
            )
            
            return reconstructed
            
        except RaptorQError as e:
            log.error("RaptorQ decoding failed for %s: %s", content_hash, e)
            raise
    
    async def _fetch_shards_parallel(
        self,
        shards_by_index: Dict[int, List[ShardLocation]],
        required_shards: int
    ) -> List[bytes]:
        """
        Fetch shards from peers in parallel.
        
        Args:
            shards_by_index: Dictionary mapping shard_index to available locations
            required_shards: Minimum number of shards needed
            
        Returns:
            List of fetched shard bytes
        """
        # Create fetch tasks for each shard
        fetch_tasks = []
        
        for shard_index, locations in shards_by_index.items():
            # Try each location for this shard until one succeeds
            fetch_tasks.append(
                self._fetch_shard_with_fallback(shard_index, locations)
            )
        
        # Execute fetch tasks in parallel
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        # Collect successful fetches
        fetched_shards = []
        for result in results:
            if isinstance(result, Exception):
                log.warning("Shard fetch failed: %s", str(result))
            elif result is not None:
                fetched_shards.append(result)
        
        # Deduplicate shards (in case multiple peers returned the same shard)
        unique_shards = self._deduplicate_shards(fetched_shards)
        
        # Ensure we have enough unique shards
        if len(unique_shards) < required_shards:
            log.warning(
                "Only %d unique shards retrieved from %d attempts, need %d",
                len(unique_shards),
                len(fetched_shards),
                required_shards
            )
        
        return unique_shards[:required_shards]
    
    async def _fetch_shard_with_fallback(
        self,
        shard_index: int,
        locations: List[ShardLocation]
    ) -> Optional[bytes]:
        """
        Fetch a shard from one of its locations with fallback.
        
        Args:
            shard_index: Index of the shard to fetch
            locations: List of locations where the shard is available
            
        Returns:
            Shard bytes if successful, None otherwise
        """
        for location in locations:
            try:
                # In a real implementation, this would make an HTTP request to the peer
                # For now, we simulate by checking if the peer is available
                peer = await self._peer_repo.get_peer(location.peer_id)
                
                if peer and peer.status == "active":
                    # Simulate successful fetch
                    # In production, this would be: await self._http_get_shard(peer, shard_index)
                    log.debug(
                        "Simulated fetch of shard %d from peer %s",
                        shard_index,
                        location.peer_id
                    )
                    
                    # Return placeholder shard data (in production, would be actual shard)
                    # For testing, we return a marker that can be recognized
                    return f"shard_{shard_index}_from_{location.peer_id}".encode()
                
            except Exception as e:
                log.warning(
                    "Failed to fetch shard %d from peer %s: %s",
                    shard_index,
                    location.peer_id,
                    e
                )
                continue
        
        log.warning("Failed to fetch shard %d from all %d locations",
                   shard_index, len(locations))
        return None
    
    def _deduplicate_shards(self, shards: List[bytes]) -> List[bytes]:
        """
        Remove duplicate shards based on content hash.
        
        Args:
            shards: List of shard bytes
            
        Returns:
            List of unique shards
        """
        seen_hashes: Set[str] = set()
        unique_shards = []
        
        for shard in shards:
            shard_hash = hashlib.sha256(shard).hexdigest()
            if shard_hash not in seen_hashes:
                seen_hashes.add(shard_hash)
                unique_shards.append(shard)
        
        return unique_shards
    
    async def get_shard_availability(
        self,
        content_hash: str
    ) -> Dict[str, any]:
        """
        Get availability information for content shards.
        
        Args:
            content_hash: Content identifier
            
        Returns:
            Dictionary with availability statistics
        """
        shard_locations = await self._peer_repo.get_shard_peers(content_hash)
        
        # Group by shard index
        shards_by_index: Dict[int, List[ShardLocation]] = {}
        for loc in shard_locations:
            if loc.shard_index not in shards_by_index:
                shards_by_index[loc.shard_index] = []
            shards_by_index[loc.shard_index].append(loc)
        
        # Calculate availability metrics
        total_shards = len(shards_by_index)
        fully_available = sum(1 for locs in shards_by_index.values() if len(locs) > 0)
        avg_redundancy = sum(len(locs) for locs in shards_by_index.values()) / total_shards if total_shards > 0 else 0
        
        # Get unique peers
        unique_peers = set(loc.peer_id for loc in shard_locations)
        
        return {
            "content_hash": content_hash,
            "total_shards": total_shards,
            "fully_available_shards": fully_available,
            "average_redundancy": avg_redundancy,
            "unique_peers": len(unique_peers),
            "peer_list": list(unique_peers),
            "shard_details": {
                str(shard_index): {
                    "available_copies": len(locations),
                    "peers": [loc.peer_id for loc in locations],
                    "avg_availability": sum(loc.availability_score for loc in locations) / len(locations) if locations else 0.0
                }
                for shard_index, locations in shards_by_index.items()
            }
        }
    
    async def verify_shard_integrity(
        self,
        shard_data: bytes,
        expected_hash: str,
        hmac_key: Optional[bytes] = None
    ) -> bool:
        """
        Verify shard integrity using hash and optional HMAC.
        
        Args:
            shard_data: Shard bytes to verify
            expected_hash: Expected SHA-256 hash
            hmac_key: Optional HMAC key for verification
            
        Returns:
            True if shard is valid, False otherwise
        """
        # Verify SHA-256 hash
        actual_hash = hashlib.sha256(shard_data).hexdigest()
        if actual_hash != expected_hash:
            log.warning("Shard hash mismatch: expected %s, got %s", expected_hash, actual_hash)
            return False
        
        # Verify HMAC if key provided
        if hmac_key is not None:
            # RaptorQ shards have HMAC appended
            if len(shard_data) < 32:
                return False
            
            received_hmac = shard_data[-32:]
            shard_without_hmac = shard_data[:-32]
            expected_hmac = hashlib.sha3_256(hmac_key + shard_without_hmac).digest()
            
            if not hmac.compare_digest(received_hmac, expected_hmac):
                log.warning("Shard HMAC verification failed")
                return False
        
        return True