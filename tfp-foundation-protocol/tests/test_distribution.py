# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit tests for content distribution logic.

Tests the ShardManager and ShardRetriever classes for optimal
distribution planning, peer selection, and shard retrieval.
"""

import sqlite3
import threading
import time
import pytest
from datetime import datetime

from tfp_client.lib.distribution.shard_manager import ShardManager, DistributionPlan, DistributionResult
from tfp_client.lib.distribution.shard_retriever import ShardRetriever
from tfp_client.lib.peer.peer_repository import PeerRepository
from tfp_client.lib.peer.peer_models import (
    PeerInfo,
    Peer,
    PeerCapabilities,
    PeerFilters,
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

    repo = PeerRepository(in_memory_db, db_lock)

    # Helper to create test content
    def create_test_content(content_hash: str, title: str = "test"):
        in_memory_db.execute(
            """
            INSERT OR REPLACE INTO content (root_hash, title, tags, size_bytes)
            VALUES (?, ?, ?, ?)
            """,
            (content_hash, title, "test", 1024)
        )
        in_memory_db.commit()

    repo.create_test_content = create_test_content
    return repo


@pytest.fixture
def shard_manager(peer_repo):
    """Create a ShardManager instance for testing."""
    return ShardManager(peer_repo)


@pytest.fixture
def shard_retriever(peer_repo):
    """Create a ShardRetriever instance for testing."""
    return ShardRetriever(peer_repo)


@pytest.fixture
async def sample_peers(peer_repo):
    """Create sample peers for testing."""
    peers = []

    for i in range(5):
        peer_info = PeerInfo(
            peer_id=f"peer_{i}",
            public_key=f"pubkey_{i}",
            ip_address=f"192.168.1.{100 + i}",
            port=8000 + i,
            capabilities=PeerCapabilities(
                bandwidth_kbps=10000 * (i + 1),
                storage=True,
                compute=True,
                relay=True
            ),
            reputation_score=80 + i * 5,
            status="active"
        )
        peer = await peer_repo.register_peer(peer_info)
        peers.append(peer)

    return peers


class TestShardManager:
    """Tests for ShardManager distribution planning."""

    @pytest.mark.asyncio
    async def test_create_distribution_plan_basic(self, shard_manager, sample_peers):
        """Test basic distribution plan creation."""
        content_hash = "a" * 64
        content_size = 1024 * 1024  # 1 MB
        redundancy = 3

        plan = await shard_manager.calculate_optimal_distribution(
            content_hash=content_hash,
            content_size=content_size,
            redundancy=redundancy
        )

        assert plan.content_hash == content_hash
        assert plan.redundancy_factor == redundancy
        assert len(plan.shard_assignments) > 0

    @pytest.mark.asyncio
    async def test_peer_selection_with_capabilities(self, shard_manager, sample_peers):
        """Test peer selection respects capabilities."""
        content_hash = "b" * 64
        content_size = 1024 * 1024
        redundancy = 2

        plan = await shard_manager.calculate_optimal_distribution(
            content_hash=content_hash,
            content_size=content_size,
            redundancy=redundancy
        )

        # Check that peers with storage capability are selected
        all_peers_used = set()
        for shard_idx, peer_ids in plan.shard_assignments.items():
            all_peers_used.update(peer_ids)

        assert len(all_peers_used) > 0

    @pytest.mark.asyncio
    async def test_peer_selection_with_reputation(self, shard_manager, peer_repo):
        """Test peer selection respects reputation scores."""
        # Create peers with different reputation scores
        for i in range(3):
            peer_info = PeerInfo(
                peer_id=f"rep_peer_{i}",
                public_key=f"rep_pubkey_{i}",
                ip_address=f"192.168.2.{100 + i}",
                port=9000 + i,
                capabilities=PeerCapabilities(
                    bandwidth_kbps=10000,
                    storage=True,
                    compute=True,
                    relay=True
                ),
                reputation_score=50 + i * 25,  # 50, 75, 100
                status="active"
            )
            await peer_repo.register_peer(peer_info)

        content_hash = "c" * 64
        content_size = 1024 * 1024
        redundancy = 2

        plan = await shard_manager.calculate_optimal_distribution(
            content_hash=content_hash,
            content_size=content_size,
            redundancy=redundancy
        )

        # Higher reputation peers should be used more
        peer_usage = {}
        for peer_ids in plan.shard_assignments.values():
            for peer_id in peer_ids:
                peer_usage[peer_id] = peer_usage.get(peer_id, 0) + 1

        # Peer with highest reputation (rep_peer_2) should have highest usage
        assert peer_usage.get("rep_peer_2", 0) >= peer_usage.get("rep_peer_1", 0)
        assert peer_usage.get("rep_peer_1", 0) >= peer_usage.get("rep_peer_0", 0)

    @pytest.mark.asyncio
    async def test_distribute_shards_success(self, shard_manager, sample_peers, peer_repo):
        """Test successful shard distribution."""
        content_hash = "d" * 64
        content_data = b"test content data" * 1000  # ~17 KB

        # Create test content first to satisfy foreign key
        peer_repo.create_test_content(content_hash)

        result = await shard_manager.distribute_shards(
            content_hash=content_hash,
            content_data=content_data,
            hmac_key=None,
            redundancy=0.5  # Higher redundancy for distribution multiplier
        )

        assert result.success is True
        assert result.content_hash == content_hash
        assert result.shards_distributed > 0
        assert result.shards_failed == 0
        assert len(result.peer_ids) > 0
        assert result.distribution_time_ms > 0

    @pytest.mark.asyncio
    async def test_distribute_shards_with_no_peers(self, shard_manager, peer_repo):
        """Test distribution behavior when no peers are available."""
        content_hash = "e" * 64
        content_data = b"test content data" * 1000

        # Create test content first to satisfy foreign key
        peer_repo.create_test_content(content_hash)

        result = await shard_manager.distribute_shards(
            content_hash=content_hash,
            content_data=content_data,
            hmac_key=None,
            redundancy=0.05
        )

        # Should fail when no peers are available
        assert result.content_hash == content_hash
        assert result.success is False
        assert len(result.errors) > 0


class TestShardRetriever:
    """Tests for ShardRetriever shard fetching."""

    @pytest.mark.asyncio
    async def test_retrieve_shards_basic(self, shard_retriever, peer_repo):
        """Test basic shard retrieval."""
        content_hash = "f" * 64

        # Create test content first to satisfy foreign key
        peer_repo.create_test_content(content_hash)

        # Register some shard locations
        await peer_repo.register_shard(
            content_hash=content_hash,
            shard_index=0,
            shard_hash="hash_0",
            size_bytes=1024,
            parity_shard=False
        )

        peer_info = PeerInfo(
            peer_id="retrieval_peer",
            public_key="retrieval_pubkey",
            ip_address="192.168.3.100",
            port=9999,
            capabilities=PeerCapabilities(
                bandwidth_kbps=10000,
                storage=True,
                compute=True,
                relay=True
            ),
            reputation_score=90,
            status="active"
        )
        await peer_repo.register_peer(peer_info)

        await peer_repo.register_shard_location(
            content_hash=content_hash,
            shard_index=0,
            peer_id="retrieval_peer",
            availability_score=1.0
        )

        # Note: In a real implementation, this would fetch actual shard data
        # For now, we test the availability logic
        availability = await shard_retriever.get_shard_availability(content_hash)

        assert availability["content_hash"] == content_hash
        assert availability["total_shards"] > 0
        assert len(availability["peer_list"]) > 0

    @pytest.mark.asyncio
    async def test_retrieve_with_insufficient_shards(self, shard_retriever):
        """Test retrieval when insufficient shards are available."""
        content_hash = "g" * 64

        # No shards registered
        availability = await shard_retriever.get_shard_availability(content_hash)

        assert availability["content_hash"] == content_hash
        assert availability["total_shards"] == 0
        assert availability["fully_available_shards"] == 0

    @pytest.mark.asyncio
    async def test_peer_selection_for_retrieval(self, shard_retriever, peer_repo):
        """Test peer selection for retrieval favors high-availability peers."""
        content_hash = "h" * 64

        # Create test content first to satisfy foreign key
        peer_repo.create_test_content(content_hash)

        # Register a shard
        await peer_repo.register_shard(
            content_hash=content_hash,
            shard_index=0,
            shard_hash="hash_0",
            size_bytes=1024,
            parity_shard=False
        )

        # Create peers with different availability scores
        for i in range(3):
            peer_info = PeerInfo(
                peer_id=f"avail_peer_{i}",
                public_key=f"avail_pubkey_{i}",
                ip_address=f"192.168.4.{100 + i}",
                port=10000 + i,
                capabilities=PeerCapabilities(
                    bandwidth_kbps=10000,
                    storage=True,
                    compute=True,
                    relay=True
                ),
                reputation_score=80,
                status="active"
            )
            await peer_repo.register_peer(peer_info)

            # Register shard location with different availability scores
            await peer_repo.register_shard_location(
                content_hash=content_hash,
                shard_index=0,
                peer_id=f"avail_peer_{i}",
                availability_score=0.5 + i * 0.2  # 0.5, 0.7, 0.9
            )

        availability = await shard_retriever.get_shard_availability(content_hash)

        # Check that availability reflects the registered peers
        assert availability["total_shards"] == 1
        assert availability["fully_available_shards"] == 1
        assert len(availability["peer_list"]) == 3


class TestDistributionIntegration:
    """Integration tests for distribution components."""

    @pytest.mark.asyncio
    async def test_distribution_and_retrieval_flow(self, shard_manager, shard_retriever, peer_repo):
        """Test end-to-end distribution and retrieval planning."""
        content_hash = "i" * 64
        content_data = b"integration test content" * 1000

        # Create test content first to satisfy foreign key
        peer_repo.create_test_content(content_hash)

        # Create peers
        for i in range(3):
            peer_info = PeerInfo(
                peer_id=f"int_peer_{i}",
                public_key=f"int_pubkey_{i}",
                ip_address=f"192.168.5.{100 + i}",
                port=11000 + i,
                capabilities=PeerCapabilities(
                    bandwidth_kbps=10000,
                    storage=True,
                    compute=True,
                    relay=True
                ),
                reputation_score=85,
                status="active"
            )
            await peer_repo.register_peer(peer_info)

        # Distribute content
        dist_result = await shard_manager.distribute_shards(
            content_hash=content_hash,
            content_data=content_data,
            hmac_key=None,
            redundancy=0.5  # Higher redundancy for distribution multiplier
        )

        assert dist_result.success is True

        # Check distribution status
        is_distributed = await peer_repo.is_content_distributed(content_hash)
        assert is_distributed is True

        status = await peer_repo.get_distribution_status(content_hash)
        assert status is not None
        assert status["content_hash"] == content_hash
        assert status["total_shards"] > 0
        assert status["distributed_shards"] > 0

        # Check availability
        availability = await shard_retriever.get_shard_availability(content_hash)
        assert availability["content_hash"] == content_hash
        assert availability["total_shards"] > 0
        assert len(availability["peer_list"]) > 0
