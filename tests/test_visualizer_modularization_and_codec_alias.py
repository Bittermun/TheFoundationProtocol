# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acceptance tests for Visualizer Server Modularization and Binary Erasure Codec Taxonomy.

Proves:
1. tfp_core_v4.visualizer_server is cleanly decoupled and importable independently.
2. Complete backwards compatibility: create_visualizer_server and get_static_assets_dir
   are available from both tfp_core_v4.cli and tfp_core_v4.visualizer_server.
3. BinaryLinearErasureCodec is available from tfp_client.lib.fountain and
   tfp_client.lib.fountain.fountain_real as an architectural alias of RealRaptorQAdapter.
4. BinaryLinearErasureCodec successfully encodes and reconstructs payloads across
   packet erasure loss conditions using real GF(2) XOR algebra and Gaussian elimination.
5. HMAC-SHA3-256 integrity verification raises IntegrityError upon bit-tampering.
"""

import pytest
from tfp_core_v4.visualizer_server import (
    create_visualizer_server as vs_create_server,
    get_static_assets_dir as vs_get_assets,
)
from tfp_core_v4.cli import (
    create_visualizer_server as cli_create_server,
    get_static_assets_dir as cli_get_assets,
)
from tfp_client.lib.fountain import (
    BinaryLinearErasureCodec,
    IntegrityError,
    RealRaptorQAdapter,
)


def test_visualizer_server_modularization_and_compatibility(tmp_path):
    """Verify clean modularization and 100% backward compatibility."""
    assert vs_create_server is cli_create_server
    assert vs_get_assets is cli_get_assets

    assets_dir = vs_get_assets()
    assert assets_dir.is_dir()
    assert (assets_dir / "visualizer.html").is_file()

    server, port = vs_create_server(port=0, data_dir=tmp_path)
    assert port > 0
    server.server_close()


def test_binary_linear_erasure_codec_alias():
    """Verify that BinaryLinearErasureCodec is the architectural alias of RealRaptorQAdapter."""
    assert BinaryLinearErasureCodec is RealRaptorQAdapter
    codec = BinaryLinearErasureCodec(shard_size=128)
    assert codec.shard_size == 128


def test_binary_linear_erasure_codec_erasure_recovery():
    """Verify real GF(2) XOR Gaussian elimination recovery across packet loss."""
    raw_data = b"The Foundation Protocol: Resilient Civilization Knowledge Base v4.0. " * 10
    codec = BinaryLinearErasureCodec(shard_size=64)

    # Encode with 40% repair redundancy
    shards = codec.encode(raw_data, redundancy=0.40)
    assert len(shards) > 10

    k = (len(raw_data) + 63) // 64
    assert len(shards) >= k

    # Drop the first 2 source shards, simulating physical wireless link erasure
    lossy_shards = shards[2:]  # Dropped shards 0 and 1, keeping other source and repair shards
    assert len(lossy_shards) >= k

    # Reconstruct using k available shards
    recovered = codec.decode(lossy_shards[:k])
    assert recovered == raw_data


def test_binary_linear_erasure_codec_hmac_tamper_detection():
    """Verify per-shard HMAC-SHA3-256 integrity verification rejects tampered packets."""
    raw_data = b"Emergency civil defense directive: maintain designated frequency."
    key = b"super-secret-triage-key-256bit!"
    codec = BinaryLinearErasureCodec(shard_size=32)
    k = (len(raw_data) + 31) // 32

    shards = codec.encode(raw_data, redundancy=0.50, hmac_key=key)
    assert len(shards) > k

    # Tamper with a single byte in the payload of shard 0
    tampered_shard0 = bytearray(shards[0])
    tampered_shard0[15] ^= 0xFF
    tampered_shards = [bytes(tampered_shard0)] + shards[1:]

    # Case 1: When only k shards are provided and one is tampered, valid shards < k -> IntegrityError
    with pytest.raises(IntegrityError):
        codec.decode(tampered_shards[:k], hmac_key=key)

    # Case 2: When all shards are tampered -> IntegrityError
    all_tampered = [bytes(bytearray(s)[:15] + b"\xee" + bytearray(s)[16:]) for s in shards]
    with pytest.raises(IntegrityError):
        codec.decode(all_tampered, hmac_key=key)

    # Case 3: When redundant shards are available, the corrupted shard is dropped and data is recovered
    recovered = codec.decode(tampered_shards, hmac_key=key)
    assert recovered == raw_data
