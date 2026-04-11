"""
TFP Merkleized RaptorQ - Transport Integrity Layer

Maps RaptorQ symbols to Merkle tree nodes, verifies shard integrity before decoding,
and requires multiple independent Interest convergences for cache admission.

Prevents poisoned shard attacks and ensures transport-level data integrity.
"""

import hashlib
import hmac
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RateLimitRecord:
    """Track rate limit state for a client."""

    tokens: float
    last_update: float
    rejected_count: int = 0


@dataclass
class ShardMetadata:
    """Metadata for a RaptorQ shard."""

    shard_id: int
    symbol_id: int
    data: bytes
    mac: bytes
    merkle_proof: List[str]  # Sibling hashes for Merkle proof
    timestamp: float = field(default_factory=time.time)


@dataclass
class MerkleTree:
    """Merkle tree for shard verification."""

    root_hash: str
    leaf_hashes: List[str]
    tree_depth: int

    def get_proof(self, leaf_index: int, total_leaves: int) -> List[tuple]:
        """Generate Merkle proof for a leaf node. Returns list of (step_type, sibling_hash, is_left_sibling)."""
        if leaf_index >= total_leaves:
            return []

        # Build the tree level by level to capture all intermediate hashes
        levels = [self.leaf_hashes[:total_leaves]]
        current_level = self.leaf_hashes[:total_leaves]

        while len(current_level) > 1:
            next_level = []
            i = 0
            while i < len(current_level):
                if i + 1 < len(current_level):
                    # Pair exists
                    combined = hashlib.sha3_256(
                        (current_level[i] + current_level[i + 1]).encode()
                    ).hexdigest()
                    next_level.append(combined)
                    i += 2
                else:
                    # Odd element, self-combine
                    combined = hashlib.sha3_256(
                        (current_level[i] + current_level[i]).encode()
                    ).hexdigest()
                    next_level.append(combined)
                    i += 1
            levels.append(next_level)
            current_level = next_level

        # Generate proof by walking up the tree
        proof = []
        idx = leaf_index

        for level_idx in range(len(levels) - 1):
            level = levels[level_idx]
            if idx % 2 == 0:
                # Current is left child
                if idx + 1 < len(level):
                    # Sibling exists on right
                    proof.append(
                        ("sibling", level[idx + 1], False)
                    )  # sibling is on right, so NOT left
                else:
                    # Self-combine
                    proof.append(("self", None, True))
            else:
                # Current is right child, sibling is on left
                proof.append(("sibling", level[idx - 1], True))  # sibling is on left

            idx = idx // 2

        return proof

    def verify_proof(
        self, leaf_data: bytes, leaf_index: int, proof: List[tuple]
    ) -> bool:
        """Verify a Merkle proof for given data."""
        current_hash = hashlib.sha3_256(leaf_data).hexdigest()

        for step in proof:
            step_type = step[0]
            if step_type == "self":
                # Self-combine for odd last element
                combined = current_hash + current_hash
            else:
                # step = ('sibling', sibling_hash, is_left_sibling)
                sibling_hash = step[1]
                is_left_sibling = step[2]

                if is_left_sibling:
                    # Sibling is on left, current is on right
                    combined = sibling_hash + current_hash
                else:
                    # Sibling is on right, current is on left
                    combined = current_hash + sibling_hash

            current_hash = hashlib.sha3_256(combined.encode()).hexdigest()

        return current_hash == self.root_hash


@dataclass
class CacheAdmissionRecord:
    """Track Interest convergences for cache admission."""

    content_hash: str
    interest_sources: set  # Set of source identifiers
    first_seen: float
    last_seen: float
    convergence_count: int = 0


class MerkleizedRaptorQ:
    """
    Provides transport-level integrity for RaptorQ-encoded content.

    Features:
    - Maps RaptorQ symbols to Merkle tree nodes
    - Verifies shard MACs BEFORE decoding
    - Requires ≥2 independent Interest convergences for cache admission
    - Drops poisoned shards immediately
    """

    def __init__(
        self,
        required_convergences: int = 2,
        rate_limit_tokens: float = 10.0,
        rate_limit_refill: float = 1.0,
    ):
        self.required_convergences = required_convergences
        self._lock = threading.Lock()
        self._merkle_trees: Dict[str, MerkleTree] = {}  # content_hash -> tree
        self._cache_admission: Dict[str, CacheAdmissionRecord] = {}
        self._verified_shards: Dict[
            str, Dict[int, ShardMetadata]
        ] = {}  # content_hash -> {shard_id -> shard}
        self._dropped_shards: List[Dict[str, Any]] = []  # Log of dropped shards

        # Rate limiting (token bucket algorithm)
        self._rate_limits: Dict[str, RateLimitRecord] = defaultdict(
            lambda: RateLimitRecord(tokens=rate_limit_tokens, last_update=time.time())
        )
        self.rate_limit_max_tokens = rate_limit_tokens
        self.rate_limit_refill_per_sec = rate_limit_refill

    def register_content(
        self, content_hash: str, shard_data_list: List[bytes]
    ) -> MerkleTree:
        """
        Register content and build its Merkle tree.

        Args:
            content_hash: Hash of the original content
            shard_data_list: List of RaptorQ shard data

        Returns:
            MerkleTree for verification
        """
        # Compute leaf hashes
        leaf_hashes = [
            hashlib.sha3_256(shard_data).hexdigest() for shard_data in shard_data_list
        ]

        # Build Merkle tree
        root_hash = self._build_merkle_root(leaf_hashes)
        tree_depth = len(leaf_hashes).bit_length()

        tree = MerkleTree(
            root_hash=root_hash, leaf_hashes=leaf_hashes, tree_depth=tree_depth
        )

        with self._lock:
            self._merkle_trees[content_hash] = tree
            self._verified_shards[content_hash] = {}

        return tree

    def _check_rate_limit(self, client_id: str) -> Tuple[bool, float]:
        """
        Check and update rate limit for a client using token bucket algorithm.

        Args:
            client_id: Unique identifier for the client (e.g., IP, pubkey)

        Returns:
            Tuple of (is_allowed, wait_time_seconds)
        """
        current_time = time.time()

        with self._lock:
            record = self._rate_limits[client_id]

            # Refill tokens based on elapsed time
            elapsed = current_time - record.last_update
            record.tokens = min(
                self.rate_limit_max_tokens,
                record.tokens + elapsed * self.rate_limit_refill_per_sec,
            )
            record.last_update = current_time

            if record.tokens >= 1.0:
                # Consume one token
                record.tokens -= 1.0
                return True, 0.0
            else:
                # Rate limited
                record.rejected_count += 1
                # Calculate wait time to get 1 token
                wait_time = (1.0 - record.tokens) / self.rate_limit_refill_per_sec
                return False, wait_time

    def verify_shard(
        self,
        content_hash: str,
        shard_id: int,
        shard_data: bytes,
        expected_mac: bytes,
        merkle_proof: List[str],
        client_id: str = "default",
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify a RaptorQ shard before decoding.

        Args:
            content_hash: Hash of the content
            shard_id: ID of the shard
            shard_data: Raw shard data
            expected_mac: Expected MAC for the shard
            merkle_proof: Merkle proof for the shard
            client_id: Client identifier for rate limiting

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check rate limit FIRST (before any heavy computation)
        is_allowed, wait_time = self._check_rate_limit(client_id)
        if not is_allowed:
            self._log_dropped_shard(
                content_hash, shard_id, f"RATE_LIMITED(wait={wait_time:.2f}s)"
            )
            return False, f"Rate limit exceeded. Wait {wait_time:.2f}s"

        # Use constant-time comparison for MAC verification to prevent timing attacks
        computed_mac = hashlib.sha3_256(
            f"{content_hash}:{shard_id}:".encode() + shard_data
        ).digest()

        # Constant-time MAC comparison
        if not hmac.compare_digest(computed_mac, expected_mac):
            self._log_dropped_shard(content_hash, shard_id, "MAC_MISMATCH")
            return False, "MAC verification failed"

        # Verify Merkle proof
        with self._lock:
            tree = self._merkle_trees.get(content_hash)

        if not tree:
            self._log_dropped_shard(content_hash, shard_id, "NO_MERKLE_TREE")
            return False, "Merkle tree not found"

        if not tree.verify_proof(shard_data, shard_id, merkle_proof):
            self._log_dropped_shard(content_hash, shard_id, "MERKLE_PROOF_FAILED")
            return False, "Merkle proof verification failed"

        # Shard is valid, store it
        with self._lock:
            if content_hash not in self._verified_shards:
                self._verified_shards[content_hash] = {}

            self._verified_shards[content_hash][shard_id] = ShardMetadata(
                shard_id=shard_id,
                symbol_id=shard_id,
                data=shard_data,
                mac=expected_mac,
                merkle_proof=merkle_proof,
            )

        return True, None

    def record_interest_convergence(self, content_hash: str, source_id: str) -> bool:
        """
        Record an Interest convergence for cache admission.

        Args:
            content_hash: Hash of the content
            source_id: Identifier of the Interest source

        Returns:
            True if cache admission criteria are met
        """
        current_time = time.time()

        with self._lock:
            if content_hash not in self._cache_admission:
                self._cache_admission[content_hash] = CacheAdmissionRecord(
                    content_hash=content_hash,
                    interest_sources={source_id},
                    first_seen=current_time,
                    last_seen=current_time,
                    convergence_count=1,
                )
            else:
                record = self._cache_admission[content_hash]
                if source_id not in record.interest_sources:
                    record.interest_sources.add(source_id)
                    record.convergence_count += 1
                    record.last_seen = current_time

        return self._check_cache_admission(content_hash)

    def _check_cache_admission(self, content_hash: str) -> bool:
        """Check if content meets cache admission criteria."""
        with self._lock:
            record = self._cache_admission.get(content_hash)
            if not record:
                return False

            return record.convergence_count >= self.required_convergences

    def get_verified_shards(self, content_hash: str) -> Dict[int, bytes]:
        """
        Get all verified shards for a content hash.

        Args:
            content_hash: Hash of the content

        Returns:
            Dictionary mapping shard_id to shard data
        """
        with self._lock:
            if content_hash not in self._verified_shards:
                return {}

            return {
                shard_id: shard.data
                for shard_id, shard in self._verified_shards[content_hash].items()
            }

    def get_integrity_stats(self) -> Dict[str, Any]:
        """Get transport integrity statistics."""
        with self._lock:
            total_shards = sum(len(shards) for shards in self._verified_shards.values())
            total_rejected = sum(
                record.rejected_count for record in self._rate_limits.values()
            )

            return {
                "registered_contents": len(self._merkle_trees),
                "verified_shards": total_shards,
                "dropped_shards": len(self._dropped_shards),
                "pending_admissions": len(
                    [
                        r
                        for r in self._cache_admission.values()
                        if r.convergence_count < self.required_convergences
                    ]
                ),
                "admitted_contents": len(
                    [
                        r
                        for r in self._cache_admission.values()
                        if r.convergence_count >= self.required_convergences
                    ]
                ),
                "rate_limited_requests": total_rejected,
                "unique_clients": len(self._rate_limits),
            }

    def _build_merkle_root(self, leaf_hashes: List[str]) -> str:
        """Build Merkle root from leaf hashes."""
        if not leaf_hashes:
            return hashlib.sha3_256(b"").hexdigest()

        level = leaf_hashes.copy()

        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else left
                combined = hashlib.sha3_256((left + right).encode()).hexdigest()
                next_level.append(combined)

            level = next_level

        return level[0]

    def _log_dropped_shard(self, content_hash: str, shard_id: int, reason: str) -> None:
        """Log a dropped shard for auditing."""
        self._dropped_shards.append(
            {
                "content_hash": content_hash,
                "shard_id": shard_id,
                "reason": reason,
                "timestamp": time.time(),
            }
        )

        # Limit log size
        if len(self._dropped_shards) > 10000:
            self._dropped_shards = self._dropped_shards[-5000:]


# Feature gate check
def is_transport_integrity_enabled() -> bool:
    """Check if transport integrity features are enabled."""
    import os

    return os.getenv("TFP_FEATURES_TRANSPORT_INTEGRITY", "false").lower() == "true"


if __name__ == "__main__":
    # Demo usage with rate limiting and timing attack protection
    mrq = MerkleizedRaptorQ(
        required_convergences=2, rate_limit_tokens=5.0, rate_limit_refill=1.0
    )

    # Simulate content registration
    content_hash = "abc123"
    shard_data = [b"shard0", b"shard1", b"shard2", b"shard3"]

    tree = mrq.register_content(content_hash, shard_data)
    print(f"Merkle Root: {tree.root_hash}")

    # Verify shards with rate limiting
    print("\n=== Testing Rate Limiting ===")
    total_leaves = len(shard_data)
    for i in range(7):  # Try to verify more shards than rate limit allows
        shard_id = i % 4
        proof = tree.get_proof(shard_id, total_leaves)
        mac = hashlib.sha3_256(
            f"{content_hash}:{shard_id}:".encode() + shard_data[shard_id]
        ).digest()

        is_valid, error = mrq.verify_shard(
            content_hash=content_hash,
            shard_id=shard_id,
            shard_data=shard_data[shard_id],
            expected_mac=mac,
            merkle_proof=proof,
            client_id="test_client_1",
        )

        print(f"Request {i + 1}: Shard {shard_id} valid={is_valid}", end="")
        if error:
            print(f" - {error}")
        else:
            print()

    # Test constant-time comparison (timing attack protection)
    print("\n=== Testing Timing Attack Protection ===")
    print("Using hmac.compare_digest() for constant-time MAC comparison")

    # Simulate Interest convergences
    print("\n=== Testing Interest Convergence ===")
    for i, source in enumerate(["source_A", "source_B", "source_C"]):
        admitted = mrq.record_interest_convergence(content_hash, source)
        print(f"Convergence {i + 1} from {source}: Admitted={admitted}")

    print("\nIntegrity Stats:")
    stats = mrq.get_integrity_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
