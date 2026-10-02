# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit tests for symmetric desktop/mobile image transfer and FastCDC verification.
"""

import io
import json
from pathlib import Path
import pytest

from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof


def test_fastcdc_image_chunking_and_merkle():
    """Verify arbitrary JPEG binary data is cleanly partitioned by FastCDC and authenticated."""
    synthetic_jpg = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + (b"RANDOM_IMAGE_DATA_PADDING_BLOCK_1234" * 150)
    
    chunker = ContentDefinedChunker(min_size=128, max_size=1024, target_size=256)
    chunks = chunker.chunk(synthetic_jpg)
    
    assert len(chunks) >= 2, "Expected multiple FastCDC chunks for synthetic image"
    assert b"".join(chunks) == synthetic_jpg, "Reassembled chunks must match original binary exactly"
    
    tree = MerkleTree(chunks)
    assert tree.root_hex is not None
    assert len(tree.root_hex) == 64
    proof = tree.get_proof(0)
    assert verify_merkle_proof(chunks[0], proof, tree.root) is True


def test_symmetric_server_lifecycle(tmp_path):
    """Verify the symmetric image sharing HTTP handler processes uploads and serves metadata."""
    from phone_download.server import SharedImageState

    state = SharedImageState(storage_dir=tmp_path)
    
    # 1. Initial state has no image
    meta = state.get_metadata()
    assert meta["has_image"] is False
    
    # 2. Store an image
    test_image_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"TEST_BYTES_IMAGE_PAYLOAD"
    res = state.set_image("photo.jpg", "image/jpeg", test_image_bytes)
    
    assert res["status"] == "ok"
    assert res["chunk_count"] >= 1
    assert "merkle_root" in res
    
    # 3. Retrieve metadata
    meta = state.get_metadata()
    assert meta["has_image"] is True
    assert meta["filename"] == "photo.jpg"
    assert meta["size_bytes"] == len(test_image_bytes)
    assert meta["content_type"] == "image/jpeg"
    
    # 4. Retrieve raw bytes
    raw_data, content_type = state.get_image_data()
    assert raw_data == test_image_bytes
    assert content_type == "image/jpeg"
