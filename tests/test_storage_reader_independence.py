# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from pathlib import Path
import pytest
from tfp_core_v4.node import TFPNode
from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec


def test_stored_content_retrieval_independent_of_reader_settings(tmp_path: Path):
    """
    Verifies that stored content remains readable even when the reader node
    runs with different symbol_size or FastCDC chunker parameters than the writer.
    """
    db_file = tmp_path / "cross_settings_archive.db"
    test_payload = b"OFFLINE_MEDICAL_MANUAL_CHAPTER_123: " + (b"QUININE_AND_ARTESUNATE_TREATMENT_PROTOCOLS\n" * 150)

    # 1. Writer Node: uses non-default symbol_size=128 and customized chunk boundaries
    writer_chunker = ContentDefinedChunker(min_size=128, target_size=256, max_size=512)
    writer_codec = FountainCodec(symbol_size=128)
    writer_node = TFPNode(db_path=db_file, chunker=writer_chunker, codec=writer_codec)

    recipe = writer_node.publish(test_payload, metadata={"title": "Severe Malaria"}, redundancy=1.0)
    root_hash = recipe.root_hash

    # Ensure writer node's in-memory state is closed
    del writer_node

    # 2. Reader Node: opened with completely different settings (symbol_size=512, larger chunker)
    reader_chunker = ContentDefinedChunker(min_size=256, target_size=1024, max_size=2048)
    reader_node = TFPNode(db_path=db_file, symbol_size=512, chunker=reader_chunker)
    assert reader_node.codec.symbol_size == 512, "Reader runs 512-byte symbols (writer used 128)"

    # Fast path: Local intact chunk reading
    recovered_direct = reader_node.fetch(root_hash, simulated_loss=0.0)
    assert recovered_direct == test_payload, "Direct local retrieval must be 100% bit-exact across different settings"

    # Fountain loss path: Force fountain reconstruction by providing droplets with seed 0 dropped
    # Reader node (symbol_size=512) must dynamically adapt to writer's symbol_size=128
    stored_droplets = reader_node.droplet_store[root_hash]
    surviving_droplets = [d for d in stored_droplets if d.seed != 0]
    recovered_fountain = reader_node.fetch(root_hash, received_droplets=surviving_droplets)
    assert recovered_fountain == test_payload, "Fountain loss recovery must succeed across different settings"
