# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hierarchical Content-Defined Chunking Example

Demonstrates multi-level CDC for efficient deduplication across different
granularities. This is useful for:
- Large file archives where sub-files share common content
- Version control systems with incremental changes
- Backup systems with rolling snapshots

Hierarchical levels:
1. Level 1: Coarse-grained CDC (e.g., 64KB-1MB chunks)
2. Level 2: Fine-grained CDC within each Level 1 chunk (e.g., 4KB-64KB)
3. Level 3: Optional RaptorQ erasure coding on Level 2 chunks
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass

from tfp_transport.cdc import CDCChunker, create_fastcdc_chunker


@dataclass
class ChunkMetadata:
    """Metadata for a chunk at any hierarchical level."""
    level: int
    index: int
    hash: str
    offset: int
    size: int
    parent_hash: str = None  # For child chunks, reference to parent


@dataclass
class HierarchicalChunkTree:
    """Tree structure representing hierarchical chunking."""
    level1_chunks: List[ChunkMetadata]
    level2_chunks: Dict[str, List[ChunkMetadata]]  # parent_hash -> children
    level3_encoded: Dict[str, List[bytes]] = None  # Optional RaptorQ encoding


class HierarchicalCDC:
    """
    Hierarchical Content-Defined Chunking for multi-level deduplication.

    Applies CDC at multiple granularities to maximize deduplication:
    - Level 1: Coarse chunks for large-scale deduplication
    - Level 2: Fine chunks within each coarse chunk for content-level deduplication
    - Level 3: Optional erasure coding for fault tolerance
    """

    def __init__(
        self,
        level1_min_kb: int = 64,
        level1_max_kb: int = 1024,
        level1_avg_kb: int = 256,
        level2_min_kb: int = 4,
        level2_max_kb: int = 64,
        level2_avg_kb: int = 16,
    ):
        """
        Initialize hierarchical CDC chunker.

        Args:
            level1_min_kb: Minimum size for Level 1 chunks in KB
            level1_max_kb: Maximum size for Level 1 chunks in KB
            level1_avg_kb: Target average size for Level 1 chunks in KB
            level2_min_kb: Minimum size for Level 2 chunks in KB
            level2_max_kb: Maximum size for Level 2 chunks in KB
            level2_avg_kb: Target average size for Level 2 chunks in KB
        """
        self.level1_chunker = create_fastcdc_chunker(
            min_chunk_kb=level1_min_kb,
            max_chunk_kb=level1_max_kb,
            avg_chunk_kb=level1_avg_kb,
        )
        self.level2_chunker = create_fastcdc_chunker(
            min_chunk_kb=level2_min_kb,
            max_chunk_kb=level2_max_kb,
            avg_chunk_kb=level2_avg_kb,
        )

    def chunk_hierarchical(self, data: bytes) -> HierarchicalChunkTree:
        """
        Apply hierarchical CDC to data.

        Args:
            data: Input data to chunk

        Returns:
            HierarchicalChunkTree with chunk metadata at all levels
        """
        import hashlib

        # Level 1: Coarse-grained chunking
        level1_chunks = []
        level2_chunks = {}

        offset = 0
        for i, chunk in enumerate(self.level1_chunker.chunk_data(data)):
            chunk_hash = hashlib.sha256(chunk).hexdigest()
            metadata = ChunkMetadata(
                level=1,
                index=i,
                hash=chunk_hash,
                offset=offset,
                size=len(chunk),
            )
            level1_chunks.append(metadata)

            # Level 2: Fine-grained chunking within each Level 1 chunk
            children = []
            child_offset = 0
            for j, subchunk in enumerate(self.level2_chunker.chunk_data(chunk)):
                subchunk_hash = hashlib.sha256(subchunk).hexdigest()
                child_metadata = ChunkMetadata(
                    level=2,
                    index=j,
                    hash=subchunk_hash,
                    offset=child_offset,
                    size=len(subchunk),
                    parent_hash=chunk_hash,
                )
                children.append(child_metadata)
                child_offset += len(subchunk)

            level2_chunks[chunk_hash] = children
            offset += len(chunk)

        return HierarchicalChunkTree(
            level1_chunks=level1_chunks,
            level2_chunks=level2_chunks,
        )

    def get_deduplication_stats(self, tree: HierarchicalChunkTree) -> Dict:
        """
        Calculate deduplication statistics from hierarchical chunk tree.

        Args:
            tree: HierarchicalChunkTree from chunk_hierarchical

        Returns:
            Dictionary with deduplication metrics
        """
        # Count unique chunks at each level
        level1_hashes = [c.hash for c in tree.level1_chunks]
        level2_hashes = [c.hash for children in tree.level2_chunks.values() for c in children]

        level1_unique = len(set(level1_hashes))
        level2_unique = len(set(level2_hashes))

        level1_total = len(level1_hashes)
        level2_total = len(level2_hashes)

        return {
            "level1": {
                "total_chunks": level1_total,
                "unique_chunks": level1_unique,
                "dedup_ratio": 1.0 - (level1_unique / level1_total) if level1_total > 0 else 0,
            },
            "level2": {
                "total_chunks": level2_total,
                "unique_chunks": level2_unique,
                "dedup_ratio": 1.0 - (level2_unique / level2_total) if level2_total > 0 else 0,
            },
        }

    def find_shared_chunks(
        self, tree1: HierarchicalChunkTree, tree2: HierarchicalChunkTree
    ) -> Dict[str, List[str]]:
        """
        Find chunks shared between two hierarchical chunk trees.

        Args:
            tree1: First hierarchical chunk tree
            tree2: Second hierarchical chunk tree

        Returns:
            Dictionary mapping level to list of shared chunk hashes
        """
        tree1_l1_hashes = set(c.hash for c in tree1.level1_chunks)
        tree1_l2_hashes = set(
            c.hash for children in tree1.level2_chunks.values() for c in children
        )

        tree2_l1_hashes = set(c.hash for c in tree2.level1_chunks)
        tree2_l2_hashes = set(
            c.hash for children in tree2.level2_chunks.values() for c in children
        )

        return {
            "level1": list(tree1_l1_hashes & tree2_l1_hashes),
            "level2": list(tree1_l2_hashes & tree2_l2_hashes),
        }


def example_usage():
    """Example demonstrating hierarchical CDC usage."""
    print("=== Hierarchical CDC Example ===\n")

    # Create hierarchical chunker
    hcdc = HierarchicalCDC(
        level1_min_kb=64,    # 64KB minimum for coarse chunks
        level1_max_kb=1024,   # 1MB maximum for coarse chunks
        level1_avg_kb=256,    # 256KB target for coarse chunks
        level2_min_kb=4,      # 4KB minimum for fine chunks
        level2_max_kb=64,     # 64KB maximum for fine chunks
        level2_avg_kb=16,     # 16KB target for fine chunks
    )

    # Example 1: Single file chunking
    print("Example 1: Single file hierarchical chunking")
    data = b"The quick brown fox jumps over the lazy dog. " * 10000
    tree = hcdc.chunk_hierarchical(data)

    print(f"Level 1 chunks: {len(tree.level1_chunks)}")
    print(f"Level 2 chunks: {sum(len(c) for c in tree.level2_chunks.values())}")

    stats = hcdc.get_deduplication_stats(tree)
    print(f"\nDeduplication stats:")
    print(f"  Level 1: {stats['level1']['unique_chunks']}/{stats['level1']['total_chunks']} unique ({stats['level1']['dedup_ratio']:.1%} dedup)")
    print(f"  Level 2: {stats['level2']['unique_chunks']}/{stats['level2']['total_chunks']} unique ({stats['level2']['dedup_ratio']:.1%} dedup)")

    # Example 2: Compare two similar files
    print("\n\nExample 2: Comparing similar files")
    data1 = b"The quick brown fox jumps over the lazy dog. " * 10000
    data2 = b"The quick brown fox jumps over the lazy cat. " * 10000

    tree1 = hcdc.chunk_hierarchical(data1)
    tree2 = hcdc.chunk_hierarchical(data2)

    shared = hcdc.find_shared_chunks(tree1, tree2)
    print(f"Shared Level 1 chunks: {len(shared['level1'])}")
    print(f"Shared Level 2 chunks: {len(shared['level2'])}")

    # Example 3: Incremental update scenario
    print("\n\nExample 3: Incremental update (version control)")
    base_version = b"Base content " * 10000
    updated_version = b"Base content " * 10000 + b" with new changes"

    base_tree = hcdc.chunk_hierarchical(base_version)
    updated_tree = hcdc.chunk_hierarchical(updated_version)

    shared = hcdc.find_shared_chunks(base_tree, updated_tree)
    print(f"Chunks shared with base version:")
    print(f"  Level 1: {len(shared['level1'])}")
    print(f"  Level 2: {len(shared['level2'])}")

    # Calculate storage savings
    base_size = len(base_version)
    updated_size = len(updated_version)
    shared_l2_size = sum(
        c.size
        for children in base_tree.level2_chunks.values()
        for c in children
        if c.hash in set(shared['level2'])
    )
    savings = (shared_l2_size / updated_size) * 100
    print(f"  Estimated storage savings: {savings:.1f}%")


if __name__ == "__main__":
    example_usage()
