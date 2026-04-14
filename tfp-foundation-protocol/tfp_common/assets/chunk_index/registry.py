# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Chunk Registry - Maps chunk_id → content_hash → category

Central registry for all chunks in the TFP ecosystem. Provides:
- Chunk ID generation and validation
- Content hash computation (SHA3-256)
- Category-based organization
- Merkle root computation for verification
- Serialization/deserialization
"""

import hashlib
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .categories import validate_category


@dataclass
class ChunkEntry:
    """
    Represents a single chunk in the registry.

    Attributes:
        chunk_id: Unique identifier for the chunk (alphanumeric + underscore)
        content_hash: SHA3-256 hash of the chunk data
        category: Category name (texture, layout, etc.)
        size_bytes: Size of the chunk data in bytes
        version: Version number (increments on updates)
        tags: Optional list of tags for discovery
        metadata: Additional metadata dictionary
    """

    chunk_id: str
    content_hash: str
    category: str
    size_bytes: int
    version: int = 1
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def is_valid_chunk_id(chunk_id: str) -> bool:
        """
        Validate chunk ID format.

        Rules:
        - Alphanumeric characters only (a-z, A-Z, 0-9)
        - Underscores allowed
        - No spaces or special characters
        - Non-empty

        Args:
            chunk_id: The chunk ID to validate

        Returns:
            True if valid, False otherwise
        """
        if not chunk_id:
            return False
        return bool(re.match(r"^[a-zA-Z0-9_]+$", chunk_id))

    @staticmethod
    def is_valid_content_hash(content_hash: str) -> bool:
        """
        Validate content hash format (SHA3-256 hex string).

        Args:
            content_hash: The hash to validate

        Returns:
            True if valid 64-char hex string, False otherwise
        """
        if not content_hash or len(content_hash) != 64:
            return False
        try:
            int(content_hash, 16)
            return True
        except ValueError:
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize entry to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "category": self.category,
            "size_bytes": self.size_bytes,
            "version": self.version,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkEntry":
        """Deserialize entry from dictionary."""
        return cls(
            chunk_id=data["chunk_id"],
            content_hash=data["content_hash"],
            category=data["category"],
            size_bytes=data["size_bytes"],
            version=data.get("version", 1),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


class ChunkRegistry:
    """
    Central registry for all chunks.

    Thread-safe registry that maps chunk IDs to content hashes and categories.
    Supports:
    - Registration with auto-generated or custom IDs
    - Lookup by ID, hash, category, or tag
    - Merkle root computation for integrity verification
    - Serialization/deserialization
    - Statistics and querying
    """

    def __init__(self):
        """Initialize an empty chunk registry."""
        self._chunks: Dict[str, ChunkEntry] = OrderedDict()
        self._hash_to_id: Dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def count(self) -> int:
        """Get total number of chunks in registry."""
        with self._lock:
            return len(self._chunks)

    def register(
        self,
        chunk_data: bytes,
        category: str,
        chunk_id_hint: Optional[str] = None,
        allow_update: bool = False,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register a new chunk in the registry.

        Args:
            chunk_data: Raw chunk data bytes
            category: Category name (must be valid)
            chunk_id_hint: Optional hint for chunk ID (auto-generated if None)
            allow_update: If True, update existing chunk with same hint
            tags: Optional list of tags for discovery
            metadata: Optional additional metadata

        Returns:
            The chunk ID (either generated or from hint)

        Raises:
            ValueError: If category is invalid or chunk_id format is invalid
        """
        # Validate category
        if not validate_category(category):
            raise ValueError(f"Invalid category: '{category}'")

        # Compute content hash
        content_hash = hashlib.sha3_256(chunk_data).hexdigest()
        size_bytes = len(chunk_data)

        with self._lock:
            # Check if this hash already exists
            if content_hash in self._hash_to_id:
                existing_id = self._hash_to_id[content_hash]
                return existing_id  # Return existing ID for duplicate data

            # Generate or validate chunk ID
            if chunk_id_hint:
                if not ChunkEntry.is_valid_chunk_id(chunk_id_hint):
                    raise ValueError(f"Invalid chunk_id format: '{chunk_id_hint}'")

                # Check if ID already exists
                if chunk_id_hint in self._chunks:
                    if allow_update:
                        # Update existing entry
                        existing = self._chunks[chunk_id_hint]
                        updated_entry = ChunkEntry(
                            chunk_id=chunk_id_hint,
                            content_hash=content_hash,
                            category=category,
                            size_bytes=size_bytes,
                            version=existing.version + 1,
                            tags=tags or existing.tags,
                            metadata=metadata or existing.metadata,
                        )
                        # Remove old hash mapping
                        old_hash = existing.content_hash
                        if (
                            old_hash in self._hash_to_id
                            and self._hash_to_id[old_hash] == chunk_id_hint
                        ):
                            del self._hash_to_id[old_hash]

                        self._chunks[chunk_id_hint] = updated_entry
                        self._hash_to_id[content_hash] = chunk_id_hint
                        return chunk_id_hint
                    else:
                        raise ValueError(
                            f"Chunk ID '{chunk_id_hint}' already exists. Use allow_update=True to update."
                        )

                chunk_id = chunk_id_hint
            else:
                # Auto-generate unique ID
                base_id = f"chunk_{uuid.uuid4().hex[:8]}"
                chunk_id = base_id
                counter = 0
                while chunk_id in self._chunks:
                    counter += 1
                    chunk_id = f"chunk_{uuid.uuid4().hex[:8]}_{counter}"

            # Create entry
            entry = ChunkEntry(
                chunk_id=chunk_id,
                content_hash=content_hash,
                category=category.lower(),
                size_bytes=size_bytes,
                version=1,
                tags=tags or [],
                metadata=metadata or {},
            )

            # Register
            self._chunks[chunk_id] = entry
            self._hash_to_id[content_hash] = chunk_id

            return chunk_id

    def get_by_id(self, chunk_id: str) -> Optional[ChunkEntry]:
        """
        Retrieve chunk entry by ID.

        Args:
            chunk_id: The chunk ID to look up

        Returns:
            ChunkEntry if found, None otherwise
        """
        with self._lock:
            return self._chunks.get(chunk_id)

    def get_by_hash(self, content_hash: str) -> Optional[ChunkEntry]:
        """
        Retrieve chunk entry by content hash.

        Args:
            content_hash: SHA3-256 hash to look up

        Returns:
            ChunkEntry if found, None otherwise
        """
        with self._lock:
            chunk_id = self._hash_to_id.get(content_hash)
            if chunk_id:
                return self._chunks.get(chunk_id)
            return None

    def get_by_category(self, category: str) -> List[ChunkEntry]:
        """
        Get all chunks in a category.

        Args:
            category: Category name to filter by

        Returns:
            List of ChunkEntry objects in the category
        """
        with self._lock:
            category_lower = category.lower()
            return [
                entry
                for entry in self._chunks.values()
                if entry.category == category_lower
            ]

    def query_by_tag(self, tag: str) -> List[ChunkEntry]:
        """
        Query chunks by tag.

        Args:
            tag: Tag to search for

        Returns:
            List of ChunkEntry objects with the tag
        """
        with self._lock:
            tag_lower = tag.lower()
            return [
                entry
                for entry in self._chunks.values()
                if tag_lower in [t.lower() for t in entry.tags]
            ]

    def delete(self, chunk_id: str) -> None:
        """
        Delete a chunk from the registry.

        Args:
            chunk_id: ID of chunk to delete

        Raises:
            KeyError: If chunk doesn't exist
        """
        with self._lock:
            if chunk_id not in self._chunks:
                raise KeyError(f"Chunk '{chunk_id}' not found")

            entry = self._chunks[chunk_id]
            # Remove hash mapping
            if entry.content_hash in self._hash_to_id:
                del self._hash_to_id[entry.content_hash]

            # Remove chunk
            del self._chunks[chunk_id]

    def get_all_chunks(self) -> List[ChunkEntry]:
        """Get all chunk entries."""
        with self._lock:
            return list(self._chunks.values())

    def get_all_chunk_ids(self) -> List[str]:
        """Get all chunk IDs."""
        with self._lock:
            return list(self._chunks.keys())

    def compute_merkle_root(self) -> str:
        """
        Compute Merkle root of all chunks for integrity verification.

        Returns:
            SHA3-256 hex string of the Merkle root
        """
        with self._lock:
            if not self._chunks:
                # Empty registry has a well-defined root
                return hashlib.sha3_256(b"empty_registry").hexdigest()

            # Sort chunks by ID for deterministic ordering
            sorted_ids = sorted(self._chunks.keys())

            # Build leaf hashes
            leaves = [
                hashlib.sha3_256(
                    f"{chunk_id}:{self._chunks[chunk_id].content_hash}".encode()
                ).hexdigest()
                for chunk_id in sorted_ids
            ]

            # Build Merkle tree
            while len(leaves) > 1:
                if len(leaves) % 2 == 1:
                    leaves.append(leaves[-1])  # Duplicate last if odd

                new_level = []
                for i in range(0, len(leaves), 2):
                    combined = leaves[i] + leaves[i + 1]
                    parent_hash = hashlib.sha3_256(combined.encode()).hexdigest()
                    new_level.append(parent_hash)

                leaves = new_level

            return leaves[0]

    def to_dict(self) -> Dict[str, Any]:
        """
        Export entire registry to dictionary.

        Returns:
            Dictionary representation of the registry
        """
        with self._lock:
            return {
                "chunks": [entry.to_dict() for entry in self._chunks.values()],
                "merkle_root": self.compute_merkle_root(),
                "count": len(self._chunks),
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkRegistry":
        """
        Import registry from dictionary.

        Args:
            data: Dictionary from to_dict()

        Returns:
            Restored ChunkRegistry instance
        """
        registry = cls()

        with registry._lock:
            for chunk_data in data.get("chunks", []):
                entry = ChunkEntry.from_dict(chunk_data)
                registry._chunks[entry.chunk_id] = entry
                registry._hash_to_id[entry.content_hash] = entry.chunk_id

        return registry

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            by_category: Dict[str, int] = {}
            total_size = 0

            for entry in self._chunks.values():
                cat = entry.category
                by_category[cat] = by_category.get(cat, 0) + 1
                total_size += entry.size_bytes

            return {
                "total_chunks": len(self._chunks),
                "by_category": by_category,
                "total_size_bytes": total_size,
                "merkle_root": self.compute_merkle_root(),
            }
