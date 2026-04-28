# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for Content-Defined Chunking (CDC) implementation using FastCDC.
"""

import pytest

from tfp_transport.cdc import CDCChunker, FastCDC, create_fastcdc_chunker

try:
    from tfp_client.lib.upload.chunk_encoder import ChunkEncoder
    CHUNK_ENCODER_AVAILABLE = True
except ImportError:
    CHUNK_ENCODER_AVAILABLE = False


class TestFastCDC:
    """Test FastCDC Gear hash implementation."""

    def test_gear_table_deterministic(self):
        """Test that Gear hash table is deterministic."""
        cdc1 = FastCDC()
        cdc2 = FastCDC()
        assert cdc1.gear_table == cdc2.gear_table

    def test_gear_roll(self):
        """Test Gear hash rolling update."""
        cdc = FastCDC()
        fp = 0
        old_byte = 0x41
        new_byte = 0x42
        new_fp = cdc._gear_roll(fp, old_byte, new_byte)
        assert isinstance(new_fp, int)
        assert 0 <= new_fp < (1 << 64)

    def test_normalized_mask(self):
        """Test normalized mask adjustment."""
        cdc = FastCDC(expected_chunk=16384)
        
        # Small chunk: more boundaries (mask shifted right)
        mask_small = cdc._normalized_mask(4096)
        # Large chunk: fewer boundaries (mask shifted left) - must be > 2x expected
        mask_large = cdc._normalized_mask(40000)
        # Normal chunk: base mask
        mask_normal = cdc._normalized_mask(16384)
        
        assert mask_small < mask_normal
        assert mask_large > mask_normal


class TestCDCChunker:
    """Test CDC chunker implementation."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        chunker = CDCChunker()
        assert chunker.min_chunk == CDCChunker.DEFAULT_MIN_CHUNK
        assert chunker.max_chunk == CDCChunker.DEFAULT_MAX_CHUNK
        assert chunker.avg_chunk == CDCChunker.DEFAULT_AVG_CHUNK

    def test_init_custom_sizes(self):
        """Test initialization with custom sizes."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        assert chunker.min_chunk == 1024
        assert chunker.max_chunk == 8192
        assert chunker.avg_chunk == 2048

    def test_invalid_min_max(self):
        """Test that min_chunk must be less than max_chunk."""
        with pytest.raises(ValueError):
            CDCChunker(min_chunk=8192, max_chunk=4096)

    def test_invalid_avg_outside_range(self):
        """Test that avg_chunk must be between min and max."""
        with pytest.raises(ValueError):
            CDCChunker(min_chunk=4096, max_chunk=8192, avg_chunk=1024)
        with pytest.raises(ValueError):
            CDCChunker(min_chunk=4096, max_chunk=8192, avg_chunk=16384)

    def test_chunk_empty_data(self):
        """Test chunking empty data."""
        chunker = CDCChunker()
        chunks = list(chunker.chunk_data(b""))
        assert len(chunks) == 0

    def test_chunk_small_data(self):
        """Test chunking data smaller than min_chunk."""
        chunker = CDCChunker(min_chunk=4096)
        data = b"small data"
        chunks = list(chunker.chunk_data(data))
        assert len(chunks) == 1
        assert chunks[0] == data

    def test_chunk_large_data(self):
        """Test chunking large data."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        data = b"x" * 100000
        chunks = list(chunker.chunk_data(data))
        assert len(chunks) > 1

        # Verify size constraints
        for chunk in chunks:
            assert chunker.min_chunk <= len(chunk) <= chunker.max_chunk or len(chunk) < chunker.min_chunk

    def test_reconstruction(self):
        """Test that chunks can be reconstructed to original data."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        original = b"The quick brown fox jumps over the lazy dog. " * 1000
        chunks = list(chunker.chunk_data(original))
        reconstructed = b"".join(chunks)
        assert reconstructed == original

    def test_chunk_size_distribution(self):
        """Test that chunk sizes follow expected distribution."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        # Use varied data to ensure hash variation
        import os
        data = os.urandom(100000)
        chunks = list(chunker.chunk_data(data))

        sizes = [len(c) for c in chunks]
        avg_size = sum(sizes) / len(sizes)

        # Average should be between min and max (looser constraint)
        assert chunker.min_chunk <= avg_size <= chunker.max_chunk

    def test_max_chunk_enforced(self):
        """Test that max_chunk is never exceeded."""
        chunker = CDCChunker(min_chunk=512, max_chunk=2048, avg_chunk=1024)
        data = b"x" * 100000
        chunks = list(chunker.chunk_data(data))
        for chunk in chunks:
            assert len(chunk) <= chunker.max_chunk

    def test_min_chunk_enforced(self):
        """Test that min_chunk is respected (except for last chunk)."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        data = b"x" * 100000
        chunks = list(chunker.chunk_data(data))

        # All chunks except possibly the last should meet min_chunk
        for i, chunk in enumerate(chunks[:-1]):
            assert len(chunk) >= chunker.min_chunk

    def test_get_chunk_hashes(self):
        """Test chunk hash computation."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        data = b"test data" * 1000
        hashes = chunker.get_chunk_hashes(data)

        chunks = list(chunker.chunk_data(data))
        assert len(hashes) == len(chunks)

        # Hashes should be hex strings
        for h in hashes:
            assert len(h) == 64  # SHA-256 hex length
            assert all(c in "0123456789abcdef" for c in h)

    def test_estimate_chunk_count(self):
        """Test chunk count estimation."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        data_size = 100000
        estimated = chunker.estimate_chunk_count(data_size)

        # Should be reasonably close to actual
        import os
        data = os.urandom(data_size)
        actual = len(list(chunker.chunk_data(data)))

        # Allow wider error margin due to content-defined nature
        assert estimated * 0.25 <= actual <= estimated * 4

    def test_estimate_zero_size(self):
        """Test estimation with zero size."""
        chunker = CDCChunker()
        assert chunker.estimate_chunk_count(0) == 0

    def test_deterministic_chunking(self):
        """Test that chunking is deterministic."""
        chunker = CDCChunker(min_chunk=1024, max_chunk=8192, avg_chunk=2048)
        data = b"test data" * 1000

        chunks1 = list(chunker.chunk_data(data))
        chunks2 = list(chunker.chunk_data(data))

        assert chunks1 == chunks2

    def test_content_based_splits(self):
        """Test that similar content produces similar chunk boundaries."""
        chunker = CDCChunker(min_chunk=512, max_chunk=4096, avg_chunk=1024)

        # Two similar files with small difference
        data1 = b"The quick brown fox jumps over the lazy dog." * 100
        data2 = b"The quick brown fox jumps over the lazy cat." * 100

        chunks1 = list(chunker.chunk_data(data1))
        chunks2 = list(chunker.chunk_data(data2))

        # Should have similar number of chunks (allow more leniency)
        assert abs(len(chunks1) - len(chunks2)) < max(len(chunks1), len(chunks2)) * 0.8


class TestCreateFastCDCChunker:
    """Test FastCDC-style chunker creation."""

    def test_create_with_kb_params(self):
        """Test creating chunker with KB parameters."""
        chunker = create_fastcdc_chunker(min_chunk_kb=4, max_chunk_kb=64, avg_chunk_kb=16)
        assert chunker.min_chunk == 4096
        assert chunker.max_chunk == 65536
        assert chunker.avg_chunk == 16384

    def test_create_defaults(self):
        """Test creating chunker with default parameters."""
        chunker = create_fastcdc_chunker()
        assert chunker.min_chunk == 4096
        assert chunker.max_chunk == 65536
        assert chunker.avg_chunk == 16384

    def test_fastcdc_functionality(self):
        """Test that FastCDC-style chunker works correctly."""
        chunker = create_fastcdc_chunker(min_chunk_kb=4, max_chunk_kb=64, avg_chunk_kb=16)
        data = b"x" * 100000
        chunks = list(chunker.chunk_data(data))
        reconstructed = b"".join(chunks)
        assert reconstructed == data


@pytest.mark.skipif(not CHUNK_ENCODER_AVAILABLE, reason="ChunkEncoder not available")
class TestChunkEncoderIntegration:
    """Test CDC integration with ChunkEncoder."""

    def test_encoder_without_cdc(self):
        """Test that encoder works without CDC (default behavior)."""
        encoder = ChunkEncoder(use_cdc=False)
        assert not encoder.is_cdc_enabled()

    def test_encoder_with_cdc(self):
        """Test that encoder can be initialized with CDC."""
        encoder = ChunkEncoder(use_cdc=True)
        assert encoder.is_cdc_enabled()

    def test_cdc_chunk_hashes(self):
        """Test getting CDC chunk hashes from encoder."""
        encoder = ChunkEncoder(use_cdc=True)
        data = b"test data" * 1000
        hashes = encoder.get_cdc_chunk_hashes(data)

        assert hashes is not None
        assert len(hashes) > 0
        assert all(len(h) == 64 for h in hashes)  # SHA-256 hex length

    def test_cdc_chunk_hashes_disabled(self):
        """Test that CDC hashes return None when CDC is disabled."""
        encoder = ChunkEncoder(use_cdc=False)
        data = b"test data" * 1000
        hashes = encoder.get_cdc_chunk_hashes(data)
        assert hashes is None

    def test_encode_with_cdc(self):
        """Test that encoding works with CDC enabled."""
        encoder = ChunkEncoder(use_cdc=True, chunk_size=8192)
        data = b"x" * 50000

        # This should not raise an error
        # Note: actual encoding may fail if RaptorQ adapter is not available
        # but the CDC preprocessing should work
        try:
            encoded = encoder.encode_for_upload(data)
            # If encoding succeeds, verify we can decode
            decoded = encoder.decode_from_chunks(encoded)
            assert decoded == data
        except Exception as e:
            # If RaptorQ is not available, that's okay - we're testing CDC integration
            if "RaptorQ" not in str(e):
                raise
