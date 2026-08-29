# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Benchmark Verification Suite for TFP

Measures:
1. Fountain / RaptorQ encoding and decoding throughput (MB/s).
2. FastCDC chunking throughput (MB/s) and deduplication ratio.
3. Merkle tree construction and proof verification latencies.
4. Multi-node parallel retrieval and reconstruction speed under simulated loss.
5. Strict assertions against baseline performance thresholds.
"""

import asyncio
import hashlib
import os
import random
import time
from typing import Dict, List
import pytest

from tfp_client.lib.fountain.raptorq_ffi import RealRaptorQAdapter
from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork
from tfp_core_v4.node import TFPNode


# ==============================================================================
# 1. Fountain / RaptorQ Encoding & Decoding Throughput Benchmarks
# ==============================================================================

@pytest.mark.benchmark
class TestFountainThroughputBenchmarks:
    """Benchmark vectorized GF(2) fountain codec and RFC 6330 RaptorQ throughput."""

    def test_fountain_encode_throughput_baseline(self):
        """
        Benchmark FountainCodec encoding throughput on a 100KB payload with 50% redundancy.
        Baseline threshold: >= 2.0 MB/s.
        """
        payload_size = 100 * 1024  # 100 KB
        payload = os.urandom(payload_size)
        codec = FountainCodec(symbol_size=256)

        t0 = time.perf_counter()
        droplets, k, orig_len = codec.encode(payload, redundancy=0.50)
        t1 = time.perf_counter()

        elapsed = max(t1 - t0, 1e-9)
        throughput_mb_s = (payload_size / (1024 * 1024)) / elapsed

        print(f"\n[Benchmark] Fountain Encode Throughput: {throughput_mb_s:.2f} MB/s ({payload_size/1024:.0f} KB in {elapsed*1000:.2f} ms)")
        assert len(droplets) >= k
        assert orig_len == payload_size
        assert throughput_mb_s >= 2.0, f"Fountain encode throughput {throughput_mb_s:.2f} MB/s below baseline 2.0 MB/s"

    def test_fountain_decode_throughput_baseline(self):
        """
        Benchmark FountainCodec decoding throughput using vectorized Gaussian elimination.
        Baseline threshold: >= 1.0 MB/s.
        """
        payload_size = 50 * 1024  # 50 KB
        payload = os.urandom(payload_size)
        codec = FountainCodec(symbol_size=256)

        droplets, k, orig_len = codec.encode(payload, redundancy=0.50)

        t0 = time.perf_counter()
        recovered = codec.decode(droplets, k=k, orig_len=orig_len)
        t1 = time.perf_counter()

        elapsed = max(t1 - t0, 1e-9)
        throughput_mb_s = (payload_size / (1024 * 1024)) / elapsed

        print(f"\n[Benchmark] Fountain Decode Throughput: {throughput_mb_s:.2f} MB/s ({payload_size/1024:.0f} KB in {elapsed*1000:.2f} ms)")
        assert recovered == payload
        assert throughput_mb_s >= 1.0, f"Fountain decode throughput {throughput_mb_s:.2f} MB/s below baseline 1.0 MB/s"

    def test_raptorq_adapter_encode_decode_throughput(self):
        """
        Benchmark RealRaptorQAdapter encoding and decoding throughput on 256KB payload.
        Baseline threshold: Encode >= 0.8 MB/s (pure Python), Decode >= 100.0 MB/s.
        """
        payload_size = 256 * 1024  # 256 KB
        payload = os.urandom(payload_size)
        adapter = RealRaptorQAdapter(shard_size=1024)

        # Encode
        t0 = time.perf_counter()
        shards = adapter.encode(payload, redundancy=0.20)
        t1 = time.perf_counter()
        encode_elapsed = max(t1 - t0, 1e-9)
        encode_speed_mb_s = (payload_size / (1024 * 1024)) / encode_elapsed

        # Decode
        t2 = time.perf_counter()
        recovered = adapter.decode(shards)
        t3 = time.perf_counter()
        decode_elapsed = max(t3 - t2, 1e-9)
        decode_speed_mb_s = (payload_size / (1024 * 1024)) / decode_elapsed

        print(f"\n[Benchmark] RaptorQ Adapter: Encode={encode_speed_mb_s:.2f} MB/s, Decode={decode_speed_mb_s:.2f} MB/s")
        assert len(recovered) >= payload_size
        assert recovered[:payload_size] == payload
        assert encode_speed_mb_s >= 0.8, f"Encode speed {encode_speed_mb_s:.2f} MB/s < 0.8 MB/s"
        assert decode_speed_mb_s >= 100.0, f"Decode speed {decode_speed_mb_s:.2f} MB/s < 100.0 MB/s"


# ==============================================================================
# 2. FastCDC Chunking & Deduplication Throughput Benchmarks
# ==============================================================================

@pytest.mark.benchmark
class TestFastCDCChunkingBenchmarks:
    """Benchmark FastCDC 64-bit rolling hash partitioning speed and deduplication efficiency."""

    def test_fastcdc_chunking_throughput_baseline(self):
        """
        Benchmark ContentDefinedChunker chunking throughput on a 500KB payload.
        Baseline threshold: >= 5.0 MB/s.
        """
        payload_size = 500 * 1024  # 500 KB
        payload = os.urandom(payload_size)
        chunker = ContentDefinedChunker(min_size=512, max_size=4096, target_size=1024)

        t0 = time.perf_counter()
        chunks = chunker.chunk(payload)
        t1 = time.perf_counter()

        elapsed = max(t1 - t0, 1e-9)
        throughput_mb_s = (payload_size / (1024 * 1024)) / elapsed

        print(f"\n[Benchmark] FastCDC Chunking Speed: {throughput_mb_s:.2f} MB/s ({len(chunks)} chunks in {elapsed*1000:.2f} ms)")
        assert len(chunks) > 100
        assert sum(len(c) for c in chunks) == payload_size
        assert throughput_mb_s >= 5.0, f"FastCDC throughput {throughput_mb_s:.2f} MB/s < 5.0 MB/s"

    def test_fastcdc_deduplication_ratio_benchmark(self):
        """
        Benchmark FastCDC deduplication ratio when a 16-byte localized edit is made to a 100KB file.
        Baseline threshold: Cumulative deduplication ratio >= 45.0% across the 2-file corpus.
        """
        base_data = os.urandom(100 * 1024)
        # Create modified version with small localized change in middle
        mod_data = bytearray(base_data)
        mod_data[50 * 1024 : 50 * 1024 + 16] = b"MODIFIED_16BYTES"
        mod_data = bytes(mod_data)

        engine = TFPNode(node_id="dedup_bench")
        recipe1 = engine.publish(base_data)
        recipe2 = engine.publish(mod_data)

        telemetry = engine.get_telemetry()
        dedup_pct = telemetry["bandwidth_saved_pct"]

        print(f"\n[Benchmark] FastCDC Localized Edit Deduplication Ratio: {dedup_pct:.1f}%")
        assert dedup_pct >= 45.0, f"Deduplication {dedup_pct:.1f}% below baseline 45.0%"


# ==============================================================================
# 3. Merkle Tree Construction & Verification Latencies
# ==============================================================================

@pytest.mark.benchmark
class TestMerkleTreeLatencyBenchmarks:
    """Benchmark SHA3-256 Merkle tree construction latency and constant-time proof verification."""

    def test_merkle_tree_construction_latency(self):
        """
        Benchmark time to construct a binary Merkle tree over 1,000 leaf hashes.
        Baseline threshold: < 100 ms total construction time (< 0.1 ms per leaf).
        """
        num_leaves = 1000
        leaves = [os.urandom(64) for _ in range(num_leaves)]

        t0 = time.perf_counter()
        tree = MerkleTree(leaves)
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000.0
        print(f"\n[Benchmark] Merkle Tree (1000 leaves) Construction Latency: {elapsed_ms:.2f} ms")
        assert tree.root is not None
        assert len(tree.leaf_hashes) == num_leaves
        assert elapsed_ms < 100.0, f"Merkle construction latency {elapsed_ms:.2f} ms exceeded 100 ms threshold"

    def test_merkle_proof_verification_latency(self):
        """
        Benchmark constant-time Merkle proof verification over 256 proofs.
        Baseline threshold: Mean latency < 0.5 ms per proof (< 500 us).
        """
        num_leaves = 256
        leaves = [os.urandom(64) for _ in range(num_leaves)]
        tree = MerkleTree(leaves)
        expected_root = tree.root

        proofs = [(i, leaves[i], tree.get_proof(i)) for i in range(num_leaves)]

        t0 = time.perf_counter()
        for idx, leaf_data, proof in proofs:
            valid = verify_merkle_proof(leaf_data, proof, expected_root)
            assert valid is True
        t1 = time.perf_counter()

        total_ms = (t1 - t0) * 1000.0
        mean_us = (total_ms / num_leaves) * 1000.0

        print(f"\n[Benchmark] Merkle Proof Verification Mean Latency: {mean_us:.2f} us per proof ({total_ms:.2f} ms for {num_leaves} proofs)")
        assert mean_us < 500.0, f"Mean verification latency {mean_us:.2f} us exceeded 500 us threshold"


# ==============================================================================
# 4. Multi-Node Parallel Retrieval & Reconstruction Speed Under Loss
# ==============================================================================

@pytest.mark.benchmark
class TestParallelRetrievalAndReconstructionBenchmarks:
    """Benchmark end-to-end multi-node swarm retrieval latency under simulated packet loss."""

    @pytest.mark.asyncio
    async def test_parallel_swarm_retrieval_under_loss_speed(self):
        """
        Benchmark 5-node distributed swarm fetch of a 20KB payload with 20% packet loss.
        Baseline threshold: Total retrieval + reconstruction time < 3.0 seconds.
        """
        net = SwarmNetwork()
        origin = net.add_peer("origin", loss_rate=0.0)
        relays = [net.add_peer(f"relay_{i}", loss_rate=0.20) for i in range(4)]
        consumer = net.add_peer("consumer", loss_rate=0.0)

        for r in relays:
            origin.connect(r)
            r.connect(consumer)

        payload_size = 20 * 1024  # 20 KB
        payload = os.urandom(payload_size)
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        for r in relays:
            r.store_content(recipe, droplets, mtree.root_hex)
        consumer.known_recipes[recipe.root_hash] = recipe

        t0 = time.perf_counter()
        recovered = await consumer.swarm_fetch(recipe.root_hash)
        t1 = time.perf_counter()

        elapsed_sec = t1 - t0
        print(f"\n[Benchmark] Multi-Node Swarm Fetch under 20% Loss: {elapsed_sec:.3f} s ({payload_size/1024:.0f} KB)")
        assert recovered == payload
        assert elapsed_sec < 3.0, f"Swarm fetch under loss took {elapsed_sec:.3f} s, exceeding 3.0 s baseline"

    def test_node_fetch_loss_recovery_latency(self):
        """
        Benchmark single-node fountain fetch & reconstruction latency on 30KB payload under 25% loss.
        Baseline threshold: Recovery time < 3.0 seconds.
        """
        payload_size = 30 * 1024  # 30 KB
        payload = os.urandom(payload_size)
        engine = TFPNode()
        recipe = engine.publish(payload)

        t0 = time.perf_counter()
        recovered = engine.fetch(recipe.root_hash, simulated_loss=0.25)
        t1 = time.perf_counter()

        elapsed_sec = t1 - t0
        print(f"\n[Benchmark] Node Fetch Recovery under 25% Loss: {elapsed_sec:.3f} s")
        assert recovered == payload
        assert elapsed_sec < 3.0, f"Recovery latency {elapsed_sec:.3f} s exceeded 3.0 s baseline"
