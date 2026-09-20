# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Experiment 1: Honest Permanent Symbol Loss & Fountain Erasure Recovery.

Verifies:
1. True permanent symbol loss: discarded droplets are permanently inaccessible.
2. Zero received symbols cannot produce successful reconstruction (must raise RuntimeError).
3. Sub-rank droplet subsets (fewer than K received symbols) must fail to decode.
4. With sufficient repair droplets, rateless Gaussian elimination reconstructs
   the original payload bit-for-bit without access to the publisher's droplet pool.
"""

import os
import pytest

from tfp_core_v4.fountain import FountainEncoder, FountainDecoder, FountainDroplet
from tfp_core_v4.node import TFPNode


def test_zero_received_droplets_must_fail():
    """Control: Zero received droplets must fail cleanly and never reconstruct."""
    node = TFPNode()
    payload = b"Emergency field surgical protocol payload"
    recipe = node.publish(payload)

    # 100% simulated loss means 0 droplets survive
    with pytest.raises(RuntimeError) as exc_info:
        node.fetch(recipe.root_hash, simulated_loss=1.0)
    assert "0 surviving droplets" in str(exc_info.value) or "Fountain decode failed" in str(exc_info.value)

    # Explicit empty droplet list must also fail
    with pytest.raises(RuntimeError) as exc_info:
        node.fetch(recipe.root_hash, received_droplets=[])
    assert "0 surviving droplets" in str(exc_info.value)


def test_sub_rank_droplets_must_fail():
    """Control: If received droplets < K source blocks, decode must raise."""
    encoder = FountainEncoder(symbol_size=64)
    data = os.urandom(640)  # 10 source blocks (K = 10)
    droplets, k, orig_len = encoder.encode(data, redundancy=0.50)  # 15 droplets
    assert k == 10
    assert len(droplets) == 15

    decoder = FountainDecoder(symbol_size=64, pre_validate=False)

    # Pass only 9 droplets (strictly less than K=10)
    insufficient = droplets[:9]
    with pytest.raises(ValueError) as exc_info:
        decoder.decode(insufficient, k=k, orig_len=orig_len)
    assert "Need at least 10 valid droplets" in str(exc_info.value) or "Insufficient" in str(exc_info.value)


def test_permanent_symbol_loss_recovery_with_repair():
    """
    Experiment 1 core:
    Drop systematic source droplets permanently, and prove that repair droplets
    (linear combinations) successfully solve for the missing symbols.
    """
    encoder = FountainEncoder(symbol_size=128)
    payload = b"CRITICAL DISASTER BULLETIN: Water treatment plant disabled. Use chlorine NaDCC tablets." * 10
    # K source blocks with redundancy=2.0 to ensure Soliton coupon-collector coverage of all indices
    droplets, k, orig_len = encoder.encode(payload, redundancy=2.0)
    assert k > 1

    # Separate systematic (0..k-1) and repair (k..end)
    systematic = droplets[:k]
    repair = droplets[k:]

    # Permanently discard 2 systematic droplets (index 0 and 1)
    discarded_indices = {0, 1}
    surviving_systematic = [d for d in systematic if d.seed not in discarded_indices]
    assert len(surviving_systematic) == k - 2

    # Combine surviving systematic with repair droplets
    received_droplets = surviving_systematic + repair

    decoder = FountainDecoder(symbol_size=128, pre_validate=False)
    reconstructed = decoder.decode(received_droplets, k=k, orig_len=orig_len)

    # Bit-exact equality verification
    assert reconstructed == payload, "Reconstructed payload must be bit-exact match"


def test_node_isolated_fetch_without_publisher_pool():
    """
    Verify TFPNode.fetch() using an explicit isolated received_droplets set.
    The node must NOT be able to reach into self.droplet_store to cheat.
    """
    node = TFPNode()
    payload = os.urandom(1024)
    recipe = node.publish(payload, redundancy=0.80)

    all_droplets = list(node.droplet_store[recipe.root_hash])
    k = (recipe.total_size + node.codec.symbol_size - 1) // node.codec.symbol_size

    # Simulate receiver getting all repair droplets + majority of systematic droplets
    # Permanently drop the first systematic droplet (seed 0)
    received = [d for d in all_droplets if d.seed != 0]

    # Temporarily wipe the publisher's droplet store to guarantee no secret access
    stashed_droplets = node.droplet_store[recipe.root_hash]
    node.droplet_store[recipe.root_hash] = []  # Wiped!

    try:
        # Fetch must succeed purely from received_droplets
        recovered = node.fetch(recipe.root_hash, received_droplets=received)
        assert recovered == payload
    finally:
        node.droplet_store[recipe.root_hash] = stashed_droplets
