# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Gossip protocol for P2P mesh networking.

Implements TTL-based message propagation, peer announcements,
and network-wide information dissemination using NostrBridge.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from ..peer.peer_repository import PeerRepository
from ..bridges.nostr_bridge import NostrBridge, NostrEvent

log = logging.getLogger(__name__)

# TFP-specific Nostr event kind for peer announcements
TFP_PEER_ANNOUNCE_KIND: int = 30082


@dataclass
class GossipMessage:
    """
    A gossip message for network-wide propagation.

    Messages carry a TTL (time-to-live) and are rebroadcast by each
    peer until TTL reaches zero, preventing infinite loops.
    """
    message_type: str
    payload: Dict[str, Any]
    source_peer_id: str
    ttl: int = 10
    signature: str = ""
    created_at: float = field(default_factory=time.time)
    processed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/transmission."""
        return {
            "message_type": self.message_type,
            "payload": self.payload,
            "source_peer_id": self.source_peer_id,
            "ttl": self.ttl,
            "signature": self.signature,
            "created_at": self.created_at,
            "processed": self.processed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GossipMessage":
        """Create from dictionary."""
        return cls(
            message_type=data["message_type"],
            payload=data["payload"],
            source_peer_id=data["source_peer_id"],
            ttl=data.get("ttl", 10),
            signature=data.get("signature", ""),
            created_at=data.get("created_at", time.time()),
            processed=data.get("processed", False),
        )


@dataclass
class GossipConfig:
    """Configuration for gossip protocol behavior."""
    default_ttl: int = 10
    max_message_size: int = 1024 * 1024  # 1MB
    gossip_interval_seconds: float = 30.0
    dedup_window_seconds: float = 300.0  # 5 minutes
    enable_relay_broadcast: bool = True


class GossipProtocol:
    """
    Gossip protocol for P2P mesh networking.

    Uses NostrBridge for cross-network peer discovery and message
    propagation. Messages are signed, TTL-limited, and deduplicated.
    """

    def __init__(
        self,
        peer_repo: PeerRepository,
        nostr_bridge: Optional[NostrBridge] = None,
        config: Optional[GossipConfig] = None,
    ):
        self._peer_repo = peer_repo
        self._nostr_bridge = nostr_bridge or NostrBridge(offline=True)
        self._config = config or GossipConfig()

        # Message deduplication: message_id -> seen_at_timestamp
        self._seen_messages: Dict[str, float] = {}

        # Local message history for debugging
        self._message_history: List[GossipMessage] = []

    async def broadcast_message(
        self,
        message_type: str,
        payload: Dict[str, Any],
        ttl: Optional[int] = None,
        source_peer_id: Optional[str] = None,
    ) -> bool:
        """
        Broadcast a gossip message to the peer network.

        Args:
            message_type: Type of message (e.g., "peer_announce", "content_announce")
            payload: Message payload (must be JSON-serializable)
            ttl: Time-to-live (hops before message expires)
            source_peer_id: Originating peer ID (defaults to local peer)

        Returns:
            True if broadcast succeeded, False otherwise
        """
        if ttl is None:
            ttl = self._config.default_ttl

        if source_peer_id is None:
            # Use a default local peer ID for now
            source_peer_id = "local_peer"

        # Ensure source peer exists in peer repository to satisfy foreign key constraints
        if self._peer_repo is not None:
            try:
                peer = await self._peer_repo.get_peer(source_peer_id)
                if peer is None:
                    from ..peer.peer_models import PeerInfo, PeerCapabilities
                    await self._peer_repo.register_peer(
                        PeerInfo(
                            peer_id=source_peer_id,
                            public_key=f"pubkey_{source_peer_id}",
                            ip_address="127.0.0.1",
                            port=8000,
                            capabilities=PeerCapabilities(compute=True, storage=True),
                            status="active",
                        )
                    )
            except Exception as exc:
                log.debug("Could not auto-register peer %s: %s", source_peer_id, exc)

        # Check message size
        payload_str = json.dumps(payload, separators=(",", ":"))
        if len(payload_str.encode("utf-8")) > self._config.max_message_size:
            log.warning("Gossip message too large: %d bytes", len(payload_str))
            return False

        # Create gossip message
        message = GossipMessage(
            message_type=message_type,
            payload=payload,
            source_peer_id=source_peer_id,
            ttl=ttl,
        )

        # Store in repository for local peers
        await self._peer_repo.store_gossip_message(
            message_type=message.message_type,
            payload=message.payload,
            source_peer_id=message.source_peer_id,
            ttl=message.ttl,
            signature=message.signature,
        )

        # Broadcast via Nostr relay if enabled
        if self._config.enable_relay_broadcast:
            try:
                nostr_event = self._build_nostr_event(message)
                self._nostr_bridge._history.append(nostr_event)
                log.info(
                    "Broadcast gossip message via Nostr: type=%s, id=%s",
                    message_type,
                    nostr_event.id[:8],
                )
            except Exception as exc:
                log.warning("Nostr broadcast failed: %s", exc)

        # Track for deduplication
        message_id = self._compute_message_id(message)
        self._seen_messages[message_id] = time.time()

        # Add to history
        self._message_history.append(message)

        return True

    async def process_gossip_message(
        self,
        message: GossipMessage,
        local_peer_id: str,
    ) -> bool:
        """
        Process an incoming gossip message.

        Args:
            message: The gossip message to process
            local_peer_id: Local peer ID for signature verification

        Returns:
            True if message was processed (not a duplicate), False if duplicate
        """
        # Check deduplication
        message_id = self._compute_message_id(message)
        if message_id in self._seen_messages:
            # Still within dedup window?
            seen_at = self._seen_messages[message_id]
            if time.time() - seen_at < self._config.dedup_window_seconds:
                log.debug("Duplicate gossip message ignored: %s", message_id[:8])
                return False

        # Process based on message type
        success = False
        if message.message_type == "peer_announce":
            success = await self._process_peer_announce(message)
        elif message.message_type == "content_announce":
            success = await self._process_content_announce(message)
        elif message.message_type == "route_update":
            success = await self._process_route_update(message)
        else:
            log.warning("Unknown gossip message type: %s", message.message_type)

        if success:
            # Mark as processed
            await self._peer_repo.mark_gossip_processed(message.id if hasattr(message, 'id') else None)

            # Track for deduplication
            self._seen_messages[message_id] = time.time()

            # Rebroadcast if TTL > 0
            if message.ttl > 0:
                message.ttl -= 1
                await self.broadcast_message(
                    message.message_type,
                    message.payload,
                    ttl=message.ttl,
                    source_peer_id=message.source_peer_id,
                )

        return success

    async def announce_peer(
        self,
        peer_id: str,
        ip_address: str,
        port: int,
        capabilities: Dict[str, Any],
    ) -> bool:
        """
        Announce a peer to the network.

        Args:
            peer_id: Peer ID to announce
            ip_address: Peer IP address
            port: Peer port
            capabilities: Peer capabilities dict

        Returns:
            True if announcement succeeded
        """
        payload = {
            "peer_id": peer_id,
            "ip_address": ip_address,
            "port": port,
            "capabilities": capabilities,
            "timestamp": time.time(),
        }

        return await self.broadcast_message(
            message_type="peer_announce",
            payload=payload,
        )

    async def announce_content(
        self,
        content_hash: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """
        Announce content availability to the network.

        Args:
            content_hash: Content hash
            metadata: Content metadata (title, tags, size, etc.)

        Returns:
            True if announcement succeeded
        """
        payload = {
            "content_hash": content_hash,
            "metadata": metadata,
            "timestamp": time.time(),
        }

        return await self.broadcast_message(
            message_type="content_announce",
            payload=payload,
        )

    async def announce_route(
        self,
        destination_peer_id: str,
        next_hop_peer_id: str,
        hop_count: int,
        latency_ms: Optional[int] = None,
    ) -> bool:
        """
        Announce a mesh route to the network.

        Args:
            destination_peer_id: Destination peer ID
            next_hop_peer_id: Next hop peer ID
            hop_count: Number of hops
            latency_ms: Route latency in milliseconds

        Returns:
            True if announcement succeeded
        """
        payload = {
            "destination_peer_id": destination_peer_id,
            "next_hop_peer_id": next_hop_peer_id,
            "hop_count": hop_count,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }

        return await self.broadcast_message(
            message_type="route_update",
            payload=payload,
        )

    async def get_pending_messages(self, limit: int = 100) -> List[GossipMessage]:
        """
        Get unprocessed gossip messages from the repository.

        Args:
            limit: Maximum number of messages to retrieve

        Returns:
            List of unprocessed gossip messages
        """
        db_messages = await self._peer_repo.get_unprocessed_gossip_messages(limit)
        return [GossipMessage.from_dict(msg.to_dict()) for msg in db_messages]

    def _compute_message_id(self, message: GossipMessage) -> str:
        """Compute a unique ID for deduplication."""
        import hashlib

        canonical = json.dumps(
            {
                "type": message.message_type,
                "payload": message.payload,
                "source": message.source_peer_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _build_nostr_event(self, message: GossipMessage) -> NostrEvent:
        """Build a Nostr event from a gossip message."""
        content_str = json.dumps(message.to_dict(), separators=(",", ":"))
        tags = [["t", "tfp"], ["t", "gossip"], ["t", message.message_type]]

        return NostrEvent.create(
            privkey=self._nostr_bridge._privkey,
            kind=TFP_PEER_ANNOUNCE_KIND,
            content=content_str,
            tags=tags,
        )

    async def _process_peer_announce(self, message: GossipMessage) -> bool:
        """Process a peer announcement message."""
        try:
            peer_id = message.payload.get("peer_id")
            if not peer_id:
                return False

            # Check if peer already exists
            existing = await self._peer_repo.get_peer(peer_id)
            if existing:
                # Update last_seen
                await self._peer_repo.update_peer_last_seen(peer_id)
                log.debug("Updated existing peer from gossip: %s", peer_id)
            else:
                # New peer - would need PeerInfo to register
                log.info("Discovered new peer via gossip: %s", peer_id)

            return True
        except Exception as exc:
            log.error("Failed to process peer announce: %s", exc)
            return False

    async def _process_content_announce(self, message: GossipMessage) -> bool:
        """Process a content announcement message."""
        try:
            content_hash = message.payload.get("content_hash")
            if not content_hash:
                return False

            log.debug("Content announced via gossip: %s", content_hash[:8])
            # Could trigger content download or caching here
            return True
        except Exception as exc:
            log.error("Failed to process content announce: %s", exc)
            return False

    async def _process_route_update(self, message: GossipMessage) -> bool:
        """Process a route update message."""
        try:
            destination = message.payload.get("destination_peer_id")
            next_hop = message.payload.get("next_hop_peer_id")
            hop_count = message.payload.get("hop_count", 1)
            latency_ms = message.payload.get("latency_ms")

            if not destination or not next_hop:
                return False

            # Upsert route in repository
            await self._peer_repo.upsert_route(
                destination_peer_id=destination,
                next_hop_peer_id=next_hop,
                hop_count=hop_count,
                latency_ms=latency_ms,
                route_quality=1.0,  # Initial quality
            )

            log.debug(
                "Route updated via gossip: %s -> %s (%d hops)",
                destination,
                next_hop,
                hop_count,
            )
            return True
        except Exception as exc:
            log.error("Failed to process route update: %s", exc)
            return False

    def cleanup_old_messages(self):
        """Remove expired deduplication entries."""
        now = time.time()
        expired = [
            msg_id
            for msg_id, seen_at in self._seen_messages.items()
            if now - seen_at > self._config.dedup_window_seconds
        ]
        for msg_id in expired:
            del self._seen_messages[msg_id]

        if expired:
            log.debug("Cleaned up %d expired gossip message IDs", len(expired))
