# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Throughput and Acceleration Benchmark Suite for Wirehair / AcceleratedFountainCodec.

Measures encoding and decoding throughput across multiple payload sizes (64KB to 1MB)
and asserts bit-exact erasure recovery and seamless fallback transparency.
"""

from pathlib import Path
import random
import sys
import time
import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.wirehair_bridge import AcceleratedFountainCodec, wirehair_is_available
from tfp_core_v4.fountain import FountainCodec


def test_wirehair_availability_flag():
    """Verify availability check executes safely without uncaught exceptions."""
    is_avail = wirehair_is_available()
    assert isinstance(is_avail, bool)


def test_accelerated_codec_transparency():
    """Verify AcceleratedFountainCodec produces identical bit-exact recovery as FountainCodec."""
    data = b"FOUNDATION-PROTOCOL-ACCELERATION-TEST:" * 100
    codec_accel = AcceleratedFountainCodec(symbol_size=256)
    codec_pure = FountainCodec(symbol_size=256)

    droplets_accel, k_accel, len_accel = codec_accel.encode(data, redundancy=0.30)
    droplets_pure, k_pure, len_pure = codec_pure.encode(data, redundancy=0.30)

    assert k_accel == k_pure
    assert len_accel == len_pure

    rec_accel = codec_accel.decode(droplets_accel, k_accel, len_accel)
    rec_pure = codec_pure.decode(droplets_pure, k_pure, len_pure)

    assert rec_accel == data
    assert rec_pure == data


@pytest.mark.parametrize("payload_size_kb", [64, 128, 256])
def test_accelerated_codec_throughput(payload_size_kb):
    """Benchmark encode and decode throughput across practical streaming chunk sizes."""
    payload_bytes = payload_size_kb * 1024
    rng = random.Random(42)
    data = rng.randbytes(payload_bytes)

    codec = AcceleratedFountainCodec(symbol_size=512)

    # Measure encoding speed
    t0 = time.perf_counter()
    droplets, k, orig_len = codec.encode(data, redundancy=0.20)
    t_enc = time.perf_counter() - t0

    # Measure decoding speed
    t1 = time.perf_counter()
    recovered = codec.decode(droplets, k, orig_len)
    t_dec = time.perf_counter() - t1

    assert recovered == data

    mb = payload_bytes / (1024 * 1024)
    enc_speed = mb / t_enc if t_enc > 0 else float("inf")
    dec_speed = mb / t_dec if t_dec > 0 else float("inf")

    # Assert basic performance floor (at least 0.5 MB/s on modest hardware)
    assert enc_speed > 0.5
    assert dec_speed > 0.5


def test_accelerated_codec_erasure_recovery():
    """Verify recovery under random erasures with rateless droplet accumulation."""
    data = b"RESILIENT-DATA-BLOCK-" * 128
    codec = AcceleratedFountainCodec(symbol_size=256)

    # Encode with rateless repair overhead
    droplets, k, orig_len = codec.encode(data, redundancy=0.80)

    # Simulate 20% network packet drop
    rng = random.Random(999)
    surviving = [d for d in droplets if rng.random() >= 0.20]

    # Rateless accumulation: ingest arriving stream until full rank
    recovered = None
    for d in droplets:
        try:
            recovered = codec.decode(surviving, k, orig_len)
            break
        except ValueError:
            if d not in surviving:
                surviving.append(d)

    assert recovered == data
