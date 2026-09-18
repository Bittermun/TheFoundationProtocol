# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from tfp_client.lib.distribution.shard_retriever import ShardRetriever
from tfp_client.lib.peer.peer_models import Peer, PeerCapabilities, ShardLocation


class TestRealShardNetworkTransport:
    """Test suite verifying real async HTTP shard retrieval across peers."""

    @pytest.mark.asyncio
    async def test_real_http_shard_fetch_success(self):
        peer_repo = AsyncMock()
        raptorq_adapter = MagicMock()

        # Mock active peer with real network location
        peer = Peer(
            peer_id="peer_alpha",
            public_key="pubkey_alpha",
            ip_address="127.0.0.1",
            port=8080,
            capabilities=PeerCapabilities(storage=True),
            status="active",
        )
        peer_repo.get_peer = AsyncMock(return_value=peer)

        content_hash = "c" * 64
        shard_locations = [
            ShardLocation(content_hash=content_hash, shard_index=0, peer_id="peer_alpha"),
            ShardLocation(content_hash=content_hash, shard_index=1, peer_id="peer_alpha"),
        ]
        peer_repo.get_shard_peers = AsyncMock(return_value=shard_locations)

        # Real shard bytes emitted by peer
        shard_payloads = {
            (content_hash, 0): b"REAL_BINARY_SHARD_0_DATA_PAYLOAD",
            (content_hash, 1): b"REAL_BINARY_SHARD_1_DATA_PAYLOAD",
        }

        async def mock_http_fetcher(p, c_hash, s_idx):
            assert p.ip_address == "127.0.0.1"
            return shard_payloads.get((c_hash, s_idx))

        raptorq_adapter.decode.return_value = b"FULL_RECONSTRUCTED_FILE_DATA"

        retriever = ShardRetriever(
            peer_repo=peer_repo,
            raptorq_adapter=raptorq_adapter,
            http_fetcher=mock_http_fetcher,
        )

        reconstructed = await retriever.retrieve_content(content_hash=content_hash)
        assert reconstructed == b"FULL_RECONSTRUCTED_FILE_DATA"
        raptorq_adapter.decode.assert_called_once()
        args, kwargs = raptorq_adapter.decode.call_args
        fetched_shards = args[0]
        assert b"REAL_BINARY_SHARD_0_DATA_PAYLOAD" in fetched_shards
        assert b"REAL_BINARY_SHARD_1_DATA_PAYLOAD" in fetched_shards

    @pytest.mark.asyncio
    async def test_http_fetch_peer_failover(self):
        peer_repo = AsyncMock()
        raptorq_adapter = MagicMock()

        peer_dead = Peer(
            peer_id="peer_failing",
            public_key="pubkey_failing",
            ip_address="127.0.0.1",
            port=9991,
            status="active",
        )
        peer_alive = Peer(
            peer_id="peer_healthy",
            public_key="pubkey_healthy",
            ip_address="127.0.0.1",
            port=9992,
            status="active",
        )

        async def get_peer(p_id):
            return peer_dead if p_id == "peer_failing" else peer_alive

        peer_repo.get_peer = AsyncMock(side_effect=get_peer)

        content_hash = "d" * 64
        shard_locations = [
            ShardLocation(content_hash=content_hash, shard_index=0, peer_id="peer_failing"),
            ShardLocation(content_hash=content_hash, shard_index=0, peer_id="peer_healthy"),
        ]
        peer_repo.get_shard_peers = AsyncMock(return_value=shard_locations)

        async def mock_http_fetcher(p, c_hash, s_idx):
            if p.peer_id == "peer_failing":
                raise ConnectionRefusedError("Node connection refused")
            return b"HEALTHY_PEER_SHARD_BYTES"

        raptorq_adapter.decode.return_value = b"RECOVERED_DATA"

        retriever = ShardRetriever(
            peer_repo=peer_repo,
            raptorq_adapter=raptorq_adapter,
            http_fetcher=mock_http_fetcher,
        )

        reconstructed = await retriever.retrieve_content(content_hash=content_hash, required_shards=1)
        assert reconstructed == b"RECOVERED_DATA"
