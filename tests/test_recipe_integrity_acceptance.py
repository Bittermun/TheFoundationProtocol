# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acceptance tests for Recipe Content Integrity & Order Reversal Protection.

Proves that:
1. Fast-path retrieval verifies that the ordered sequence of chunks matches root_hash.
2. Tampering with SQLite chunk_hashes_json (reversing or swapping chunks) is rejected
   with ValueError under both fast-path and fountain reconstruction paths.
3. ContentDefinedChunker.assemble rejects corrupted recipes before returning bytes.
"""

import json
import sqlite3
import pytest
from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.node import TFPNode


def test_recipe_validation_reversal_detected():
    """Verify that reversing chunk order invalidates the recipe."""
    chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
    # Multi-chunk payload
    data = b"CHUNK_A_CONTENT_" * 30 + b"CHUNK_B_CONTENT_" * 30 + b"CHUNK_C_CONTENT_" * 30
    recipe, chunks = chunker.create_recipe(data)
    assert len(recipe.chunk_hashes) > 1

    # Normal recipe must validate
    assert recipe.validate(expected_root=recipe.root_hash) is True

    # Tampered recipe with reversed chunks
    reversed_recipe = ChunkRecipe(
        root_hash=recipe.root_hash,
        total_size=recipe.total_size,
        chunk_hashes=recipe.chunk_hashes[::-1],
        chunk_sizes=recipe.chunk_sizes[::-1],
        metadata=recipe.metadata,
    )
    assert reversed_recipe.validate(expected_root=recipe.root_hash) is False

    chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, chunks)}
    with pytest.raises(ValueError, match="Invalid recipe"):
        ContentDefinedChunker.assemble(reversed_recipe, chunk_map)


def test_sqlite_tampered_order_rejected_by_node_fetch(tmp_path):
    """
    Simulate an adversarial attack where SQLite chunk_hashes_json order is reversed.
    Verify that node.fetch() refuses to return tampered content under the authentic root_hash.
    """
    db_path = tmp_path / "tamper_test.db"
    chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
    node1 = TFPNode(db_path=db_path, chunker=chunker)

    # Publish multi-chunk content
    payload = b"FIRST_SECTION_DATA_" * 50 + b"SECOND_SECTION_DATA_" * 50 + b"THIRD_SECTION_DATA_" * 50
    recipe = node1.publish(payload, metadata={"title": "Multi-section Doc"})
    root_hash = recipe.root_hash
    assert len(recipe.chunk_hashes) >= 2

    # Verify normal fast-path fetch succeeds
    fetched = node1.fetch(root_hash)
    assert fetched == payload

    # Now tamper directly with SQLite database: reverse chunk_hashes_json and chunk_sizes_json
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT chunk_hashes_json, chunk_sizes_json FROM recipes WHERE root_hash = ?", (root_hash,))
    h_json, s_json = cur.fetchone()
    hashes = json.loads(h_json)
    sizes = json.loads(s_json)

    tampered_hashes = hashes[::-1]
    tampered_sizes = sizes[::-1]

    cur.execute(
        "UPDATE recipes SET chunk_hashes_json = ?, chunk_sizes_json = ? WHERE root_hash = ?",
        (json.dumps(tampered_hashes), json.dumps(tampered_sizes), root_hash),
    )
    conn.commit()
    conn.close()

    # Cold restart fresh node
    node2 = TFPNode(db_path=db_path)

    # Attempting to fetch must raise KeyError or ValueError because recipe validation fails
    # either during _load_recipe_from_db or during fetch integrity verification
    with pytest.raises((KeyError, ValueError)):
        node2.fetch(root_hash)

    # In-memory recipe tampering probe
    # If a malicious actor manipulated node1.recipes in place:
    bad_recipe = ChunkRecipe(
        root_hash=root_hash,
        total_size=recipe.total_size,
        chunk_hashes=tampered_hashes,
        chunk_sizes=tampered_sizes,
        metadata=recipe.metadata,
    )
    node1.recipes[root_hash] = bad_recipe
    with pytest.raises(ValueError, match="does not match root hash"):
        node1.fetch(root_hash)


@pytest.mark.parametrize("cold_reader", [False, True])
@pytest.mark.parametrize("use_fountain", [False, True])
def test_reordered_recipe_rejected_on_every_retrieval_path(tmp_path, cold_reader, use_fountain):
    """Both retrieval paths bind content to the requested identity, also after restart."""
    db = tmp_path / "identity.db"
    writer = TFPNode(db_path=db, chunker=ContentDefinedChunker(128, 256, 128))
    payload = b"A" * 256 + b"B" * 256 + b"C" * 256
    recipe = writer.publish(payload)
    droplets = writer.droplet_store[recipe.root_hash]
    assert writer.fetch(recipe.root_hash, received_droplets=droplets if use_fountain else None) == payload
    reversed_hashes = recipe.chunk_hashes[::-1]
    reversed_sizes = recipe.chunk_sizes[::-1]
    if cold_reader:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE recipes SET chunk_hashes_json=?, chunk_sizes_json=? WHERE root_hash=?",
                (json.dumps(reversed_hashes), json.dumps(reversed_sizes), recipe.root_hash),
            )
        reader = TFPNode(db_path=db, symbol_size=512)
    else:
        reader = writer
        reader.recipes[recipe.root_hash] = ChunkRecipe(
            recipe.root_hash, recipe.total_size, reversed_hashes, reversed_sizes, recipe.metadata,
        )
    with pytest.raises((KeyError, ValueError)):
        reader.fetch(recipe.root_hash, received_droplets=droplets if use_fountain else None)
