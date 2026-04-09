"""
TFP Metadata Layer - Tag Overlay Index for Decentralized Discovery

This module provides:
- Bloom filter compression for metadata broadcasts
- Merkle DAG construction for tag indices
- Tag-based content discovery without central indexers
"""

from .bloom_filter import BloomFilter
from .tag_index import TagOverlayIndex, TagEntry

__all__ = ['BloomFilter', 'TagOverlayIndex', 'TagEntry']
