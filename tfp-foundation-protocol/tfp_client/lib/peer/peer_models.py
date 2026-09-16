# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer data models for P2P mesh networking.

This module defines Pydantic models for peer information, connections,
and related P2P networking data structures.
"""

from typing import Optional, Dict, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class PeerCapabilities(BaseModel):
    """Peer capabilities and resource information."""
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})
    
    compute: bool = True
    storage: bool = True
    bandwidth_kbps: int = 1000
    max_shards: int = 100
    cpu_cores: Optional[int] = None
    memory_mb: Optional[int] = None
    storage_gb: Optional[int] = None


class PeerInfo(BaseModel):
    """Peer information for registration and discovery."""
    
    peer_id: str = Field(..., description="Unique peer identifier")
    public_key: str = Field(..., description="Peer public key for verification")
    ip_address: Optional[str] = Field(None, description="Peer IP address")
    port: Optional[int] = Field(None, description="Peer port number")
    capabilities: Optional[PeerCapabilities] = Field(
        default_factory=PeerCapabilities,
        description="Peer capabilities and resources"
    )
    reputation_score: int = Field(
        default=100,
        ge=0,
        le=100,
        description="Peer reputation score (0-100)"
    )
    status: str = Field(
        default="active",
        description="Peer status: active, inactive, banned"
    )
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        """Validate peer status value."""
        valid_statuses = ['active', 'inactive', 'banned']
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class Peer(PeerInfo):
    """Extended peer model with database fields."""
    
    id: Optional[int] = Field(None, description="Database ID")
    last_seen: Optional[datetime] = Field(None, description="Last seen timestamp")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class ConnectionMetrics(BaseModel):
    """Connection performance metrics."""
    
    latency_ms: Optional[int] = Field(None, description="Connection latency in milliseconds")
    bandwidth_kbps: Optional[int] = Field(None, description="Connection bandwidth in kbps")
    packet_loss: Optional[float] = Field(None, ge=0, le=1, description="Packet loss rate")
    uptime_seconds: Optional[int] = Field(None, description="Connection uptime in seconds")


class PeerConnection(BaseModel):
    """Peer connection information."""
    
    local_peer_id: str = Field(..., description="Local peer ID")
    remote_peer_id: str = Field(..., description="Remote peer ID")
    connection_type: str = Field(
        ...,
        description="Connection type: direct, relay, dht"
    )
    metrics: Optional[ConnectionMetrics] = Field(
        default_factory=ConnectionMetrics,
        description="Connection performance metrics"
    )
    last_active: Optional[datetime] = Field(None, description="Last activity timestamp")
    
    @field_validator('connection_type')
    @classmethod
    def validate_connection_type(cls, v):
        """Validate connection type value."""
        valid_types = ['direct', 'relay', 'dht']
        if v not in valid_types:
            raise ValueError(f"Connection type must be one of {valid_types}")
        return v
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class PeerFilters(BaseModel):
    """Filters for peer queries."""
    
    status: Optional[str] = Field("active", description="Filter by peer status")
    min_reputation: Optional[int] = Field(50, description="Minimum reputation score")
    has_compute: Optional[bool] = Field(None, description="Filter by compute capability")
    has_storage: Optional[bool] = Field(None, description="Filter by storage capability")
    min_bandwidth: Optional[int] = Field(None, description="Minimum bandwidth in kbps")
    limit: Optional[int] = Field(100, description="Maximum number of results")
    offset: Optional[int] = Field(0, description="Result offset for pagination")


class PeerDiscoverRequest(BaseModel):
    """Request model for peer discovery."""
    
    peer_id: str = Field(..., description="Requesting peer ID")
    capabilities: Optional[PeerCapabilities] = Field(
        default_factory=PeerCapabilities,
        description="Requesting peer capabilities"
    )
    max_peers: Optional[int] = Field(50, description="Maximum number of peers to return")
    preferred_peers: Optional[List[str]] = Field(
        default_factory=list,
        description="Preferred peer IDs for connection"
    )


class PeerDiscoverResponse(BaseModel):
    """Response model for peer discovery."""
    
    peers: List[Peer] = Field(default_factory=list, description="Discovered peers")
    total_count: int = Field(..., description="Total number of available peers")
    request_time: datetime = Field(default_factory=datetime.now, description="Request timestamp")


class PeerHandshakeRequest(BaseModel):
    """Request model for peer handshake."""
    
    peer_id: str = Field(..., description="Requesting peer ID")
    public_key: str = Field(..., description="Requesting peer public key")
    challenge: Optional[str] = Field(None, description="Cryptographic challenge")
    capabilities: Optional[PeerCapabilities] = Field(
        default_factory=PeerCapabilities,
        description="Requesting peer capabilities"
    )


class PeerHandshakeResponse(BaseModel):
    """Response model for peer handshake."""
    
    success: bool = Field(..., description="Handshake success status")
    peer_id: str = Field(..., description="Responding peer ID")
    public_key: str = Field(..., description="Responding peer public key")
    challenge_response: Optional[str] = Field(None, description="Response to challenge")
    session_token: Optional[str] = Field(None, description="Session token for secure communication")
    capabilities: Optional[PeerCapabilities] = Field(None, description="Responding peer capabilities")


class PeerAnnounceRequest(BaseModel):
    """Request model for peer announcement."""
    
    peer_id: str = Field(..., description="Announcing peer ID")
    public_key: str = Field(..., description="Announcing peer public key")
    ip_address: Optional[str] = Field(None, description="Announcing peer IP address")
    port: Optional[int] = Field(None, description="Announcing peer port")
    capabilities: Optional[PeerCapabilities] = Field(
        default_factory=PeerCapabilities,
        description="Announcing peer capabilities"
    )
    signature: str = Field(..., description="Message signature for verification")


class ContentShard(BaseModel):
    """Content shard information."""
    
    id: Optional[int] = Field(None, description="Database ID")
    content_hash: str = Field(..., description="Parent content hash")
    shard_index: int = Field(..., ge=0, description="Shard index")
    shard_hash: str = Field(..., description="Shard content hash")
    size_bytes: int = Field(..., gt=0, description="Shard size in bytes")
    parity_shard: bool = Field(default=False, description="Whether this is a parity shard")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class ShardLocation(BaseModel):
    """Shard location information."""
    
    id: Optional[int] = Field(None, description="Database ID")
    content_hash: str = Field(..., description="Parent content hash")
    shard_index: int = Field(..., ge=0, description="Shard index")
    peer_id: str = Field(..., description="Hosting peer ID")
    availability_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Peer availability score (0.0-1.0)"
    )
    last_verified: Optional[datetime] = Field(None, description="Last verification timestamp")
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class MeshRoute(BaseModel):
    """Mesh routing information."""
    
    id: Optional[int] = Field(None, description="Database ID")
    destination_peer_id: str = Field(..., description="Destination peer ID")
    next_hop_peer_id: str = Field(..., description="Next hop peer ID")
    hop_count: int = Field(default=1, ge=1, description="Number of hops")
    latency_ms: Optional[int] = Field(None, description="Route latency in milliseconds")
    route_quality: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Route quality score (0.0-1.0)"
    )
    last_updated: Optional[datetime] = Field(None, description="Last update timestamp")
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class GossipMessage(BaseModel):
    """Gossip protocol message."""
    
    id: Optional[int] = Field(None, description="Database ID")
    message_type: str = Field(..., description="Message type")
    payload: Dict[str, Any] = Field(..., description="Message payload")
    source_peer_id: str = Field(..., description="Source peer ID")
    ttl: int = Field(default=10, ge=0, description="Time-to-live in hops")
    signature: str = Field(..., description="Message signature")
    received_at: Optional[datetime] = Field(None, description="Receipt timestamp")
    processed: bool = Field(default=False, description="Processing status")
    
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})