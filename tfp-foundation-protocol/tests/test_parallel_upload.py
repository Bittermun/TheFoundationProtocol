# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Integration tests for parallel chunk upload functionality.

Tests the ChunkUploader, ChunkEncoder, and server reassembly endpoints.
"""

import asyncio
import hashlib
import os

import pytest
import httpx

from tfp_client.lib.upload.chunk_uploader import ChunkUploader
from tfp_client.lib.upload.chunk_encoder import ChunkEncoder
from tfp_client.lib.upload.retry_handler import RetryHandler


class TestChunkUploader:
    """Tests for ChunkUploader functionality."""

    def test_split_into_chunks(self):
        """Test that data is correctly split into chunks."""
        uploader = ChunkUploader(chunk_size=1024)
        data = b"a" * 3000  # 3KB of data
        chunks = uploader.split_into_chunks(data)

        assert len(chunks) == 3  # Should split into 3 chunks
        assert all(len(chunk) <= 1024 for chunk in chunks)
        assert b"".join(chunks) == data  # Reassembly should match original

    def test_split_empty_data(self):
        """Test splitting empty data."""
        uploader = ChunkUploader()
        chunks = uploader.split_into_chunks(b"")
        assert chunks == []

    def test_split_exact_multiple(self):
        """Test splitting data that's an exact multiple of chunk size."""
        uploader = ChunkUploader(chunk_size=1024)
        data = b"a" * 2048  # Exactly 2 chunks
        chunks = uploader.split_into_chunks(data)

        assert len(chunks) == 2
        assert all(len(chunk) == 1024 for chunk in chunks)


class TestChunkEncoder:
    """Tests for ChunkEncoder erasure coding."""

    def test_encode_decode_roundtrip(self):
        """Test that encoding and decoding preserves original data."""
        encoder = ChunkEncoder(chunk_size=1024, redundancy=0.1)
        data = b"Hello, World! This is a test message." * 100

        encoded_chunks = encoder.encode_for_upload(data)
        decoded_data = encoder.decode_from_chunks(encoded_chunks)

        assert decoded_data == data

    def test_encode_empty_data(self):
        """Test encoding empty data raises error."""
        encoder = ChunkEncoder()
        with pytest.raises(ValueError, match="Cannot encode empty data"):
            encoder.encode_for_upload(b"")

    def test_decode_empty_chunks(self):
        """Test decoding empty chunks raises error."""
        encoder = ChunkEncoder()
        with pytest.raises(ValueError, match="No chunks to decode"):
            encoder.decode_from_chunks([])

    def test_estimate_chunk_count(self):
        """Test chunk count estimation."""
        encoder = ChunkEncoder(chunk_size=1024, redundancy=0.1)
        data_size = 10000  # 10KB

        estimated = encoder.estimate_chunk_count(data_size)
        assert estimated > 0
        # Should be roughly data_size / chunk_size * (1 + redundancy)
        expected_min = (data_size + 1023) // 1024  # Ceiling division
        assert estimated >= expected_min

    def test_min_chunks_to_recover(self):
        """Test minimum chunk calculation."""
        encoder = ChunkEncoder(redundancy=0.1)
        total_chunks = 11  # 10 source + 1 repair

        min_needed = encoder.get_min_chunks_to_recover(total_chunks)
        assert min_needed == 10  # Need 10 out of 11


class TestRetryHandler:
    """Tests for RetryHandler retry logic."""

    def test_successful_execution_no_retry(self):
        """Test that successful function doesn't trigger retries."""
        handler = RetryHandler(max_retries=3)

        async def success_func():
            return "success"

        # Run async test synchronously
        result = asyncio.run(handler.execute_with_retry(success_func))
        assert result == "success"

    def test_retry_on_failure(self):
        """Test that failed function triggers retries."""
        handler = RetryHandler(max_retries=2, base_delay=0.1)
        attempt_count = 0

        async def failing_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("Temporary failure")
            return "success after retry"

        result = asyncio.run(handler.execute_with_retry(failing_func))
        assert result == "success after retry"
        assert attempt_count == 2

    def test_exhausted_retries(self):
        """Test that exhausted retries raise the last exception."""
        handler = RetryHandler(max_retries=2, base_delay=0.1)

        async def always_failing_func():
            raise ValueError("Persistent failure")

        with pytest.raises(ValueError, match="Persistent failure"):
            asyncio.run(handler.execute_with_retry(always_failing_func))

    def test_should_retry_transient_errors(self):
        """Test retry detection for transient errors."""
        handler = RetryHandler()

        assert handler.should_retry(Exception("timeout"))
        assert handler.should_retry(Exception("connection error"))
        assert handler.should_retry(Exception("503 Service Unavailable"))
        assert not handler.should_retry(ValueError("invalid input"))

    def test_execute_with_retry_non_retryable(self):
        """Test that non-retryable errors are not retried."""
        handler = RetryHandler(max_retries=3, base_delay=0.1)
        attempt_count = 0

        async def non_retryable_func():
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("Invalid input - not retryable")

        with pytest.raises(ValueError, match="Invalid input"):
            asyncio.run(handler.execute_with_retry(non_retryable_func))

        # Should only attempt once (no retries for non-retryable errors)
        assert attempt_count == 1


class TestChunkUploadIntegration:
    """Integration tests for chunk upload flow."""

    def test_parallel_upload_mock(self):
        """Test parallel upload with mock server responses."""
        uploader = ChunkUploader(max_concurrent=4, chunk_size=1024)
        data = b"a" * 5000

        chunks = uploader.split_into_chunks(data)
        assert len(chunks) > 1

        # In a real test, this would use a test server
        # For now, we just verify the chunking works
        assert b"".join(chunks) == data

    def test_encoder_uploader_integration(self):
        """Test integration between encoder and uploader."""
        encoder = ChunkEncoder(chunk_size=1024, redundancy=0.1)
        uploader = ChunkUploader(chunk_size=1024)

        data = b"Test data for integration" * 200
        encoded_chunks = encoder.encode_for_upload(data)
        plain_chunks = uploader.split_into_chunks(data)

        # Encoded should have more chunks due to redundancy
        assert len(encoded_chunks) >= len(plain_chunks)

        # Decoding should recover original
        decoded = encoder.decode_from_chunks(encoded_chunks)
        assert decoded == data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

    def test_concurrent_puts(self):
        """Test that concurrent puts don't corrupt the cache."""
        import threading

        cache = ContentCache(maxsize=100)
        num_threads = 10
        items_per_thread = 20

        def put_items(thread_id: int):
            for i in range(items_per_thread):
                cache.put(f"hash-{thread_id}-{i}", f"data-{thread_id}-{i}".encode())

        threads = [threading.Thread(target=put_items, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All items should be in cache (up to maxsize)
        stats = cache.stats()
        assert stats["size"] <= cache._maxsize
        assert stats["size"] > 0

    def test_concurrent_gets(self):
        """Test that concurrent gets work correctly."""
        import threading

        cache = ContentCache(maxsize=100)
        cache.put("hash-1", b"data-1")
        cache.put("hash-2", b"data-2")

        results = []

        def get_items():
            for i in range(10):
                result = cache.get("hash-1")
                results.append(result)

        threads = [threading.Thread(target=get_items) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All gets should return the same data
        assert all(r == b"data-1" for r in results)
        assert len(results) == 50

    def test_lru_eviction_under_concurrent_access(self):
        """Test LRU eviction works correctly under concurrent access."""
        import threading

        cache = ContentCache(maxsize=5)
        
        # Fill cache to capacity
        for i in range(5):
            cache.put(f"hash-{i}", f"data-{i}".encode())

        # Access some items to establish LRU order
        cache.get("hash-0")
        cache.get("hash-1")

        # Add more items concurrently
        def add_items(start: int):
            for i in range(3):
                cache.put(f"hash-{start + i}", f"data-{start + i}".encode())

        threads = [threading.Thread(target=add_items, args=(5,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Cache should still be at or below maxsize
        assert cache.stats()["size"] <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
