"""Regression coverage for runtime defects exposed by source type checking."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from tfp_client.lib.gossip.gossip_protocol import GossipProtocol
from tfp_client.lib.peer.peer_models import GossipMessage
from tfp_client.lib.upload.chunk_uploader import ChunkUploader


@pytest.mark.asyncio
async def test_pending_gossip_accepts_repository_model():
    stored = GossipMessage(message_type="content_announce", payload={"hash": "example"}, source_peer_id="peer", signature="signature", ttl=3)
    repository = Mock()
    repository.get_unprocessed_gossip_messages = AsyncMock(return_value=[stored])
    protocol = GossipProtocol(repository)
    messages = await protocol.get_pending_messages(limit=2)
    assert len(messages) == 1
    assert messages[0].payload == stored.payload
    assert messages[0].ttl == 3
    assert messages[0].signature == "signature"
    repository.get_unprocessed_gossip_messages.assert_awaited_once_with(2)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["upload_chunks", "upload_with_progress"])
async def test_cancelled_chunk_cannot_be_returned_as_success(monkeypatch, method):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.side_effect = asyncio.CancelledError
    monkeypatch.setattr(httpx, "AsyncClient", Mock(return_value=client))
    with pytest.raises(asyncio.CancelledError):
        await getattr(ChunkUploader(), method)([b"chunk"], "https://example.invalid")
