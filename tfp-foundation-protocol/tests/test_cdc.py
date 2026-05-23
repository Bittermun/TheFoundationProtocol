# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import hashlib
import pytest
from tfp_client.lib.fountain.cdc import ContentDefinedChunker


def test_cdc_empty_data():
    chunker = ContentDefinedChunker()
    assert chunker.chunk_data(b"") == []


def test_cdc_small_data():
    chunker = ContentDefinedChunker(min_size=100, max_size=500, target_size=200)
    data = b"hello" * 10
    chunks = chunker.chunk_data(data)
    assert len(chunks) == 1
    assert chunks[0]["offset"] == 0
    assert chunks[0]["size"] == len(data)
    assert chunks[0]["hash"] == hashlib.sha3_256(data).hexdigest()
    assert chunks[0]["data"] == data


def test_cdc_chunk_bounds():
    min_size = 100
    max_size = 500
    target_size = 256
    chunker = ContentDefinedChunker(min_size=min_size, max_size=max_size, target_size=target_size)
    
    # Generate 2000 bytes of repeatable pseudo-random data
    data = bytes((i * 17) % 256 for i in range(2000))
    chunks = chunker.chunk_data(data)
    
    assert len(chunks) > 1
    total_size = 0
    for chunk in chunks:
        assert chunk["size"] >= min_size or chunk == chunks[-1]  # last chunk can be smaller if trailing
        assert chunk["size"] <= max_size
        assert chunk["hash"] == hashlib.sha3_256(chunk["data"]).hexdigest()
        assert chunk["offset"] == total_size
        total_size += chunk["size"]
        
    assert total_size == len(data)


def test_cdc_boundary_shift_resistance():
    """
    Assert that inserting a few bytes in the middle of a file only changes
    one or two chunks, keeping other chunk boundaries fully intact.
    """
    chunker = ContentDefinedChunker(min_size=50, max_size=200, target_size=64)
    
    # Base data
    base_data = bytes((i * 31) % 256 for i in range(1000))
    base_chunks = chunker.chunk_data(base_data)
    
    # Modified data (inserted 5 bytes at index 400)
    mod_data = base_data[:400] + b"ABCDE" + base_data[400:]
    mod_chunks = chunker.chunk_data(mod_data)
    
    # Check that early chunk hashes match exactly
    match_count_start = 0
    for c1, c2 in zip(base_chunks, mod_chunks):
        if c1["hash"] == c2["hash"]:
            match_count_start += 1
        else:
            break
            
    assert match_count_start > 0
    
    # Check that tail chunk hashes match exactly (deduplicated)
    base_hashes_tail = [c["hash"] for c in base_chunks[match_count_start + 2:]]
    mod_hashes_tail = [c["hash"] for c in mod_chunks]
    
    # Find matching subset
    tail_matches = 0
    for h in base_hashes_tail:
        if h in mod_hashes_tail:
            tail_matches += 1
            
    assert tail_matches > 0
