# SPDX-License-Identifier: Apache-2.0
"""Zstandard domain dictionary training and held-out compression measurements."""

from typing import Dict, List, Tuple

import zstandard as zstd


def train_lexicon_dictionary(
    samples: List[bytes], dict_size: int = 112640
) -> Tuple[zstd.ZstdCompressionDict, Dict[str, float]]:
    """Trains a Zstandard compression dictionary from sample payloads and evaluates savings."""
    if not samples:
        raise ValueError("Cannot train dictionary on empty sample set")

    # Split 80/20 train/test
    split_idx = int(len(samples) * 0.8)
    train_samples = samples[:split_idx]
    test_samples = samples[split_idx:]

    # Train dictionary using zstandard
    trained_dict = zstd.train_dictionary(dict_size=dict_size, samples=train_samples)

    # Benchmark against generic compression without dictionary
    cctx_plain = zstd.ZstdCompressor(level=3)
    cctx_dict = zstd.ZstdCompressor(level=3, dict_data=trained_dict)

    raw_total = sum(len(s) for s in test_samples)
    plain_total = sum(len(cctx_plain.compress(s)) for s in test_samples)
    dict_total = sum(len(cctx_dict.compress(s)) for s in test_samples)

    plain_ratio = raw_total / plain_total if plain_total else 1.0
    dict_ratio = raw_total / dict_total if dict_total else 1.0
    bandwidth_savings_pct = (1.0 - (dict_total / plain_total)) * 100.0 if plain_total else 0.0

    metrics = {
        "raw_bytes": raw_total,
        "generic_compressed_bytes": plain_total,
        "dict_compressed_bytes": dict_total,
        "generic_ratio": round(plain_ratio, 2),
        "dict_ratio": round(dict_ratio, 2),
        "bandwidth_savings_vs_generic_pct": round(bandwidth_savings_pct, 2),
        "dictionary_id": trained_dict.dict_id(),
        "dictionary_size_bytes": len(trained_dict.as_bytes()),
    }
    return trained_dict, metrics
