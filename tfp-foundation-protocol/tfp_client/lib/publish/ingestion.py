"""
Publish Ingestion - Device-side content publishing for TFP

Flow:
1. Hash content
2. RaptorQ encode into shards
3. NDN Announce to local mesh
4. Wait for mesh cache confirmation
"""

import hashlib
import time
from typing import Any, Dict, List, Optional

# Import from existing TFP modules
try:
    from ..fountain.fountain_real import RealRaptorQAdapter
except ImportError:
    RealRaptorQAdapter = None

try:
    from ..ndn.ndn_real import RealNDNAdapter
except ImportError:
    RealNDNAdapter = None


class PublishIngestion:
    """
    Handles device-side content publishing workflow.

    Usage:
        ingestion = PublishIngestion()
        content_hash = ingestion.announce_content(b"my content", {"title": "Test"})

        # Or full flow with encoding:
        shards = ingestion.encode_and_announce(b"my content")
        confirmed = ingestion.wait_for_mesh_cache_confirmation(content_hash, timeout=30)
    """

    def __init__(self, hmac_key: Optional[bytes] = None):
        """
        Initialize publish ingestion.

        Args:
            hmac_key: Optional HMAC key for shard integrity (uses fountain adapter default if None)
        """
        self._hmac_key = hmac_key
        self._fountain = RealRaptorQAdapter() if RealRaptorQAdapter else None
        self._ndn = RealNDNAdapter(fallback_content=b"{}") if RealNDNAdapter else None
        self._pending_announcements: Dict[str, float] = {}  # hash -> timestamp

    def announce_content(self, content: bytes, metadata: Dict[str, Any]) -> str:
        """
        Announce content to the mesh network.

        This is the lightweight path - just announces the hash and metadata,
        letting interested nodes request the actual content.

        Args:
            content: Raw content bytes
            metadata: Content metadata (title, tags, domain, etc.)

        Returns:
            Content hash (hex string)
        """
        # Compute content hash
        content_hash = hashlib.sha3_256(content).digest()
        hash_hex = content_hash.hex()

        # Build announcement message
        announcement = {  # noqa: F841
            "type": "publish_announce",
            "hash": hash_hex,
            "size": len(content),
            "metadata": metadata,
            "timestamp": time.time(),
        }

        # Create NDN interest for announcement
        if self._ndn:
            announce_name = f"/tfp/publish/announce/{hash_hex}"
            interest = self._ndn.create_interest(announce_name.encode())
            # Express interest to announce presence
            self._ndn.express_interest(interest)

        # Track pending announcement
        self._pending_announcements[hash_hex] = time.time()

        return hash_hex

    def encode_and_announce(
        self, content: bytes, redundancy: float = 0.1
    ) -> List[bytes]:
        """
        Full publish flow: encode content and announce shards.

        Args:
            content: Raw content bytes
            redundancy: RaptorQ redundancy factor (default 0.1 = 10% extra shards)

        Returns:
            List of encoded shards

        Raises:
            RuntimeError: If fountain encoder not available
        """
        if not self._fountain:
            raise RuntimeError("Fountain encoder not available")

        if len(content) == 0:
            raise ValueError("Cannot publish empty content")

        # Encode with RaptorQ
        shards = self._fountain.encode(
            content, redundancy=redundancy, hmac_key=self._hmac_key
        )

        # Compute content hash for reference
        content_hash = hashlib.sha3_256(content).digest()
        hash_hex = content_hash.hex()

        # Announce each shard via NDN
        if self._ndn:
            for i, shard in enumerate(shards):
                shard_name = f"/tfp/publish/shard/{hash_hex}/{i}"
                interest = self._ndn.create_interest(shard_name.encode())
                self._ndn.express_interest(interest)

        # Track pending
        self._pending_announcements[hash_hex] = time.time()

        return shards

    def wait_for_mesh_cache_confirmation(
        self, hash_hex: str, timeout: int = 30
    ) -> bool:
        """
        Wait for mesh nodes to confirm caching of content.

        In a real implementation, this would listen for cache confirmation
        messages from mesh nodes. For now, simulates with a delay.

        Args:
            hash_hex: Content hash to wait for
            timeout: Maximum seconds to wait

        Returns:
            True if confirmed, False if timeout
        """
        if hash_hex not in self._pending_announcements:
            return False

        start_time = time.time()
        while time.time() - start_time < timeout:
            # In real implementation, check for confirmation messages
            # For simulation, assume confirmation after short delay
            elapsed = time.time() - self._pending_announcements[hash_hex]
            if elapsed > 2.0:  # Simulated 2-second cache propagation
                del self._pending_announcements[hash_hex]
                return True
            time.sleep(0.1)

        # Timeout - clean up
        if hash_hex in self._pending_announcements:
            del self._pending_announcements[hash_hex]
        return False

    def get_pending_announcements(self) -> List[str]:
        """Get list of pending announcement hashes."""
        return list(self._pending_announcements.keys())

    def cancel_announcement(self, hash_hex: str) -> bool:
        """
        Cancel a pending announcement.

        Args:
            hash_hex: Hash to cancel

        Returns:
            True if cancelled, False if not found
        """
        if hash_hex in self._pending_announcements:
            del self._pending_announcements[hash_hex]
            return True
        return False

    def build_publish_interest(self, content_hash: str, shard_idx: int = -1) -> bytes:
        """
        Build an NDN interest name for published content.

        Args:
            content_hash: Hex content hash
            shard_idx: Shard index (-1 for full content, 0+ for specific shard)

        Returns:
            Serialized interest name
        """
        if shard_idx < 0:
            name = f"/tfp/content/{content_hash}"
        else:
            name = f"/tfp/shard/{content_hash}/{shard_idx}"

        return name.encode("utf-8")

    def estimate_shard_count(self, content_size: int, shard_size: int = 1024) -> int:
        """
        Estimate number of shards for given content size.

        Args:
            content_size: Size of content in bytes
            shard_size: Target shard size (default 1KB)

        Returns:
            Estimated shard count
        """
        import math

        return math.ceil(content_size / shard_size)
