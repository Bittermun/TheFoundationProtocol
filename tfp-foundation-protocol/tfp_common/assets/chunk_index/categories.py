# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Chunk Categories - Predefined categories for chunk classification.

Categories organize chunks by type: texture, layout, audio_pattern, code_block, text_delta, etc.
"""

import dataclasses
from typing import Dict


@dataclasses.dataclass
class ChunkCategory:
    """Definition of a chunk category."""

    name: str
    description: str
    mime_type_prefix: str = ""
    default_compression: str = "raptorq"


# Predefined standard categories
CHUNK_CATEGORIES: Dict[str, ChunkCategory] = {
    "texture": ChunkCategory(
        name="texture",
        description="Visual texture elements (gradients, patterns, images)",
        mime_type_prefix="image/",
        default_compression="raptorq",
    ),
    "layout": ChunkCategory(
        name="layout",
        description="Structural layout templates (UI frames, page structures)",
        mime_type_prefix="application/layout+",
        default_compression="raptorq",
    ),
    "audio_pattern": ChunkCategory(
        name="audio_pattern",
        description="Audio segments and sound patterns",
        mime_type_prefix="audio/",
        default_compression="raptorq",
    ),
    "code_block": ChunkCategory(
        name="code_block",
        description="Executable code snippets and functions",
        mime_type_prefix="text/x-",
        default_compression="raptorq",
    ),
    "text_delta": ChunkCategory(
        name="text_delta",
        description="Text content differences and deltas",
        mime_type_prefix="text/",
        default_compression="raptorq",
    ),
    "video_segment": ChunkCategory(
        name="video_segment",
        description="Video clips and animation segments",
        mime_type_prefix="video/",
        default_compression="raptorq",
    ),
    "metadata": ChunkCategory(
        name="metadata",
        description="Metadata and configuration chunks",
        mime_type_prefix="application/json",
        default_compression="raptorq",
    ),
    "font_glyph": ChunkCategory(
        name="font_glyph",
        description="Font glyphs and typography elements",
        mime_type_prefix="font/",
        default_compression="raptorq",
    ),
    "icon": ChunkCategory(
        name="icon",
        description="Icon graphics and symbols",
        mime_type_prefix="image/icon+",
        default_compression="raptorq",
    ),
    "3d_model": ChunkCategory(
        name="3d_model",
        description="3D model components and meshes",
        mime_type_prefix="model/",
        default_compression="raptorq",
    ),
}


def get_category_by_name(name: str) -> ChunkCategory | None:
    """
    Retrieve a category by its name.

    Args:
        name: Category name (case-insensitive)

    Returns:
        ChunkCategory if found, None otherwise
    """
    return CHUNK_CATEGORIES.get(name.lower())


def validate_category(name: str) -> bool:
    """
    Validate if a category name exists.

    Args:
        name: Category name to validate

    Returns:
        True if valid category, False otherwise
    """
    if not name or not isinstance(name, str):
        return False
    return name.lower() in CHUNK_CATEGORIES


def register_custom_category(
    name: str,
    description: str,
    mime_type_prefix: str = "",
    default_compression: str = "raptorq",
) -> ChunkCategory:
    """
    Register a custom category at runtime.

    Args:
        name: Unique category name
        description: Human-readable description
        mime_type_prefix: MIME type prefix for this category
        default_compression: Default compression algorithm

    Returns:
        The created ChunkCategory

    Raises:
        ValueError: If category name already exists
    """
    name_lower = name.lower()
    if name_lower in CHUNK_CATEGORIES:
        raise ValueError(f"Category '{name}' already exists")

    category = ChunkCategory(
        name=name_lower,
        description=description,
        mime_type_prefix=mime_type_prefix,
        default_compression=default_compression,
    )
    CHUNK_CATEGORIES[name_lower] = category
    return category


def get_all_categories() -> list[str]:
    """Get list of all registered category names."""
    return list(CHUNK_CATEGORIES.keys())
