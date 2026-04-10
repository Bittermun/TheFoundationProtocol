"""
TFP Merkleized RaptorQ - Transport Integrity Layer

Maps RaptorQ symbols to Merkle tree nodes, verifies shard integrity before decoding,
and requires multiple independent Interest convergences for cache admission.

Prevents poisoned shard attacks and ensures transport-level data integrity.
"""

import hashlib
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
import threading
import time


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
    
    def get_proof(self, leaf_index: int, total_leaves: int) -> List[str]:
        """Generate Merkle proof for a leaf node."""
        if leaf_index >= total_leaves:
            return []
        
        proof = []
        idx = leaf_index
        level_size = total_leaves
        
        while level_size > 1:
            # Track if current idx is in this pair
            pair_idx = idx // 2
            sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
            
            # Add sibling to proof if exists (not self-combined)
            if sibling_idx < level_size:
                proof.append(('sibling', sibling_idx))
            else:
                proof.append(('self', None))  # Self-combine for odd last element
            
            level_size = (level_size + 1) // 2
            idx = pair_idx
        
        return proof
    
    def verify_proof(self, leaf_data: bytes, leaf_index: int, proof: List[tuple], 
                     leaf_hashes: List[str]) -> bool:
        """Verify a Merkle proof for given data."""
        current_hash = hashlib.sha3_256(leaf_data).hexdigest()
        idx = leaf_index
        level_size = len(leaf_hashes)
        
        for step_type, step_data in proof:
            if step_type == 'self':
                # Self-combine for odd last element
                combined = current_hash + current_hash
            else:
                # Sibling combine
                sibling_idx = step_data
                sibling_hash = leaf_hashes[sibling_idx] if isinstance(sibling_idx, int) else step_data
                if idx % 2 == 0:
                    # Current is left child, sibling is right
                    combined = current_hash + sibling_hash
                else:
                    # Current is right child, sibling is left
                    combined = sibling_hash + current_hash
            
            current_hash = hashlib.sha3_256(combined.encode()).hexdigest()
            idx = idx // 2
            level_size = (level_size + 1) // 2
        
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
    
    def __init__(self, required_convergences: int = 2):
        self.required_convergences = required_convergences
        self._lock = threading.Lock()
        self._merkle_trees: Dict[str, MerkleTree] = {}  # content_hash -> tree
        self._cache_admission: Dict[str, CacheAdmissionRecord] = {}
        self._verified_shards: Dict[str, Dict[int, ShardMetadata]] = {}  # content_hash -> {shard_id -> shard}
        self._dropped_shards: List[Dict[str, Any]] = []  # Log of dropped shards
        
    def register_content(self, content_hash: str, shard_data_list: List[bytes]) -> MerkleTree:
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
            hashlib.sha3_256(shard_data).hexdigest()
            for shard_data in shard_data_list
        ]
        
        # Build Merkle tree
        root_hash = self._build_merkle_root(leaf_hashes)
        tree_depth = len(leaf_hashes).bit_length()
        
        tree = MerkleTree(
            root_hash=root_hash,
            leaf_hashes=leaf_hashes,
            tree_depth=tree_depth
        )
        
        with self._lock:
            self._merkle_trees[content_hash] = tree
            self._verified_shards[content_hash] = {}
        
        return tree
    
    def verify_shard(
        self,
        content_hash: str,
        shard_id: int,
        shard_data: bytes,
        expected_mac: bytes,
        merkle_proof: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify a RaptorQ shard before decoding.
        
        Args:
            content_hash: Hash of the content
            shard_id: ID of the shard
            shard_data: Raw shard data
            expected_mac: Expected MAC for the shard
            merkle_proof: Merkle proof for the shard
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Compute MAC
        computed_mac = hashlib.sha3_256(
            f"{content_hash}:{shard_id}:".encode() + shard_data
        ).digest()
        
        if computed_mac != expected_mac:
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
                merkle_proof=merkle_proof
            )
        
        return True, None
    
    def record_interest_convergence(
        self,
        content_hash: str,
        source_id: str
    ) -> bool:
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
                    convergence_count=1
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
            total_shards = sum(
                len(shards) for shards in self._verified_shards.values()
            )
            
            return {
                "registered_contents": len(self._merkle_trees),
                "verified_shards": total_shards,
                "dropped_shards": len(self._dropped_shards),
                "pending_admissions": len([
                    r for r in self._cache_admission.values()
                    if r.convergence_count < self.required_convergences
                ]),
                "admitted_contents": len([
                    r for r in self._cache_admission.values()
                    if r.convergence_count >= self.required_convergences
                ])
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
    
    def _log_dropped_shard(
        self,
        content_hash: str,
        shard_id: int,
        reason: str
    ) -> None:
        """Log a dropped shard for auditing."""
        self._dropped_shards.append({
            "content_hash": content_hash,
            "shard_id": shard_id,
            "reason": reason,
            "timestamp": time.time()
        })
        
        # Limit log size
        if len(self._dropped_shards) > 10000:
            self._dropped_shards = self._dropped_shards[-5000:]


# Feature gate check
def is_transport_integrity_enabled() -> bool:
    """Check if transport integrity features are enabled."""
    import os
    return os.getenv("TFP_FEATURES_TRANSPORT_INTEGRITY", "false").lower() == "true"


if __name__ == "__main__":
    # Demo usage
    mrq = MerkleizedRaptorQ(required_convergences=2)
    
    # Simulate content registration
    content_hash = "abc123"
    shard_data = [b"shard0", b"shard1", b"shard2", b"shard3"]
    
    tree = mrq.register_content(content_hash, shard_data)
    print(f"Merkle Root: {tree.root_hash}")
    
    # Verify a shard
    shard_id = 1
    proof = tree.get_proof(shard_id)
    mac = hashlib.sha3_256(
        f"{content_hash}:{shard_id}:".encode() + shard_data[shard_id]
    ).digest()
    
    is_valid, error = mrq.verify_shard(
        content_hash=content_hash,
        shard_id=shard_id,
        shard_data=shard_data[shard_id],
        expected_mac=mac,
        merkle_proof=proof
    )
    
    print(f"Shard {shard_id} valid: {is_valid}")
    if error:
        print(f"Error: {error}")
    
    # Simulate Interest convergences
    for i, source in enumerate(["source_A", "source_B", "source_C"]):
        admitted = mrq.record_interest_convergence(content_hash, source)
        print(f"Convergence {i+1} from {source}: Admitted={admitted}")
    
    print("\nIntegrity Stats:")
    stats = mrq.get_integrity_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
