# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Peer schema initialization for P2P mesh networking.

This module provides database schema initialization for peer registry,
connections, and related P2P networking tables.
"""

import sqlite3
import threading
import logging
from typing import Optional

log = logging.getLogger(__name__)


class PeerSchema:
    """
    Database schema manager for peer-related tables.
    
    Handles creation and management of:
    - peer_registry: Peer information and capabilities
    - peer_connections: Peer connection tracking
    - content_shards: Content shard metadata
    - content_shard_locations: Shard location tracking
    - mesh_routes: Mesh routing table
    - gossip_messages: Gossip protocol messages
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize all peer-related database tables."""
        with self._db_lock:
            # Enable foreign key enforcement
            self._conn.execute("PRAGMA foreign_keys = ON")
            
            # Create peer_registry table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS peer_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    peer_id TEXT NOT NULL UNIQUE,
                    public_key TEXT NOT NULL,
                    ip_address TEXT,
                    port INTEGER,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    capabilities TEXT,
                    reputation_score INTEGER DEFAULT 100,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            # Create peer_connections table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS peer_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    local_peer_id TEXT NOT NULL,
                    remote_peer_id TEXT NOT NULL,
                    connection_type TEXT NOT NULL,
                    latency_ms INTEGER,
                    bandwidth_kbps INTEGER,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (local_peer_id) REFERENCES peer_registry(peer_id),
                    FOREIGN KEY (remote_peer_id) REFERENCES peer_registry(peer_id)
                )
                """
            )
            
            # Create content_shards table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_shards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL,
                    shard_index INTEGER NOT NULL,
                    shard_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    parity_shard BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (content_hash) REFERENCES content(root_hash)
                )
                """
            )
            
            # Create content_shard_locations table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_shard_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL,
                    shard_index INTEGER NOT NULL,
                    peer_id TEXT NOT NULL,
                    availability_score REAL DEFAULT 1.0,
                    last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (content_hash) REFERENCES content(root_hash),
                    FOREIGN KEY (peer_id) REFERENCES peer_registry(peer_id)
                )
                """
            )
            
            # Create mesh_routes table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mesh_routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    destination_peer_id TEXT NOT NULL,
                    next_hop_peer_id TEXT NOT NULL,
                    hop_count INTEGER DEFAULT 1,
                    latency_ms INTEGER,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    route_quality REAL DEFAULT 1.0,
                    FOREIGN KEY (destination_peer_id) REFERENCES peer_registry(peer_id),
                    FOREIGN KEY (next_hop_peer_id) REFERENCES peer_registry(peer_id)
                )
                """
            )
            
            # Create gossip_messages table
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gossip_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    source_peer_id TEXT NOT NULL,
                    ttl INTEGER DEFAULT 10,
                    signature TEXT NOT NULL,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed BOOLEAN DEFAULT 0,
                    FOREIGN KEY (source_peer_id) REFERENCES peer_registry(peer_id)
                )
                """
            )
            
            # Create indexes for performance
            self._create_indexes()
            
            self._conn.commit()
            log.info("Peer schema initialized successfully")

    def _create_indexes(self) -> None:
        """Create indexes for performance optimization."""
        # Peer registry indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_peer_status ON peer_registry(status)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_peer_last_seen ON peer_registry(last_seen)"
        )
        
        # Peer connections indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_connections_local ON peer_connections(local_peer_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_connections_remote ON peer_connections(remote_peer_id)"
        )
        
        # Content shards indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shard_content ON content_shards(content_hash)"
        )
        
        # Content shard locations indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shard_locations_content ON content_shard_locations(content_hash)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shard_locations_peer ON content_shard_locations(peer_id)"
        )
        
        # Mesh routes indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routes_destination ON mesh_routes(destination_peer_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routes_next_hop ON mesh_routes(next_hop_peer_id)"
        )
        
        # Gossip messages indexes
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gossip_processed ON gossip_messages(processed)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gossip_source ON gossip_messages(source_peer_id)"
        )
        
        self._conn.commit()
        log.info("Peer schema indexes created successfully")

    def add_content_sharding_columns(self) -> None:
        """
        Add sharding columns to existing content table.
        
        This method adds columns needed for content sharding:
        - shard_count: Number of shards the content is divided into
        - redundancy_factor: Redundancy multiplier for availability
        - distribution_status: Current distribution status
        """
        with self._db_lock:
            # Check if content table exists first
            content_table_exists = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content'"
            ).fetchone()
            
            if not content_table_exists:
                # Content table doesn't exist yet, skip this operation
                # It will be created by ContentStore later
                log.debug("Content table does not exist yet, skipping sharding column addition")
                return
            
            # Check if columns already exist (PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk))
            existing_cols = set()
            for row in self._conn.execute("PRAGMA table_info(content)").fetchall():
                if isinstance(row, dict):
                    col = row.get("name", row.get(1))
                elif hasattr(row, "__getitem__"):
                    try:
                        col = row["name"]
                    except (KeyError, IndexError, TypeError):
                        col = row[1]
                else:
                    col = getattr(row, "name", row[1])
                if col:
                    existing_cols.add(col)
            
            columns_to_add = [
                ("shard_count", "INTEGER DEFAULT 1"),
                ("redundancy_factor", "INTEGER DEFAULT 3"),
                ("distribution_status", "TEXT DEFAULT 'pending'")
            ]
            
            for col_name, col_def in columns_to_add:
                if col_name not in existing_cols:
                    self._conn.execute(
                        f"ALTER TABLE content ADD COLUMN {col_name} {col_def}"
                    )
                    log.info(f"Added column {col_name} to content table")
            
            self._conn.commit()
            log.info("Content sharding columns added successfully")