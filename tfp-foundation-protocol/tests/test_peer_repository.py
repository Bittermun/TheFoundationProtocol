# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit tests for peer repository.

Tests the PeerRepository class with various database operations
for peer registry, connections, shards, routes, and gossip messages.
"""

import sqlite3
import threading
import time
import pytest
from datetime import datetime

from tfp_client.lib.peer.peer_repository import PeerRepository
from tfp_client.lib.peer.peer_models import (
    PeerInfo,
    Peer,
    PeerConnection,
    PeerFilters,
    ConnectionMetrics,
    ContentShard,
    ShardLocation,
    MeshRoute,
    GossipMessage,
    PeerCapabilities,
)


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def peer_repo(in_memory_db):
    """Create a PeerRepository instance with test database."""
    db_lock = threading.RLock()
    
    # Initialize peer schema first
    from tfp_demo.peer_schema import PeerSchema
    peer_schema = PeerSchema(in_memory_db, db_lock)
    
    # Create basic content table for shard tests
    in_memory_db.execute(
        """
        CREATE TABLE IF NOT EXISTS content (
            root_hash TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            tags TEXT NOT NULL,
            blob_path TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    in_memory_db.commit()
    
    return PeerRepository(in_memory_db, db_lock)


class TestPeerRepository:
    """Test suite for PeerRepository basic operations."""

    async def test_register_new_peer(self, peer_repo):
        """Test registering a new peer."""
        peer_info = PeerInfo(
            peer_id="test-peer-1",
            public_key="test-public-key-1",
            ip_address="192.168.1.1",
            port=8000,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        
        registered_peer = await peer_repo.register_peer(peer_info)
        
        assert registered_peer.peer_id == "test-peer-1"
        assert registered_peer.public_key == "test-public-key-1"
        assert registered_peer.ip_address == "192.168.1.1"
        assert registered_peer.port == 8000
        assert registered_peer.reputation_score == 100
        assert registered_peer.status == "active"
        assert registered_peer.id is not None

    async def test_register_existing_peer(self, peer_repo):
        """Test updating an existing peer."""
        # Register initial peer
        peer_info = PeerInfo(
            peer_id="test-peer-2",
            public_key="test-public-key-2",
            ip_address="192.168.1.2",
            port=8001,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=500),
            reputation_score=50,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        # Update peer
        updated_info = PeerInfo(
            peer_id="test-peer-2",
            public_key="test-public-key-2-updated",
            ip_address="192.168.1.3",
            port=8002,
            capabilities=PeerCapabilities(compute=True, storage=False, bandwidth_kbps=2000),
            reputation_score=75,
            status="active"
        )
        updated_peer = await peer_repo.register_peer(updated_info)
        
        assert updated_peer.peer_id == "test-peer-2"
        assert updated_peer.public_key == "test-public-key-2-updated"
        assert updated_peer.ip_address == "192.168.1.3"
        assert updated_peer.port == 8002
        assert updated_peer.reputation_score == 75
        assert updated_peer.capabilities.storage is False
        assert updated_peer.capabilities.bandwidth_kbps == 2000

    async def test_get_peer(self, peer_repo):
        """Test retrieving a peer by ID."""
        peer_info = PeerInfo(
            peer_id="test-peer-3",
            public_key="test-public-key-3",
            ip_address="192.168.1.4",
            port=8003,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1500),
            reputation_score=85,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        retrieved_peer = await peer_repo.get_peer("test-peer-3")
        
        assert retrieved_peer is not None
        assert retrieved_peer.peer_id == "test-peer-3"
        assert retrieved_peer.public_key == "test-public-key-3"
        assert retrieved_peer.reputation_score == 85

    async def test_get_nonexistent_peer(self, peer_repo):
        """Test retrieving a non-existent peer."""
        retrieved_peer = await peer_repo.get_peer("nonexistent-peer")
        assert retrieved_peer is None

    async def test_list_peers_no_filters(self, peer_repo):
        """Test listing peers without filters."""
        # Register multiple peers
        for i in range(5):
            peer_info = PeerInfo(
                peer_id=f"test-peer-{i}",
                public_key=f"test-public-key-{i}",
                ip_address=f"192.168.1.{i}",
                port=8000 + i,
                capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000 + i * 100),
                reputation_score=50 + i * 10,
                status="active"
            )
            await peer_repo.register_peer(peer_info)
        
        filters = PeerFilters(status="active", min_reputation=0, limit=10)
        peers = await peer_repo.list_peers(filters)
        
        assert len(peers) == 5
        # Should be sorted by reputation descending
        assert peers[0].reputation_score >= peers[1].reputation_score

    async def test_list_peers_with_reputation_filter(self, peer_repo):
        """Test listing peers with reputation filter."""
        # Register peers with different reputation scores
        for i in range(5):
            peer_info = PeerInfo(
                peer_id=f"test-peer-rep-{i}",
                public_key=f"test-public-key-rep-{i}",
                ip_address=f"192.168.2.{i}",
                port=8010 + i,
                capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
                reputation_score=30 + i * 15,  # 30, 45, 60, 75, 90
                status="active"
            )
            await peer_repo.register_peer(peer_info)
        
        filters = PeerFilters(status="active", min_reputation=60, limit=10)
        peers = await peer_repo.list_peers(filters)
        
        assert len(peers) == 3  # Only peers with reputation >= 60
        for peer in peers:
            assert peer.reputation_score >= 60

    async def test_list_peers_with_capability_filter(self, peer_repo):
        """Test listing peers with capability filter."""
        # Register peers with different capabilities
        peer_info_compute = PeerInfo(
            peer_id="compute-peer",
            public_key="compute-key",
            ip_address="192.168.3.1",
            port=8020,
            capabilities=PeerCapabilities(compute=True, storage=False, bandwidth_kbps=1000),
            reputation_score=80,
            status="active"
        )
        peer_info_storage = PeerInfo(
            peer_id="storage-peer",
            public_key="storage-key",
            ip_address="192.168.3.2",
            port=8021,
            capabilities=PeerCapabilities(compute=False, storage=True, bandwidth_kbps=500),
            reputation_score=80,
            status="active"
        )
        await peer_repo.register_peer(peer_info_compute)
        await peer_repo.register_peer(peer_info_storage)
        
        filters = PeerFilters(status="active", has_compute=True, limit=10)
        peers = await peer_repo.list_peers(filters)
        
        assert len(peers) == 1
        assert peers[0].peer_id == "compute-peer"
        assert peers[0].capabilities.compute is True

    async def test_update_peer_status(self, peer_repo):
        """Test updating peer status."""
        peer_info = PeerInfo(
            peer_id="test-peer-status",
            public_key="test-public-key-status",
            ip_address="192.168.4.1",
            port=8030,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        success = await peer_repo.update_peer_status("test-peer-status", "inactive")
        assert success is True
        
        updated_peer = await peer_repo.get_peer("test-peer-status")
        assert updated_peer.status == "inactive"

    async def test_update_peer_last_seen(self, peer_repo):
        """Test updating peer last seen timestamp."""
        peer_info = PeerInfo(
            peer_id="test-peer-lastseen",
            public_key="test-public-key-lastseen",
            ip_address="192.168.5.1",
            port=8040,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        # Get initial last_seen
        initial_peer = await peer_repo.get_peer("test-peer-lastseen")
        initial_last_seen = initial_peer.last_seen
        
        # Wait a bit and update
        time.sleep(0.1)
        success = await peer_repo.update_peer_last_seen("test-peer-lastseen")
        assert success is True
        
        updated_peer = await peer_repo.get_peer("test-peer-lastseen")
        assert updated_peer.last_seen > initial_last_seen

    async def test_delete_peer(self, peer_repo):
        """Test deleting a peer."""
        peer_info = PeerInfo(
            peer_id="test-peer-delete",
            public_key="test-public-key-delete",
            ip_address="192.168.6.1",
            port=8050,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        # Verify peer exists
        assert await peer_repo.get_peer("test-peer-delete") is not None
        
        # Delete peer
        success = await peer_repo.delete_peer("test-peer-delete")
        assert success is True
        
        # Verify peer is deleted
        assert await peer_repo.get_peer("test-peer-delete") is None

    async def test_record_connection(self, peer_repo):
        """Test recording a peer connection."""
        # First register both peers
        peer_info_1 = PeerInfo(
            peer_id="local-peer",
            public_key="local-key",
            ip_address="192.168.7.1",
            port=8060,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        peer_info_2 = PeerInfo(
            peer_id="remote-peer",
            public_key="remote-key",
            ip_address="192.168.7.2",
            port=8061,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info_1)
        await peer_repo.register_peer(peer_info_2)
        
        # Record connection
        metrics = ConnectionMetrics(latency_ms=50, bandwidth_kbps=1000)
        success = await peer_repo.record_connection(
            "local-peer",
            "remote-peer",
            "direct",
            metrics
        )
        assert success is True
        
        # Verify connection was recorded
        connections = await peer_repo.get_peer_connections("local-peer")
        assert len(connections) == 1
        assert connections[0].local_peer_id == "local-peer"
        assert connections[0].remote_peer_id == "remote-peer"
        assert connections[0].connection_type == "direct"
        assert connections[0].metrics.latency_ms == 50

    async def test_register_shard(self, peer_repo):
        """Test registering a content shard."""
        # First create content table entry (simplified for test)
        peer_repo._conn.execute(
            "INSERT INTO content (root_hash, title, tags, blob_path, size_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test-content-hash", "Test Content", "test", "/test/path", 1024)
        )
        peer_repo._conn.commit()
        
        shard = await peer_repo.register_shard(
            content_hash="test-content-hash",
            shard_index=0,
            shard_hash="test-shard-hash",
            size_bytes=512,
            parity_shard=False
        )
        
        assert shard.content_hash == "test-content-hash"
        assert shard.shard_index == 0
        assert shard.shard_hash == "test-shard-hash"
        assert shard.size_bytes == 512
        assert shard.parity_shard is False
        assert shard.id is not None

    async def test_register_shard_location(self, peer_repo):
        """Test registering a shard location."""
        # Register peer and content first
        peer_info = PeerInfo(
            peer_id="shard-host-peer",
            public_key="shard-host-key",
            ip_address="192.168.8.1",
            port=8070,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        peer_repo._conn.execute(
            "INSERT INTO content (root_hash, title, tags, blob_path, size_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            ("shard-content-hash", "Shard Content", "shard", "/shard/path", 2048)
        )
        peer_repo._conn.commit()
        
        success = await peer_repo.register_shard_location(
            content_hash="shard-content-hash",
            shard_index=0,
            peer_id="shard-host-peer",
            availability_score=0.9
        )
        assert success is True

    async def test_get_shard_peers(self, peer_repo):
        """Test getting peers hosting specific shards."""
        # Register peer and content
        peer_info = PeerInfo(
            peer_id="shard-retrieval-peer",
            public_key="shard-retrieval-key",
            ip_address="192.168.9.1",
            port=8080,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        peer_repo._conn.execute(
            "INSERT INTO content (root_hash, title, tags, blob_path, size_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            ("retrieval-content-hash", "Retrieval Content", "retrieval", "/retrieval/path", 4096)
        )
        peer_repo._conn.commit()
        
        # Register shard location
        await peer_repo.register_shard_location(
            content_hash="retrieval-content-hash",
            shard_index=0,
            peer_id="shard-retrieval-peer",
            availability_score=0.8
        )
        
        # Get shard peers
        shard_peers = await peer_repo.get_shard_peers("retrieval-content-hash")
        
        assert len(shard_peers) == 1
        assert shard_peers[0].peer_id == "shard-retrieval-peer"
        assert shard_peers[0].content_hash == "retrieval-content-hash"
        assert shard_peers[0].availability_score == 0.8

    async def test_upsert_route(self, peer_repo):
        """Test inserting/updating a mesh route."""
        # Register peers
        peer_info_1 = PeerInfo(
            peer_id="route-destination",
            public_key="route-dest-key",
            ip_address="192.168.10.1",
            port=8090,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        peer_info_2 = PeerInfo(
            peer_id="route-next-hop",
            public_key="route-next-key",
            ip_address="192.168.10.2",
            port=8091,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info_1)
        await peer_repo.register_peer(peer_info_2)
        
        # Insert route
        success = await peer_repo.upsert_route(
            destination_peer_id="route-destination",
            next_hop_peer_id="route-next-hop",
            hop_count=2,
            latency_ms=100,
            route_quality=0.9
        )
        assert success is True
        
        # Update route
        success = await peer_repo.upsert_route(
            destination_peer_id="route-destination",
            next_hop_peer_id="route-next-hop",
            hop_count=2,
            latency_ms=80,  # Updated latency
            route_quality=0.95  # Updated quality
        )
        assert success is True

    async def test_get_routes_to_peer(self, peer_repo):
        """Test getting routes to a specific peer."""
        # Register peers
        peer_info_1 = PeerInfo(
            peer_id="route-target",
            public_key="route-target-key",
            ip_address="192.168.11.1",
            port=8100,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        peer_info_2 = PeerInfo(
            peer_id="route-path-1",
            public_key="route-path-1-key",
            ip_address="192.168.11.2",
            port=8101,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info_1)
        await peer_repo.register_peer(peer_info_2)
        
        # Insert route
        await peer_repo.upsert_route(
            destination_peer_id="route-target",
            next_hop_peer_id="route-path-1",
            hop_count=1,
            latency_ms=50,
            route_quality=1.0
        )
        
        # Get routes
        routes = await peer_repo.get_routes_to_peer("route-target")
        
        assert len(routes) == 1
        assert routes[0].destination_peer_id == "route-target"
        assert routes[0].next_hop_peer_id == "route-path-1"
        assert routes[0].hop_count == 1
        assert routes[0].latency_ms == 50
        assert routes[0].route_quality == 1.0

    async def test_store_gossip_message(self, peer_repo):
        """Test storing a gossip message."""
        # Register source peer
        peer_info = PeerInfo(
            peer_id="gossip-source-peer",
            public_key="gossip-source-key",
            ip_address="192.168.12.1",
            port=8110,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        # Store gossip message
        message = await peer_repo.store_gossip_message(
            message_type="peer_announce",
            payload={"peer_id": "gossip-source-peer", "capabilities": {"compute": True}},
            source_peer_id="gossip-source-peer",
            ttl=10,
            signature="test-signature"
        )
        
        assert message.message_type == "peer_announce"
        assert message.source_peer_id == "gossip-source-peer"
        assert message.ttl == 10
        assert message.signature == "test-signature"
        assert message.processed is False
        assert message.id is not None

    async def test_get_unprocessed_gossip_messages(self, peer_repo):
        """Test getting unprocessed gossip messages."""
        # Register peer
        peer_info = PeerInfo(
            peer_id="gossip-test-peer",
            public_key="gossip-test-key",
            ip_address="192.168.13.1",
            port=8120,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        # Store multiple messages
        for i in range(3):
            await peer_repo.store_gossip_message(
                message_type="test_message",
                payload={"index": i},
                source_peer_id="gossip-test-peer",
                ttl=10,
                signature=f"signature-{i}"
            )
        
        # Get unprocessed messages
        messages = await peer_repo.get_unprocessed_gossip_messages(limit=10)
        
        assert len(messages) == 3
        for msg in messages:
            assert msg.processed is False

    async def test_mark_gossip_processed(self, peer_repo):
        """Test marking gossip message as processed."""
        # Register peer and store message
        peer_info = PeerInfo(
            peer_id="gossip-process-peer",
            public_key="gossip-process-key",
            ip_address="192.168.14.1",
            port=8130,
            capabilities=PeerCapabilities(compute=True, storage=True, bandwidth_kbps=1000),
            reputation_score=100,
            status="active"
        )
        await peer_repo.register_peer(peer_info)
        
        message = await peer_repo.store_gossip_message(
            message_type="process_test",
            payload={"test": True},
            source_peer_id="gossip-process-peer",
            ttl=10,
            signature="process-signature"
        )
        
        # Mark as processed
        success = await peer_repo.mark_gossip_processed(message.id)
        assert success is True
        
        # Verify it's marked
        updated_messages = await peer_repo.get_unprocessed_gossip_messages(limit=10)
        assert message.id not in [msg.id for msg in updated_messages]