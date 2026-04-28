# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for TemplateDescriptor implementation.
"""

import pytest

from tfp_transport.template_descriptor import TemplateDescriptor, create_cdc_template


class TestTemplateDescriptor:
    """Test TemplateDescriptor implementation."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        template = TemplateDescriptor()
        assert template.schema_version == "tfp/template/v1"
        assert template.content_type == "application/octet-stream"
        assert template.chunking is not None
        assert template.semantic_index is not None
        assert template.erasure_coding is not None
        assert template.integrity == {}
        assert template.metadata == {}

    def test_init_custom(self):
        """Test initialization with custom values."""
        template = TemplateDescriptor(
            content_type="text/markdown",
            chunking={"strategy": "fastcdc"},
        )
        assert template.content_type == "text/markdown"
        assert template.chunking["strategy"] == "fastcdc"

    def test_set_content_hash(self):
        """Test setting content hash."""
        template = TemplateDescriptor()
        content = b"test content"
        template.set_content_hash(content)
        assert "content_hash" in template.integrity
        assert len(template.integrity["content_hash"]) == 64  # SHA-256 hex

    def test_set_chunk_hashes(self):
        """Test setting chunk hashes."""
        template = TemplateDescriptor()
        hashes = ["hash1", "hash2", "hash3"]
        template.set_chunk_hashes(hashes)
        assert template.integrity["chunk_hashes"] == hashes

    def test_set_template_signature(self):
        """Test setting template signature."""
        template = TemplateDescriptor()
        signature = "sig123"
        template.set_template_signature(signature)
        assert template.integrity["template_signature"] == signature

    def test_compute_template_hash(self):
        """Test computing template hash."""
        template = TemplateDescriptor(content_type="text/plain")
        hash1 = template.compute_template_hash()
        hash2 = template.compute_template_hash()
        assert hash1 == hash2  # Deterministic
        assert len(hash1) == 64  # SHA-256 hex

    def test_to_dict_from_dict(self):
        """Test serialization to/from dict."""
        template = TemplateDescriptor(content_type="text/markdown")
        template.set_content_hash(b"test")
        
        data = template.to_dict()
        assert isinstance(data, dict)
        assert data["content_type"] == "text/markdown"
        
        restored = TemplateDescriptor.from_dict(data)
        assert restored.content_type == "text/markdown"
        assert restored.integrity == template.integrity

    def test_to_json_from_json(self):
        """Test serialization to/from JSON."""
        template = TemplateDescriptor(content_type="application/json")
        template.set_content_hash(b"test")
        
        json_str = template.to_json()
        assert isinstance(json_str, str)
        
        restored = TemplateDescriptor.from_json(json_str)
        assert restored.content_type == "application/json"

    def test_validate_lightweight_pass(self):
        """Test lightweight validation with valid template."""
        template = TemplateDescriptor()
        is_valid, errors = template.validate_lightweight()
        assert is_valid
        assert len(errors) == 0

    def test_validate_lightweight_missing_schema_version(self):
        """Test validation fails without schema version."""
        template = TemplateDescriptor(schema_version="")
        is_valid, errors = template.validate_lightweight()
        assert not is_valid
        assert "schema_version is required" in errors

    def test_validate_lightweight_invalid_chunk_sizes(self):
        """Test validation fails with invalid chunk sizes."""
        template = TemplateDescriptor(
            chunking={
                "params": {
                    "min_chunk_size": 65536,
                    "max_chunk_size": 4096,
                }
            }
        )
        is_valid, errors = template.validate_lightweight()
        assert not is_valid
        assert any("min_chunk_size" in e for e in errors)

    def test_validate_lightweight_invalid_lexicon_path(self):
        """Test validation fails with invalid lexicon path."""
        template = TemplateDescriptor(
            semantic_index={"lexicon_path": "invalid/path"}
        )
        is_valid, errors = template.validate_lightweight()
        assert not is_valid
        assert any("lexicon_path" in e for e in errors)

    def test_validate_lightweight_invalid_redundancy(self):
        """Test validation fails with invalid redundancy."""
        template = TemplateDescriptor(
            erasure_coding={"redundancy": 1.5}
        )
        is_valid, errors = template.validate_lightweight()
        assert not is_valid
        assert any("redundancy" in e for e in errors)


class TestCreateCDCTemplate:
    """Test create_cdc_template convenience function."""

    def test_create_default(self):
        """Test creating template with defaults."""
        template = create_cdc_template()
        assert template.content_type == "application/octet-stream"
        assert template.chunking["strategy"] == "fastcdc"
        assert template.chunking["params"]["min_chunk_size"] == 4096
        assert template.chunking["params"]["max_chunk_size"] == 65536

    def test_create_custom_params(self):
        """Test creating template with custom parameters."""
        template = create_cdc_template(
            content_type="text/markdown",
            min_chunk_kb=8,
            max_chunk_kb=128,
            avg_chunk_kb=32,
            lexicon_path="/education/health",
            tags=["offline-first", "health"],
        )
        assert template.content_type == "text/markdown"
        assert template.chunking["params"]["min_chunk_size"] == 8192
        assert template.chunking["params"]["max_chunk_size"] == 131072
        assert template.chunking["params"]["expected_chunk_size"] == 32768
        assert template.semantic_index["lexicon_path"] == "/education/health"
        assert template.semantic_index["tags"] == ["offline-first", "health"]
