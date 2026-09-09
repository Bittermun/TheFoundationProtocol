# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer repository for P2P mesh networking data access.

This module provides database access methods for peer registry,
connections, and related P2P networking operations.
"""

import sqlite3
import threading
import time
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from .peer_models import (
    Peer,
    PeerInfo,
    PeerConnection,
    PeerFilters,
    ConnectionMetrics,
    ContentShard,
    ShardLocation,
    MeshRoute,
    GossipMessage,
    PeerCapabilities,
)

log = logging.getLogger(__name__)


class PeerRepository:
    """
    Repository for peer-related database operations.
    
    Provides methods for:
    - Peer registration and discovery
    - Connection tracking
    - Content shard management
    - Mesh routing
    - Gossip message handling
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock

    # --------------------------------------------------------------------------
    # Peer Registry Operations
    # --------------------------------------------------------------------------

    async def register_peer(self, peer_info: PeerInfo) -> Peer:
        """
        Register or update peer information.
        
        Args:
            peer_info: Peer information to register
            
        Returns:
            Registered peer with database fields populated
        """
        with self._db_lock:
            current_time = time.time()
            
            # Convert capabilities to JSON for storage
            capabilities_json = json.dumps(peer_info.capabilities.model_dump()) if peer_info.capabilities else None
            
            # Check if peer already exists
            existing = self._conn.execute(
                "SELECT id, created_at FROM peer_registry WHERE peer_id = ?",
                (peer_info.peer_id,)
            ).fetchone()
            
            if existing:
                # Update existing peer
                cursor = self._conn.execute(
                    """
                    UPDATE peer_registry 
                    SET public_key = ?, ip_address = ?, port = ?, 
                        capabilities = ?, reputation_score = ?, status = ?, 
                        last_seen = ?
                    WHERE peer_id = ?
                    """,
                    (
                        peer_info.public_key,
                        peer_info.ip_address,
                        peer_info.port,
                        capabilities_json,
                        peer_info.reputation_score,
                        peer_info.status,
                        current_time,
                        peer_info.peer_id
                    )
                )
                peer_id = existing[0]
                created_at = existing[1]
            else:
                # Insert new peer
                cursor = self._conn.execute(
                    """
                    INSERT INTO peer_registry 
                    (peer_id, public_key, ip_address, port, capabilities, 
                     reputation_score, status, last_seen, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        peer_info.peer_id,
                        peer_info.public_key,
                        peer_info.ip_address,
                        peer_info.port,
                        capabilities_json,
                        peer_info.reputation_score,
                        peer_info.status,
                        current_time,
                        current_time
                    )
                )
                peer_id = cursor.lastrowid
                created_at = current_time
            
            self._conn.commit()
            
            # Return peer with database fields
            return Peer(
                id=peer_id,
                peer_id=peer_info.peer_id,
                public_key=peer_info.public_key,
                ip_address=peer_info.ip_address,
                port=peer_info.port,
                capabilities=peer_info.capabilities,
                reputation_score=peer_info.reputation_score,
                status=peer_info.status,
                last_seen=datetime.fromtimestamp(current_time),
                created_at=datetime.fromtimestamp(created_at)
            )

    async def get_peer(self, peer_id: str) -> Optional[Peer]:
        """
        Get peer by ID.
        
        Args:
            peer_id: Peer identifier
            
        Returns:
            Peer information or None if not found
        """
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT id, peer_id, public_key, ip_address, port, capabilities,
                       reputation_score, status, last_seen, created_at
                FROM peer_registry WHERE peer_id = ?
                """,
                (peer_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_peer(row)

    async def list_peers(self, filters: Optional[PeerFilters] = None) -> List[Peer]:
        """
        List peers with optional filtering.

        Args:
            filters: Filter criteria for peer selection

        Returns:
            List of peers matching the filters
        """
        if filters is None:
            filters = PeerFilters()

        with self._db_lock:
            # Build query with filters
            query = """
                SELECT id, peer_id, public_key, ip_address, port, capabilities,
                       reputation_score, status, last_seen, created_at
                FROM peer_registry WHERE 1=1
            """
            params = []

            if filters.status:
                query += " AND status = ?"
                params.append(filters.status)

            if filters.min_reputation is not None:
                query += " AND reputation_score >= ?"
                params.append(filters.min_reputation)

            # Add capability filters if specified
            if filters.has_compute is not None or filters.has_storage is not None:
                query += " AND capabilities IS NOT NULL"

            query += " ORDER BY reputation_score DESC, last_seen DESC"

            if filters.limit:
                query += " LIMIT ?"
                params.append(filters.limit)

            if filters.offset:
                query += " OFFSET ?"
                params.append(filters.offset)

            rows = self._conn.execute(query, params).fetchall()

            peers = [self._row_to_peer(row) for row in rows]

            # Apply capability filters in Python (since they're JSON)
            if filters.has_compute is not None or filters.has_storage is not None:
                peers = [
                    peer for peer in peers
                    if self._matches_capability_filters(peer, filters)
                ]

            return peers

    async def update_peer_status(self, peer_id: str, status: str) -> bool:
        """
        Update peer online status.
        
        Args:
            peer_id: Peer identifier
            status: New status (active, inactive, banned)
            
        Returns:
            True if update was successful, False otherwise
        """
        with self._db_lock:
            result = self._conn.execute(
                "UPDATE peer_registry SET status = ?, last_seen = ? WHERE peer_id = ?",
                (status, time.time(), peer_id)
            )
            self._conn.commit()
            return result.rowcount > 0

    async def update_peer_last_seen(self, peer_id: str) -> bool:
        """
        Update peer last seen timestamp.
        
        Args:
            peer_id: Peer identifier
            
        Returns:
            True if update was successful, False otherwise
        """
        with self._db_lock:
            result = self._conn.execute(
                "UPDATE peer_registry SET last_seen = ? WHERE peer_id = ?",
                (time.time(), peer_id)
            )
            self._conn.commit()
            return result.rowcount > 0

    async def delete_peer(self, peer_id: str) -> bool:
        """
        Delete peer from registry.
        
        Args:
            peer_id: Peer identifier
            
        Returns:
            True if deletion was successful, False otherwise
        """
        with self._db_lock:
            result = self._conn.execute(
                "DELETE FROM peer_registry WHERE peer_id = ?",
                (peer_id,)
            )
            self._conn.commit()
            return result.rowcount > 0

    # --------------------------------------------------------------------------
    # Peer Connection Operations
    # --------------------------------------------------------------------------

    async def record_connection(
        self,
        local_id: str,
        remote_id: str,
        connection_type: str,
        metrics: Optional[ConnectionMetrics] = None
    ) -> bool:
        """
        Record peer connection with performance metrics.
        
        Args:
            local_id: Local peer ID
            remote_id: Remote peer ID
            connection_type: Type of connection (direct, relay, dht)
            metrics: Connection performance metrics
            
        Returns:
            True if recording was successful, False otherwise
        """
        with self._db_lock:
            current_time = time.time()
            
            # Convert metrics to JSON for storage
            metrics_json = json.dumps(metrics.model_dump()) if metrics else None
            
            self._conn.execute(
                """
                INSERT INTO peer_connections 
                (local_peer_id, remote_peer_id, connection_type, latency_ms, 
                 bandwidth_kbps, last_active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    local_id,
                    remote_id,
                    connection_type,
                    metrics.latency_ms if metrics else None,
                    metrics.bandwidth_kbps if metrics else None,
                    current_time
                )
            )
            self._conn.commit()
            return True

    async def get_peer_connections(self, peer_id: str) -> List[PeerConnection]:
        """
        Get all connections for a peer.
        
        Args:
            peer_id: Peer identifier
            
        Returns:
            List of peer connections
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT local_peer_id, remote_peer_id, connection_type, 
                       latency_ms, bandwidth_kbps, last_active
                FROM peer_connections 
                WHERE local_peer_id = ? OR remote_peer_id = ?
                ORDER BY last_active DESC
                """,
                (peer_id, peer_id)
            ).fetchall()
            
            connections = []
            for row in rows:
                metrics = ConnectionMetrics(
                    latency_ms=row[3],
                    bandwidth_kbps=row[4]
                ) if row[3] or row[4] else None
                
                connections.append(PeerConnection(
                    local_peer_id=row[0],
                    remote_peer_id=row[1],
                    connection_type=row[2],
                    metrics=metrics,
                    last_active=datetime.fromtimestamp(row[5]) if row[5] else None
                ))
            
            return connections

    async def get_all_peer_connections(self) -> List[PeerConnection]:
        """
        Get all peer connections in the network.

        Returns:
            List of all peer connections
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT local_peer_id, remote_peer_id, connection_type,
                       latency_ms, bandwidth_kbps, last_active
                FROM peer_connections
                ORDER BY last_active DESC
                """
            ).fetchall()

            connections = []
            for row in rows:
                metrics = ConnectionMetrics(
                    latency_ms=row[3],
                    bandwidth_kbps=row[4]
                ) if row[3] or row[4] else None

                connections.append(
                    PeerConnection(
                        local_peer_id=row[0],
                        remote_peer_id=row[1],
                        connection_type=row[2],
                        metrics=metrics,
                        last_active=datetime.fromtimestamp(row[5]) if row[5] else None
                    )
                )

            return connections

    # --------------------------------------------------------------------------
    # Content Shard Operations
    # --------------------------------------------------------------------------

    async def register_shard(
        self,
        content_hash: str,
        shard_index: int,
        shard_hash: str,
        size_bytes: int,
        parity_shard: bool = False
    ) -> ContentShard:
        """
        Register a content shard.
        
        Args:
            content_hash: Parent content hash
            shard_index: Shard index
            shard_hash: Shard content hash
            size_bytes: Shard size in bytes
            parity_shard: Whether this is a parity shard
            
        Returns:
            Registered content shard
        """
        with self._db_lock:
            current_time = time.time()
            
            cursor = self._conn.execute(
                """
                INSERT INTO content_shards 
                (content_hash, shard_index, shard_hash, size_bytes, parity_shard, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (content_hash, shard_index, shard_hash, size_bytes, parity_shard, current_time)
            )
            shard_id = cursor.lastrowid
            self._conn.commit()
            
            return ContentShard(
                id=shard_id,
                content_hash=content_hash,
                shard_index=shard_index,
                shard_hash=shard_hash,
                size_bytes=size_bytes,
                parity_shard=parity_shard,
                created_at=datetime.fromtimestamp(current_time)
            )

    async def register_shard_location(
        self,
        content_hash: str,
        shard_index: int,
        peer_id: str,
        availability_score: float = 1.0,
        shard_size: Optional[int] = None
    ) -> bool:
        """
        Register that a peer hosts a specific shard.

        Args:
            content_hash: Parent content hash
            shard_index: Shard index
            peer_id: Hosting peer ID
            availability_score: Peer availability score
            shard_size: Optional shard size in bytes

        Returns:
            True if registration was successful, False otherwise
        """
        with self._db_lock:
            current_time = time.time()

            self._conn.execute(
                """
                INSERT INTO content_shard_locations
                (content_hash, shard_index, peer_id, availability_score, last_verified)
                VALUES (?, ?, ?, ?, ?)
                """,
                (content_hash, shard_index, peer_id, availability_score, current_time)
            )
            self._conn.commit()
            return True

    async def get_shard_peers(
        self,
        content_hash: str,
        shard_index: Optional[int] = None,
        min_availability: float = 0.5
    ) -> List[ShardLocation]:
        """
        Get peers hosting specific content shards.
        
        Args:
            content_hash: Parent content hash
            shard_index: Optional shard index filter
            min_availability: Minimum availability score
            
        Returns:
            List of shard locations
        """
        with self._db_lock:
            query = """
                SELECT id, content_hash, shard_index, peer_id, 
                       availability_score, last_verified
                FROM content_shard_locations 
                WHERE content_hash = ? AND availability_score >= ?
            """
            params = [content_hash, min_availability]
            
            if shard_index is not None:
                query += " AND shard_index = ?"
                params.append(shard_index)
            
            query += " ORDER BY availability_score DESC"
            
            rows = self._conn.execute(query, params).fetchall()
            
            return [
                ShardLocation(
                    id=row[0],
                    content_hash=row[1],
                    shard_index=row[2],
                    peer_id=row[3],
                    availability_score=row[4],
                    last_verified=datetime.fromtimestamp(row[5]) if row[5] else None
                )
                for row in rows
            ]

    async def is_content_distributed(self, content_hash: str) -> bool:
        """
        Check if content has been distributed to peers.

        Args:
            content_hash: Content hash to check

        Returns:
            True if content has shard locations registered, False otherwise
        """
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) FROM content_shard_locations
                WHERE content_hash = ?
                """,
                (content_hash,)
            ).fetchone()
            return row[0] > 0 if row else False

    async def get_distribution_status(self, content_hash: str) -> Optional[dict]:
        """
        Get distribution status for a piece of content.

        Args:
            content_hash: Content hash to query

        Returns:
            Dictionary with distribution status or None if not found
        """
        with self._db_lock:
            # Get shard metadata
            shard_rows = self._conn.execute(
                """
                SELECT shard_index, size_bytes, parity_shard
                FROM content_shards
                WHERE content_hash = ?
                ORDER BY shard_index
                """,
                (content_hash,)
            ).fetchall()

            if not shard_rows:
                return None

            # Get shard locations
            location_rows = self._conn.execute(
                """
                SELECT shard_index, peer_id, availability_score, last_verified
                FROM content_shard_locations
                WHERE content_hash = ?
                ORDER BY shard_index, availability_score DESC
                """,
                (content_hash,)
            ).fetchall()

            # Build status
            total_shards = len(shard_rows)
            data_shards = sum(1 for r in shard_rows if not r[2])
            parity_shards = total_shards - data_shards

            locations_by_shard = {}
            for row in location_rows:
                shard_idx = row[0]
                if shard_idx not in locations_by_shard:
                    locations_by_shard[shard_idx] = []
                locations_by_shard[shard_idx].append({
                    "peer_id": row[1],
                    "availability_score": row[2],
                    "last_verified": datetime.fromtimestamp(row[3]).isoformat() if row[3] else None
                })

            distributed_shards = len(locations_by_shard)
            coverage_percent = (distributed_shards / total_shards * 100) if total_shards > 0 else 0

            return {
                "content_hash": content_hash,
                "total_shards": total_shards,
                "data_shards": data_shards,
                "parity_shards": parity_shards,
                "distributed_shards": distributed_shards,
                "coverage_percent": round(coverage_percent, 2),
                "shard_locations": locations_by_shard,
                "state": "distributed" if coverage_percent >= 100 else "partial" if coverage_percent > 0 else "not_distributed"
            }

    # --------------------------------------------------------------------------
    # Mesh Routing Operations
    # --------------------------------------------------------------------------

    async def upsert_route(
        self,
        destination_peer_id: str,
        next_hop_peer_id: str,
        hop_count: int = 1,
        latency_ms: Optional[int] = None,
        route_quality: float = 1.0
    ) -> bool:
        """
        Insert or update a mesh route.
        
        Args:
            destination_peer_id: Destination peer ID
            next_hop_peer_id: Next hop peer ID
            hop_count: Number of hops
            latency_ms: Route latency in milliseconds
            route_quality: Route quality score
            
        Returns:
            True if operation was successful, False otherwise
        """
        with self._db_lock:
            current_time = time.time()
            
            # Check if route already exists
            existing = self._conn.execute(
                """
                SELECT id FROM mesh_routes 
                WHERE destination_peer_id = ? AND next_hop_peer_id = ?
                """,
                (destination_peer_id, next_hop_peer_id)
            ).fetchone()
            
            if existing:
                # Update existing route
                cursor = self._conn.execute(
                    """
                    UPDATE mesh_routes 
                    SET hop_count = ?, latency_ms = ?, route_quality = ?, last_updated = ?
                    WHERE destination_peer_id = ? AND next_hop_peer_id = ?
                    """,
                    (hop_count, latency_ms, route_quality, current_time, 
                     destination_peer_id, next_hop_peer_id)
                )
            else:
                # Insert new route
                cursor = self._conn.execute(
                    """
                    INSERT INTO mesh_routes 
                    (destination_peer_id, next_hop_peer_id, hop_count, 
                     latency_ms, route_quality, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (destination_peer_id, next_hop_peer_id, hop_count, 
                     latency_ms, route_quality, current_time)
                )
            
            self._conn.commit()
            return True

    async def get_routes_to_peer(self, destination_peer_id: str) -> List[MeshRoute]:
        """
        Get all routes to a specific peer.
        
        Args:
            destination_peer_id: Destination peer ID
            
        Returns:
            List of available routes
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT id, destination_peer_id, next_hop_peer_id, hop_count,
                       latency_ms, route_quality, last_updated
                FROM mesh_routes 
                WHERE destination_peer_id = ?
                ORDER BY route_quality DESC, hop_count ASC, latency_ms ASC
                """,
                (destination_peer_id,)
            ).fetchall()
            
            return [
                MeshRoute(
                    id=row[0],
                    destination_peer_id=row[1],
                    next_hop_peer_id=row[2],
                    hop_count=row[3],
                    latency_ms=row[4],
                    route_quality=row[5],
                    last_updated=datetime.fromtimestamp(row[6]) if row[6] else None
                )
                for row in rows
            ]

    # --------------------------------------------------------------------------
    # Gossip Message Operations
    # --------------------------------------------------------------------------

    async def store_gossip_message(
        self,
        message_type: str,
        payload: Dict[str, Any],
        source_peer_id: str,
        ttl: int,
        signature: str
    ) -> GossipMessage:
        """
        Store a gossip message.
        
        Args:
            message_type: Type of gossip message
            payload: Message payload
            source_peer_id: Source peer ID
            ttl: Time-to-live in hops
            signature: Message signature
            
        Returns:
            Stored gossip message
        """
        with self._db_lock:
            current_time = time.time()
            
            payload_json = payload if isinstance(payload, str) else json.dumps(payload)
            
            cursor = self._conn.execute(
                """
                INSERT INTO gossip_messages 
                (message_type, payload, source_peer_id, ttl, signature, received_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_type, payload_json, source_peer_id, ttl, signature, current_time)
            )
            message_id = cursor.lastrowid
            self._conn.commit()
            
            return GossipMessage(
                id=message_id,
                message_type=message_type,
                payload=payload,
                source_peer_id=source_peer_id,
                ttl=ttl,
                signature=signature,
                received_at=datetime.fromtimestamp(current_time)
            )

    async def get_unprocessed_gossip_messages(self, limit: int = 100) -> List[GossipMessage]:
        """
        Get unprocessed gossip messages.
        
        Args:
            limit: Maximum number of messages to retrieve
            
        Returns:
            List of unprocessed gossip messages
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT id, message_type, payload, source_peer_id, ttl, 
                       signature, received_at
                FROM gossip_messages 
                WHERE processed = 0
                ORDER BY received_at ASC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [
                GossipMessage(
                    id=row[0],
                    message_type=row[1],
                    payload=json.loads(row[2]),
                    source_peer_id=row[3],
                    ttl=row[4],
                    signature=row[5],
                    received_at=datetime.fromtimestamp(row[6]) if row[6] else None
                )
                for row in rows
            ]

    async def mark_gossip_processed(self, message_id: int) -> bool:
        """
        Mark a gossip message as processed.
        
        Args:
            message_id: Message ID
            
        Returns:
            True if update was successful, False otherwise
        """
        with self._db_lock:
            result = self._conn.execute(
                "UPDATE gossip_messages SET processed = 1 WHERE id = ?",
                (message_id,)
            )
            self._conn.commit()
            return result.rowcount > 0

    # --------------------------------------------------------------------------
    # Helper Methods
    # --------------------------------------------------------------------------

    def _row_to_peer(self, row: tuple) -> Peer:
        """Convert database row to Peer model."""
        capabilities = None
        if row[5]:  # capabilities JSON
            try:
                capabilities_dict = json.loads(row[5])
                capabilities = PeerCapabilities(**capabilities_dict)
            except (json.JSONDecodeError, TypeError):
                pass
        
        return Peer(
            id=row[0],
            peer_id=row[1],
            public_key=row[2],
            ip_address=row[3],
            port=row[4],
            capabilities=capabilities,
            reputation_score=row[6],
            status=row[7],
            last_seen=datetime.fromtimestamp(row[8]) if row[8] else None,
            created_at=datetime.fromtimestamp(row[9]) if row[9] else None
        )

    def _matches_capability_filters(self, peer: Peer, filters: PeerFilters) -> bool:
        """Check if peer matches capability filters."""
        if not peer.capabilities:
            return False
        
        if filters.has_compute is not None and peer.capabilities.compute != filters.has_compute:
            return False
        
        if filters.has_storage is not None and peer.capabilities.storage != filters.has_storage:
            return False
        
        if filters.min_bandwidth is not None and peer.capabilities.bandwidth_kbps < filters.min_bandwidth:
            return False
        
        return True