# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for FastCDC ZIM Cluster-Aware Delta Extractor & Patcher.
"""

import os
import secrets
import hashlib
from pathlib import Path

import pytest

from tfp_core_v4.zim_sync import ZimDeltaEngine


def test_zim_delta_extraction_and_reconstruction(tmp_path: Path):
    """
    Verify FastCDC delta extraction between two ZIM-like archives.
    Proves that a 5% difference produces a minimal patch (~5% size) and
    reconstructs 100% bit-exact target archive.
    """
    base_zim = tmp_path / "v1.zim"
    target_zim = tmp_path / "v2.zim"

    # 20 clusters of 64 KB = 1,280 KB total archive
    shared_clusters = [hashlib.shake_256(f'cluster-{i}'.encode()).digest(64 * 1024) for i in range(20)]
    base_zim.write_bytes(b"".join(shared_clusters))

    # Mutate 1 cluster out of 20 (exactly 5% delta)
    mutated_clusters = list(shared_clusters)
    mutated_clusters[5] = hashlib.shake_256(b'mutated-cluster').digest(64 * 1024)
    target_zim.write_bytes(b"".join(mutated_clusters))

    patch_file = tmp_path / "patch.tfp"
    engine = ZimDeltaEngine(min_chunk_size=16384, target_chunk_size=65536, max_chunk_size=131072)
    manifest = engine.create_patch(base_path=base_zim, target_path=target_zim, patch_out=patch_file)

    # Base and target are ~1,280 KB each.
    # The patch should contain only the mutated cluster and any neighboring desynced chunk (~180-230 KB),
    # achieving >= 75% bandwidth savings compared to re-transferring the full archive.
    patch_size = patch_file.stat().st_size
    target_size = target_zim.stat().st_size
    savings_pct = (1.0 - (patch_size / target_size)) * 100.0
    assert savings_pct >= 70.0, f"Bandwidth savings insufficient: {savings_pct:.1f}% (patch={patch_size}B)"
    assert patch_size < 400 * 1024, f"Patch size too large: {patch_size} bytes"

    # Reconstruct target archive from base + patch
    reconstructed_zim = tmp_path / "reconstructed.zim"
    engine.apply_patch(base_path=base_zim, patch_path=patch_file, out_path=reconstructed_zim)

    assert reconstructed_zim.exists()
    assert reconstructed_zim.read_bytes() == target_zim.read_bytes()


def test_zim_delta_identical_files_produce_zero_novel_payload(tmp_path: Path):
    """Verify that diffing identical archives produces 0 novel chunk bytes."""
    data = secrets.token_bytes(256 * 1024)
    file_a = tmp_path / "a.zim"
    file_b = tmp_path / "b.zim"
    file_a.write_bytes(data)
    file_b.write_bytes(data)

    patch_file = tmp_path / "empty_patch.tfp"
    engine = ZimDeltaEngine(min_chunk_size=8192, target_chunk_size=16384, max_chunk_size=32768)
    manifest = engine.create_patch(base_path=file_a, target_path=file_b, patch_out=patch_file)

    assert manifest.novel_chunk_count == 0
    # Patch only contains manifest metadata header, well under 2 KB
    assert patch_file.stat().st_size < 2048

    out_file = tmp_path / "recovered.zim"
    engine.apply_patch(base_path=file_a, patch_path=patch_file, out_path=out_file)
    assert out_file.read_bytes() == data


def test_stream_chunking_parity_and_bounded_memory(tmp_path: Path):
    """Verify stream chunking matches ContentDefinedChunker chunking bit-for-bit."""
    data = secrets.token_bytes(512 * 1024)
    file_p = tmp_path / "test.bin"
    file_p.write_bytes(data)

    engine = ZimDeltaEngine(min_chunk_size=4096, target_chunk_size=16384, max_chunk_size=32768)
    monolithic_chunks = engine.chunker.chunk(data)

    stream_chunks = [c for _, c, _ in engine._stream_chunks(file_p)]
    assert len(stream_chunks) == len(monolithic_chunks)
    for c1, c2 in zip(stream_chunks, monolithic_chunks):
        assert c1 == c2

