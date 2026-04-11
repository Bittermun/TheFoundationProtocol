"""
Tag Overlay Index - Decentralized Metadata Layer for TFP

Provides tag-based content discovery without central indexers by:
- Building Merkle DAGs of tag→hash mappings
- Broadcasting weekly indices with Bloom filter compression
- Enabling local queries for tag-based discovery
"""

import dataclasses
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .bloom_filter import BloomFilter


@dataclasses.dataclass
class TagEntry:
    """A single entry in the tag index."""

    tag: str
    content_hash: bytes
    popularity_score: float  # 0.0 to 1.0

    def __post_init__(self):
        if not (0.0 <= self.popularity_score <= 1.0):
            raise ValueError("popularity_score must be between 0.0 and 1.0")
        if len(self.content_hash) != 32:
            raise ValueError("content_hash must be 32 bytes (SHA3-256)")

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "hash": self.content_hash.hex(),
            "popularity": self.popularity_score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TagEntry":
        return cls(
            tag=data["tag"],
            content_hash=bytes.fromhex(data["hash"]),
            popularity_score=data["popularity"],
        )


@dataclasses.dataclass
class TagIndexDAG:
    """
    A Merkle DAG representing a weekly tag index for a domain.

    Attributes:
        epoch: ISO week number (e.g., 202501 for week 1 of 2025)
        domain: Content domain (e.g., "science", "news", "education")
        entries: List of TagEntry objects
        merkle_root: Root hash of the Merkle tree
        timestamp: When this DAG was created
    """

    epoch: int
    domain: str
    entries: List[TagEntry]
    merkle_root: bytes
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "epoch": self.epoch,
            "domain": self.domain,
            "entries": [e.to_dict() for e in self.entries],
            "merkle_root": self.merkle_root.hex(),
            "timestamp": self.timestamp,
        }

    def to_bytes(self) -> bytes:
        """Serialize to bytes for transmission."""
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "TagIndexDAG":
        """Deserialize from bytes."""
        d = json.loads(data.decode("utf-8"))
        entries = [TagEntry.from_dict(e) for e in d["entries"]]
        return cls(
            epoch=d["epoch"],
            domain=d["domain"],
            entries=entries,
            merkle_root=bytes.fromhex(d["merkle_root"]),
            timestamp=d["timestamp"],
        )


class TagOverlayIndex:
    """
    Manages the tag overlay index for decentralized content discovery.

    Usage:
        index = TagOverlayIndex()
        index.add_entry("science", ["physics", "quantum"], content_hash, 0.95)
        dag = index.build_merkle_dag(epoch=202501, domain="science")
        bloom = index.export_bloom_filter(dag)

        # Later, query locally:
        if index.query_tag(bloom, "physics"):
            # Request the full index or specific content
            pass
    """

    def __init__(self):
        # Storage: domain → epoch → list of entries
        self._storage: Dict[str, Dict[int, List[TagEntry]]] = {}

    def add_entry(
        self, domain: str, tags: List[str], content_hash: bytes, popularity: float
    ) -> None:
        """
        Add a content entry with multiple tags.

        Args:
            domain: Content domain (e.g., "science", "news")
            tags: List of tags for this content
            content_hash: SHA3-256 hash of the content
            popularity: Popularity score (0.0 to 1.0)
        """
        if len(content_hash) != 32:
            raise ValueError("content_hash must be 32 bytes")

        # Create an entry for each tag
        for tag in tags:
            entry = TagEntry(
                tag=tag.lower(),  # Normalize tags to lowercase
                content_hash=content_hash,
                popularity_score=popularity,
            )

            if domain not in self._storage:
                self._storage[domain] = {}

            # Use current epoch if not specified
            epoch = self._get_current_epoch()
            if epoch not in self._storage[domain]:
                self._storage[domain][epoch] = []

            self._storage[domain][epoch].append(entry)

    def build_merkle_dag(self, epoch: int, domain: str) -> TagIndexDAG:
        """
        Build a Merkle DAG for a specific epoch and domain.

        Args:
            epoch: ISO week number
            domain: Content domain

        Returns:
            TagIndexDAG with computed Merkle root

        Raises:
            ValueError: If no entries exist for this epoch/domain
        """
        if domain not in self._storage or epoch not in self._storage[domain]:
            raise ValueError(f"No entries for domain={domain}, epoch={epoch}")

        entries = self._storage[domain][epoch]

        # Sort entries by tag for deterministic ordering
        sorted_entries = sorted(entries, key=lambda e: (e.tag, e.content_hash.hex()))

        # Build Merkle tree
        merkle_root = self._build_merkle_root(sorted_entries)

        return TagIndexDAG(
            epoch=epoch,
            domain=domain,
            entries=sorted_entries,
            merkle_root=merkle_root,
            timestamp=datetime.now(timezone.utc).timestamp(),
        )

    def _build_merkle_root(self, entries: List[TagEntry]) -> bytes:
        """
        Build a binary Merkle tree over sorted entries.

        Args:
            entries: Sorted list of TagEntry objects

        Returns:
            Merkle root hash (32 bytes)
        """
        if not entries:
            return hashlib.sha3_256(b"").digest()

        # Hash each entry
        nodes = []
        for entry in entries:
            # Serialize entry for hashing
            entry_data = (
                f"{entry.tag}:{entry.content_hash.hex()}:{entry.popularity_score}"
            )
            node_hash = hashlib.sha3_256(entry_data.encode("utf-8")).digest()
            nodes.append(node_hash)

        # Build tree bottom-up
        while len(nodes) > 1:
            next_level = []
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                right = nodes[i + 1] if i + 1 < len(nodes) else left
                parent = hashlib.sha3_256(left + right).digest()
                next_level.append(parent)
            nodes = next_level

        return nodes[0]

    def export_bloom_filter(self, dag: TagIndexDAG) -> BloomFilter:
        """
        Export a Bloom filter for efficient tag queries.

        The Bloom filter contains all unique tags in the DAG.

        Args:
            dag: TagIndexDAG to compress

        Returns:
            BloomFilter containing all tags
        """
        # Calculate optimal size based on entry count
        unique_tags = set(e.tag for e in dag.entries)
        n = len(unique_tags)

        if n == 0:
            return BloomFilter(size_bits=1000, hash_count=3)

        # Use optimal parameters for ~1% FPR
        size_bits = BloomFilter.optimal_size(n, 0.01)
        hash_count = BloomFilter.optimal_hash_count(size_bits, n)

        bf = BloomFilter(size_bits=size_bits, hash_count=hash_count)

        for tag in unique_tags:
            bf.add(tag.encode("utf-8"))

        return bf

    def query_tag(self, bloom: BloomFilter, tag: str) -> bool:
        """
        Query if a tag might exist in the index.

        This is a local query against the Bloom filter - no network needed.

        Args:
            bloom: Bloom filter from export_bloom_filter()
            tag: Tag to query

        Returns:
            True if tag might exist, False if definitely doesn't
        """
        return bloom.contains(tag)

    def get_merkle_proof(
        self, dag: TagIndexDAG, tag: str, content_hash: bytes
    ) -> Optional[List[bytes]]:
        """
        Generate a Merkle proof for a specific tag+hash entry.

        Allows verification that an entry is included in the DAG without
        transmitting the entire DAG.

        Args:
            dag: TagIndexDAG containing the entry
            tag: Tag to prove
            content_hash: Content hash to prove

        Returns:
            List of sibling hashes for Merkle proof, or None if not found
        """
        # Find the entry
        target_entry = None
        target_idx = -1
        for i, entry in enumerate(dag.entries):
            if entry.tag == tag and entry.content_hash == content_hash:
                target_entry = entry
                target_idx = i
                break

        if target_entry is None:
            return None

        # Rebuild leaf hashes
        entry_data = f"{target_entry.tag}:{target_entry.content_hash.hex()}:{target_entry.popularity_score}"  # noqa: F841

        # Build full tree and collect proof
        entries = dag.entries
        leaf_hashes = []
        for entry in entries:
            data = f"{entry.tag}:{entry.content_hash.hex()}:{entry.popularity_score}"
            leaf_hashes.append(hashlib.sha3_256(data.encode("utf-8")).digest())

        # Collect proof path
        proof = []
        nodes = leaf_hashes
        idx = target_idx

        while len(nodes) > 1:
            if idx % 2 == 0:
                # Right sibling exists?
                if idx + 1 < len(nodes):
                    proof.append(("right", nodes[idx + 1]))
                else:
                    proof.append(("right", nodes[idx]))  # Duplicate
            else:
                # Left sibling
                proof.append(("left", nodes[idx - 1]))

            # Move to parent level
            next_level = []
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                right = nodes[i + 1] if i + 1 < len(nodes) else left
                next_level.append(hashlib.sha3_256(left + right).digest())

            nodes = next_level
            idx = idx // 2

        return proof

    def verify_merkle_proof(
        self, leaf_data: str, proof: List[Tuple[str, bytes]], merkle_root: bytes
    ) -> bool:
        """
        Verify a Merkle proof.

        Args:
            leaf_data: Serialized leaf data (tag:hash:popularity)
            proof: List of (position, sibling_hash) tuples
            merkle_root: Expected Merkle root

        Returns:
            True if proof is valid
        """
        current_hash = hashlib.sha3_256(leaf_data.encode("utf-8")).digest()

        for position, sibling in proof:
            if position == "left":
                current_hash = hashlib.sha3_256(sibling + current_hash).digest()
            else:  # right
                current_hash = hashlib.sha3_256(current_hash + sibling).digest()

        return current_hash == merkle_root

    def get_entries_by_tag(self, dag: TagIndexDAG, tag: str) -> List[TagEntry]:
        """
        Get all entries matching a specific tag from a DAG.

        Args:
            dag: TagIndexDAG to search
            tag: Tag to filter by

        Returns:
            List of matching TagEntry objects
        """
        tag_lower = tag.lower()
        return [e for e in dag.entries if e.tag == tag_lower]

    def get_popular_entries(
        self, dag: TagIndexDAG, min_popularity: float = 0.8
    ) -> List[TagEntry]:
        """
        Get entries above a popularity threshold.

        Args:
            dag: TagIndexDAG to search
            min_popularity: Minimum popularity score (0.0 to 1.0)

        Returns:
            List of popular TagEntry objects, sorted by popularity descending
        """
        popular = [e for e in dag.entries if e.popularity_score >= min_popularity]
        return sorted(popular, key=lambda e: e.popularity_score, reverse=True)

    @staticmethod
    def _get_current_epoch() -> int:
        """Get current ISO week number as epoch identifier."""
        now = datetime.now(timezone.utc)
        iso_cal = now.isocalendar()
        return iso_cal[0] * 100 + iso_cal[1]  # Year * 100 + Week

    def get_available_epochs(self, domain: str) -> List[int]:
        """Get list of epochs with data for a domain."""
        if domain not in self._storage:
            return []
        return sorted(self._storage[domain].keys())

    def clear_epoch(self, domain: str, epoch: int) -> None:
        """Clear data for a specific epoch (for cleanup/rotation)."""
        if domain in self._storage and epoch in self._storage[domain]:
            del self._storage[domain][epoch]

    def get_stats(self, domain: str, epoch: int) -> dict:
        """
        Get statistics for a domain/epoch.

        Returns:
            Dict with entry_count, unique_tags, avg_popularity
        """
        if domain not in self._storage or epoch not in self._storage[domain]:
            return {"entry_count": 0, "unique_tags": 0, "avg_popularity": 0.0}

        entries = self._storage[domain][epoch]
        unique_tags = set(e.tag for e in entries)
        avg_pop = (
            sum(e.popularity_score for e in entries) / len(entries) if entries else 0.0
        )

        return {
            "entry_count": len(entries),
            "unique_tags": len(unique_tags),
            "avg_popularity": avg_pop,
        }
