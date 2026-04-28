# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Lightweight TemplateDescriptor for Content-Defined Chunking metadata.

Serves as optional publish-time metadata for discovery and deduplication.
Complements the existing Recipe system (for reconstruction) by providing
publishing-layer metadata.

This is a lightweight dict-based implementation without JSON Schema validation
for MVP simplicity. Can be extended with schema validation later if needed.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TemplateDescriptor:
    """
    Lightweight template descriptor for CDC metadata.

    Provides self-describing content metadata for:
    - Chunking strategy information
    - Semantic indexing hints
    - Integrity verification
    - Discovery metadata

    This is optional metadata for the publishing layer, separate from
    the Recipe system used for reconstruction.
    """

    schema_version: str = "tfp/template/v1"
    content_type: str = "application/octet-stream"
    chunking: Dict[str, Any] = None
    semantic_index: Dict[str, Any] = None
    erasure_coding: Dict[str, Any] = None
    integrity: Dict[str, Any] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        """Set default values for nested dicts."""
        if self.chunking is None:
            self.chunking = self._default_chunking()
        if self.semantic_index is None:
            self.semantic_index = self._default_semantic_index()
        if self.erasure_coding is None:
            self.erasure_coding = self._default_erasure_coding()
        if self.integrity is None:
            self.integrity = {}
        if self.metadata is None:
            self.metadata = {}

    @staticmethod
    def _default_chunking() -> Dict[str, Any]:
        """Default chunking parameters."""
        return {
            "strategy": "fastcdc",
            "params": {
                "min_chunk_size": 4096,
                "max_chunk_size": 65536,
                "expected_chunk_size": 16384,
                "mask_bits": 21,
                "zero_padding": 5,
            },
        }

    @staticmethod
    def _default_semantic_index() -> Dict[str, Any]:
        """Default semantic index parameters."""
        return {
            "lexicon_path": "/general",
            "tags": [],
            "language": "en",
        }

    @staticmethod
    def _default_erasure_coding() -> Dict[str, Any]:
        """Default erasure coding parameters."""
        return {
            "algorithm": "raptorq",
            "redundancy": 0.1,
            "shard_size": 262144,
        }

    def set_content_hash(self, content: bytes) -> None:
        """
        Set content hash for integrity verification.

        Args:
            content: Raw content bytes
        """
        self.integrity["content_hash"] = hashlib.sha256(content).hexdigest()

    def set_chunk_hashes(self, chunk_hashes: List[str]) -> None:
        """
        Set CDC chunk hashes for deduplication metadata.

        Args:
            chunk_hashes: List of SHA-256 hashes for each chunk
        """
        self.integrity["chunk_hashes"] = chunk_hashes

    def set_template_signature(self, signature: str) -> None:
        """
        Set template signature for verification.

        Args:
            signature: HMAC-SHA-256 signature of template + content_hash
        """
        self.integrity["template_signature"] = signature

    def compute_template_hash(self) -> str:
        """
        Compute hash of the template descriptor itself.

        Returns:
            SHA-256 hash of normalized template JSON
        """
        normalized = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateDescriptor":
        """Deserialize from dictionary with validation."""
        template = cls(**data)
        is_valid, errors = template.validate_lightweight()
        if not is_valid:
            raise ValueError(f"Invalid template descriptor: {errors}")
        return template

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "TemplateDescriptor":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def validate_lightweight(self) -> tuple[bool, List[str]]:
        """
        Lightweight validation without JSON Schema.

        Performs basic sanity checks on the template structure.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        if not self.schema_version:
            errors.append("schema_version is required")
        if not self.content_type:
            errors.append("content_type is required")

        # Validate chunking params
        if self.chunking:
            params = self.chunking.get("params", {})
            min_size = params.get("min_chunk_size", 0)
            max_size = params.get("max_chunk_size", 0)
            if min_size >= max_size:
                errors.append("min_chunk_size must be less than max_chunk_size")

        # Validate lexicon path format
        if self.semantic_index:
            lexicon_path = self.semantic_index.get("lexicon_path", "")
            if lexicon_path and not lexicon_path.startswith("/"):
                errors.append("lexicon_path must start with /")

        # Validate erasure coding redundancy
        if self.erasure_coding:
            redundancy = self.erasure_coding.get("redundancy", 0)
            if not (0 <= redundancy <= 1):
                errors.append("redundancy must be between 0 and 1")

        return len(errors) == 0, errors


def create_cdc_template(
    content_type: str = "application/octet-stream",
    min_chunk_kb: int = 4,
    max_chunk_kb: int = 64,
    avg_chunk_kb: int = 16,
    lexicon_path: str = "/general",
    tags: List[str] = None,
) -> TemplateDescriptor:
    """
    Create a TemplateDescriptor configured for CDC.

    Convenience function for creating a template with CDC parameters.

    Args:
        content_type: MIME type of content
        min_chunk_kb: Minimum chunk size in KB
        max_chunk_kb: Maximum chunk size in KB
        avg_chunk_kb: Target average chunk size in KB
        lexicon_path: Semantic lexicon path
        tags: Optional tags for discovery

    Returns:
        Configured TemplateDescriptor
    """
    template = TemplateDescriptor(
        content_type=content_type,
        chunking={
            "strategy": "fastcdc",
            "params": {
                "min_chunk_size": min_chunk_kb * 1024,
                "max_chunk_size": max_chunk_kb * 1024,
                "expected_chunk_size": avg_chunk_kb * 1024,
                "mask_bits": 21,
                "zero_padding": 5,
            },
        },
        semantic_index={
            "lexicon_path": lexicon_path,
            "tags": tags or [],
            "language": "en",
        },
    )
    return template


if __name__ == "__main__":
    # Demo usage
    print("=== TemplateDescriptor Demo ===\n")

    # Create a template for educational content
    template = create_cdc_template(
        content_type="text/markdown",
        min_chunk_kb=4,
        max_chunk_kb=64,
        avg_chunk_kb=16,
        lexicon_path="/education/health",
        tags=["offline-first", "health"],
    )

    print(f"Schema version: {template.schema_version}")
    print(f"Content type: {template.content_type}")
    print(f"Chunking strategy: {template.chunking['strategy']}")
    print(f"Lexicon path: {template.semantic_index['lexicon_path']}")
    print(f"Tags: {template.semantic_index['tags']}")

    # Set content hash
    test_content = b"Educational content about health."
    template.set_content_hash(test_content)
    print(f"\nContent hash: {template.integrity['content_hash']}")

    # Validate
    is_valid, errors = template.validate_lightweight()
    print(f"\nValidation: {'PASS' if is_valid else 'FAIL'}")
    if errors:
        for error in errors:
            print(f"  - {error}")

    # Serialize
    print(f"\nTemplate hash: {template.compute_template_hash()}")
    print(f"\nJSON output (first 200 chars):")
    print(template.to_json()[:200] + "...")
