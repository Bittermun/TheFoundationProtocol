"""
Chunk Index Module - Maps chunk_id → content_hash → category

This module provides the chunk registry system for TFP, enabling:
- Chunk identification and categorization
- Content-addressable storage references
- Merkle tree verification
- Tag-based discovery
"""

from .categories import (
    CHUNK_CATEGORIES,
    ChunkCategory,
    get_category_by_name,
    validate_category,
    register_custom_category,
    get_all_categories,
)

from .registry import (
    ChunkRegistry,
    ChunkEntry,
)

__all__ = [
    # Categories
    'CHUNK_CATEGORIES',
    'ChunkCategory',
    'get_category_by_name',
    'validate_category',
    'register_custom_category',
    'get_all_categories',
    # Registry
    'ChunkRegistry',
    'ChunkEntry',
]
