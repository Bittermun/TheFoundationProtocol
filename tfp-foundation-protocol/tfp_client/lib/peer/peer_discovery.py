# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer discovery and handshake logic for P2P mesh networking.

This module provides the core logic for peer discovery, capability exchange,
and secure handshake establishment using existing TFP security mechanisms.
"""

import hashlib
import hmac as _hmac
import logging
import secrets
import time
from typing import List, Dict, Any

from .peer_models import (
    Peer,
    PeerInfo,
    PeerCapabilities,
    ConnectionMetrics,
    PeerDiscoverRequest,
    PeerDiscoverResponse,
    PeerHandshakeRequest,
    PeerHandshakeResponse,
    PeerFilters,
)
from .peer_repository import PeerRepository

log = logging.getLogger(__name__)


class PeerDiscovery:
    """
    Peer discovery service for P2P mesh networking.
    
    Handles peer registration, capability exchange, and discovery
    using existing TFP device authentication mechanisms.
    """

    def __init__(self, peer_repo: PeerRepository, device_registry) -> None:
        self._peer_repo = peer_repo
        self._device_registry = device_registry
        self._discovery_cache: Dict[str, List[Peer]] = {}
        self._cache_ttl = 300  # 5 minutes

    async def discover_peers(
        self,
        request: PeerDiscoverRequest,
        local_device_id: str
    ) -> PeerDiscoverResponse:
        """
        Discover peers in the network.
        
        Args:
            request: Discovery request with capabilities and preferences
            local_device_id: Local device ID for authentication
            
        Returns:
            Discovery response with available peers
        """
        start_time = time.time()
        
        # Check cache first
        cache_key = self._make_cache_key(request)
        if cache_key in self._discovery_cache:
            cached_time, cached_peers = self._discovery_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                log.debug("Returning cached peer discovery results")
                return PeerDiscoverResponse(
                    peers=cached_peers,
                    total_count=len(cached_peers)
                )
        
        # Build filters from request
        filters = PeerFilters(
            status="active",
            min_reputation=50,
            has_compute=request.capabilities.compute if request.capabilities else None,
            has_storage=request.capabilities.storage if request.capabilities else None,
            min_bandwidth=request.capabilities.bandwidth_kbps if request.capabilities else None,
            limit=request.max_peers
        )
        
        # Get peers from repository
        available_peers = await self._peer_repo.list_peers(filters)
        
        # Filter out local peer
        other_peers = [p for p in available_peers if p.peer_id != local_device_id]
        
        # Apply preferred peer ordering
        if request.preferred_peers:
            preferred_peers = [p for p in other_peers if p.peer_id in request.preferred_peers]
            other_peers = [p for p in other_peers if p.peer_id not in request.preferred_peers]
            other_peers = preferred_peers + other_peers
        
        # Limit results
        result_peers = other_peers[:request.max_peers]
        
        # Cache results
        self._discovery_cache[cache_key] = (time.time(), result_peers)
        
        discovery_time = (time.time() - start_time) * 1000
        log.info(
            "Peer discovery completed: found %d peers in %.0fms",
            len(result_peers),
            discovery_time
        )
        
        return PeerDiscoverResponse(
            peers=result_peers,
            total_count=len(other_peers)
        )

    async def announce_peer(
        self,
        peer_info: PeerInfo,
        local_device_id: str
    ) -> Peer:
        """
        Announce peer to the network.
        
        Args:
            peer_info: Peer information to announce
            local_device_id: Local device ID for authentication
            
        Returns:
            Registered peer information
        """
        # Register peer in repository
        registered_peer = await self._peer_repo.register_peer(peer_info)
        
        # Clear discovery cache to force refresh
        self._discovery_cache.clear()
        
        log.info("Peer announced: %s at %s:%s", 
                peer_info.peer_id, peer_info.ip_address, peer_info.port)
        
        return registered_peer

    async def update_peer_presence(self, peer_id: str) -> bool:
        """
        Update peer last seen timestamp.
        
        Args:
            peer_id: Peer identifier
            
        Returns:
            True if update was successful
        """
        return await self._peer_repo.update_peer_last_seen(peer_id)

    def _make_cache_key(self, request: PeerDiscoverRequest) -> str:
        """Create cache key from discovery request."""
        key_parts = [
            str(request.capabilities.compute) if request.capabilities else "None",
            str(request.capabilities.storage) if request.capabilities else "None",
            str(request.capabilities.bandwidth_kbps) if request.capabilities else "None",
            str(request.max_peers),
            ",".join(sorted(request.preferred_peers)) if request.preferred_peers else ""
        ]
        return ":".join(key_parts)


class PeerHandshake:
    """
    Peer handshake service for secure P2P communication.
    
    Handles cryptographic handshake using existing TFP PUF/TEE identity
    and HMAC device authentication mechanisms.
    """

    def __init__(self, peer_repo: PeerRepository, device_registry) -> None:
        self._peer_repo = peer_repo
        self._device_registry = device_registry
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        self._session_ttl = 3600  # 1 hour

    async def perform_handshake(
        self,
        request: PeerHandshakeRequest,
        local_device_id: str
    ) -> PeerHandshakeResponse:
        """
        Perform cryptographic handshake with peer.
        
        Args:
            request: Handshake request with peer info and optional challenge
            local_device_id: Local device ID for authentication
            
        Returns:
            Handshake response with session information
        """
        start_time = time.time()
        
        # Get or register local peer
        local_peer = await self._peer_repo.get_peer(local_device_id)
        if not local_peer:
            # Auto-register with device's public key from registry
            peer_info = PeerInfo(
                peer_id=local_device_id,
                public_key="",  # Will be populated from device context
                capabilities=request.capabilities,
                reputation_score=100,
                status="active"
            )
            local_peer = await self._peer_repo.register_peer(peer_info)
        
        # Generate session token
        session_token = secrets.token_hex(16)
        session_id = f"{local_device_id}:{request.peer_id}:{session_token}"
        
        # Handle challenge-response if provided
        challenge_response = None
        if request.challenge:
            challenge_response = await self._process_challenge(
                request.challenge,
                local_device_id,
                request.peer_id
            )
        
        # Store session information
        self._active_sessions[session_id] = {
            "local_peer_id": local_device_id,
            "remote_peer_id": request.peer_id,
            "created_at": time.time(),
            "capabilities": request.capabilities.model_dump() if request.capabilities else {}
        }
        
        # Record connection
        await self._peer_repo.record_connection(
            local_device_id,
            request.peer_id,
            "direct",
            ConnectionMetrics(latency_ms=None, bandwidth_kbps=None)
        )
        
        handshake_time = (time.time() - start_time) * 1000
        log.info(
            "Peer handshake completed: %s <-> %s in %.0fms",
            local_device_id,
            request.peer_id,
            handshake_time
        )
        
        return PeerHandshakeResponse(
            success=True,
            peer_id=local_device_id,
            public_key=local_peer.public_key,
            challenge_response=challenge_response,
            session_token=session_token,
            capabilities=local_peer.capabilities
        )

    async def verify_session(self, session_id: str) -> bool:
        """
        Verify if a session is still valid.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if session is valid, False otherwise
        """
        if session_id not in self._active_sessions:
            return False
        
        session = self._active_sessions[session_id]
        if time.time() - session["created_at"] > self._session_ttl:
            del self._active_sessions[session_id]
            return False
        
        return True

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        current_time = time.time()
        expired_sessions = [
            session_id for session_id, session in self._active_sessions.items()
            if current_time - session["created_at"] > self._session_ttl
        ]
        
        for session_id in expired_sessions:
            del self._active_sessions[session_id]
        
        if expired_sessions:
            log.info("Cleaned up %d expired peer sessions", len(expired_sessions))
        
        return len(expired_sessions)

    async def _process_challenge(
        self,
        challenge: str,
        local_device_id: str,
        remote_peer_id: str
    ) -> str:
        """
        Process cryptographic challenge.
        
        In production, this would use proper cryptographic methods.
        For now, it provides a basic challenge-response mechanism.
        
        Args:
            challenge: Challenge string from remote peer
            local_device_id: Local device ID
            remote_peer_id: Remote peer ID
            
        Returns:
            Challenge response
        """
        # Get device entropy for signing
        entropy = self._device_registry.get_entropy(local_device_id)
        if not entropy:
            raise ValueError("Device not enrolled")
        
        # Create challenge response using HMAC
        message = f"{local_device_id}:{remote_peer_id}:{challenge}"
        response = _hmac.new(entropy, message.encode(), hashlib.sha256).hexdigest()
        
        return f"challenge:{response}"


class CapabilityExchange:
    """
    Capability exchange service for peer resource negotiation.
    
    Handles exchange of peer capabilities (compute, storage, bandwidth)
    to enable intelligent peer selection and resource allocation.
    """

    def __init__(self, peer_repo: PeerRepository) -> None:
        self._peer_repo = peer_repo

    async def negotiate_capabilities(
        self,
        local_capabilities: PeerCapabilities,
        remote_peer_id: str
    ) -> Dict[str, Any]:
        """
        Negotiate capabilities with remote peer.
        
        Args:
            local_capabilities: Local peer capabilities
            remote_peer_id: Remote peer ID
            
        Returns:
            Negotiation result with compatibility assessment
        """
        remote_peer = await self._peer_repo.get_peer(remote_peer_id)
        if not remote_peer or not remote_peer.capabilities:
            return {
                "compatible": False,
                "reason": "Remote peer not found or capabilities unknown"
            }
        
        remote_caps = remote_peer.capabilities
        
        # Check compatibility
        compatibility = {
            "compute": local_capabilities.compute and remote_caps.compute,
            "storage": local_capabilities.storage and remote_caps.storage,
            "bandwidth": min(local_capabilities.bandwidth_kbps, remote_caps.bandwidth_kbps)
        }
        
        is_compatible = all([
            compatibility["compute"],
            compatibility["storage"],
            compatibility["bandwidth"] > 0
        ])
        
        return {
            "compatible": is_compatible,
            "local_capabilities": local_capabilities.model_dump(),
            "remote_capabilities": remote_caps.model_dump(),
            "compatibility": compatibility,
            "recommended_action": "connect" if is_compatible else "skip"
        }

    async def get_optimal_peers(
        self,
        required_capabilities: PeerCapabilities,
        count: int = 5
    ) -> List[Peer]:
        """
        Get optimal peers matching required capabilities.
        
        Args:
            required_capabilities: Required capabilities
            count: Number of peers to return
            
        Returns:
            List of optimal peers
        """
        
        filters = PeerFilters(
            status="active",
            has_compute=required_capabilities.compute,
            has_storage=required_capabilities.storage,
            min_bandwidth=required_capabilities.bandwidth_kbps,
            min_reputation=70,
            limit=count * 2  # Get more for selection
        )
        
        peers = await self._peer_repo.list_peers(filters)
        
        # Sort by combined score (reputation + bandwidth)
        scored_peers = []
        for peer in peers:
            if peer.capabilities:
                score = (
                    peer.reputation_score * 0.7 +
                    min(peer.capabilities.bandwidth_kbps / 10000, 1.0) * 30
                )
                scored_peers.append((score, peer))
        
        # Sort by score descending and return top N
        scored_peers.sort(key=lambda x: x[0], reverse=True)
        return [peer for score, peer in scored_peers[:count]]