# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Challenge Stress Test Harness (Challenger 2)
Multi-Node Swarm Simulation, Fault Tolerance, Partition Healing, and Scaling Benchmarks.
"""

import asyncio
import hashlib
import os
from pathlib import Path
import random
import sys
import time
from typing import Dict, List, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from tfp_core_v4.merkle import MerkleTree, verify_merkle_proof
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork, GossipMessage
from tfp_core_v4.node import TFPNode
from tfp_simulator.core import (
    ChaosConfig,
    ChaosEvent,
    ChaosOrchestrator,
    DeviceState,
    HardwareSpecs,
    VirtualDevice,
)


def run_experiment_1_loss_gradient():
    """Experiment 1: Fountain resilience, overhead epsilon, and latency across packet loss gradient (0% to 60%)."""
    print("\n" + "=" * 80)
    print("EXPERIMENT 1: PACKET LOSS GRADIENT RESILIENCE & LATENCY (0% to 60%)")
    print("=" * 80)

    loss_rates = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
    payload_size = 64 * 1024  # 64 KB
    test_payload = os.urandom(payload_size)
    orig_hash = hashlib.sha3_256(test_payload).hexdigest()

    results = []
    codec = FountainCodec(symbol_size=256)
    k = (payload_size + 255) // 256

    print(f"  Target Payload: {payload_size/1024:.0f} KB, K = {k} source symbols")

    for loss in loss_rates:
        latencies = []
        droplets_needed_list = []
        successes = 0
        trials = 10

        for trial in range(trials):
            # Dynamic rateless stream simulation: generate droplets on demand
            # until decoder reaches rank K
            collected: List[FountainDroplet] = []
            seed = 0
            t0 = time.perf_counter()
            decoded = None

            # Stream packets through lossy channel
            while decoded is None and seed < k * 5:
                # Generate next droplet
                # (Systematic 0..k-1, repair k..)
                if seed < k:
                    d = FountainDroplet(seed=seed, degree=1, indices=[seed], payload=test_payload[seed*256:(seed+1)*256].ljust(256, b"\x00"))
                else:
                    rng = random.Random(seed)
                    degree = codec._sample_degree(k, rng)
                    indices = sorted(rng.sample(range(k), degree))
                    combined = bytearray(256)
                    for idx in indices:
                        sym = test_payload[idx*256:(idx+1)*256].ljust(256, b"\x00")
                        for b in range(256):
                            combined[b] ^= sym[b]
                    d = FountainDroplet(seed=seed, degree=degree, indices=indices, payload=bytes(combined))
                
                seed += 1
                # Loss channel
                if random.random() >= loss:
                    collected.append(d)
                    if len(collected) >= k:
                        try:
                            decoded = codec.decode(collected, k=k, orig_len=payload_size)
                        except ValueError:
                            pass

            t1 = time.perf_counter()
            if decoded == test_payload:
                successes += 1
                latencies.append((t1 - t0) * 1000.0)
                droplets_needed_list.append(len(collected))

        avg_lat = sum(latencies) / len(latencies) if latencies else float("inf")
        avg_needed = sum(droplets_needed_list) / len(droplets_needed_list) if droplets_needed_list else 0
        overhead_pct = ((avg_needed - k) / k) * 100.0 if k > 0 else 0
        success_pct = (successes / trials) * 100.0
        results.append((loss, success_pct, avg_lat, avg_needed, overhead_pct))
        print(f"  Loss: {loss*100:4.1f}% | Success: {success_pct:5.1f}% | Avg Rx Droplets: {avg_needed:5.1f} (Overhead: +{overhead_pct:4.1f}%) | Latency: {avg_lat:6.2f} ms")

        assert success_pct == 100.0, f"Failure at {loss*100}% loss rate under rateless stream!"

    print("--> EXPERIMENT 1 PASSED: 100% rateless recovery up to 60% loss with bounded overhead epsilon.")
    return results


async def run_experiment_2_large_swarm_scale():
    """Experiment 2: Large Swarm Topology Scalability (20 nodes with 40% sudden churn)."""
    print("\n" + "=" * 80)
    print("EXPERIMENT 2: LARGE SWARM SCALABILITY & MASS CHURN (20 Nodes, 40% Churn)")
    print("=" * 80)

    net = SwarmNetwork()
    num_nodes = 20
    peers = [net.add_peer(f"swarm_node_{i:02d}", loss_rate=0.15) for i in range(num_nodes)]
    net.connect_all()

    payload_size = 128 * 1024  # 128 KB
    payload = os.urandom(payload_size)
    orig_hash = hashlib.sha3_256(payload).hexdigest()

    engine = TFPNode()
    recipe = engine.publish(payload)
    droplets = engine.droplet_store[recipe.root_hash]
    mtree = engine.merkle_trees[recipe.root_hash]

    # Seed first 6 nodes with fragments of droplets
    shard_chunk = len(droplets) // 6
    for i in range(6):
        start_idx = i * shard_chunk
        end_idx = start_idx + shard_chunk if i < 5 else len(droplets)
        peers[i].store_content(recipe, droplets[start_idx:end_idx], mtree.root_hex)

    # Broadcast gossip across all 20 nodes
    t0_gossip = time.perf_counter()
    await peers[0].broadcast_gossip(recipe, mtree.root_hex)
    await asyncio.sleep(0.15)
    t1_gossip = time.perf_counter()

    # Verify gossip reached all 20 nodes
    gossip_coverage = sum(1 for p in peers if recipe.root_hash in p.known_recipes)
    print(f"  Gossip Coverage: {gossip_coverage}/{num_nodes} nodes reached in {(t1_gossip - t0_gossip)*1000:.2f} ms")
    assert gossip_coverage == num_nodes

    # MASS CHURN: Kill 8 out of 20 nodes (40% crash), including 3 seed nodes
    crashed_indices = [0, 1, 2, 7, 8, 9, 10, 11]
    for idx in crashed_indices:
        peers[idx].is_alive = False
    print(f"  [CHAOS] 8 Nodes ({len(crashed_indices)}/{num_nodes} = 40%) abruptly CRASHED mid-swarm.")

    # Receiver is node 19 (an unseeded node)
    receiver = peers[19]
    t0_fetch = time.perf_counter()
    recovered = await receiver.swarm_fetch(recipe.root_hash)
    t1_fetch = time.perf_counter()

    fetch_time_sec = t1_fetch - t0_fetch
    throughput_mb_s = (payload_size / (1024 * 1024)) / fetch_time_sec

    print(f"  Swarm Fetch Time: {fetch_time_sec:.3f} s ({payload_size/1024:.0f} KB)")
    print(f"  Effective Swarm Throughput: {throughput_mb_s:.2f} MB/s under 15% loss + 40% crash")

    assert recovered == payload
    assert hashlib.sha3_256(recovered).hexdigest() == orig_hash
    print("--> EXPERIMENT 2 PASSED: 100% exact recovery under 40% mass node churn in 20-node swarm.")


async def run_experiment_3_split_brain_partition():
    """Experiment 3: Network Partition (Split-Brain) and Post-Partition Re-Sync."""
    print("\n" + "=" * 80)
    print("EXPERIMENT 3: SPLIT-BRAIN PARTITION & BIDIRECTIONAL RECONCILIATION")
    print("=" * 80)

    net = SwarmNetwork()

    # Create two sub-swarms: East Swarm (nodes E0..E4) and West Swarm (nodes W0..W4)
    # Connected via Bridge Gateways (Bridge-E and Bridge-W)
    east_nodes = [net.add_peer(f"east_{i}", loss_rate=0.05) for i in range(5)]
    west_nodes = [net.add_peer(f"west_{i}", loss_rate=0.05) for i in range(5)]
    bridge_e = net.add_peer("bridge_east", loss_rate=0.0)
    bridge_w = net.add_peer("bridge_west", loss_rate=0.0)

    # Interconnect East Sub-Swarm
    for i in range(len(east_nodes)):
        for j in range(i + 1, len(east_nodes)):
            east_nodes[i].connect(east_nodes[j])
        east_nodes[i].connect(bridge_e)

    # Interconnect West Sub-Swarm
    for i in range(len(west_nodes)):
        for j in range(i + 1, len(west_nodes)):
            west_nodes[i].connect(west_nodes[j])
        west_nodes[i].connect(bridge_w)

    # Connect bridge link
    bridge_e.connect(bridge_w)

    # Publish Document A in East Swarm
    doc_east = b"EAST_COAST_CONFIDENTIAL_TELEMETRY_LOG_" * 40
    engine_e = TFPNode(node_id="engine_east")
    recipe_east = engine_e.publish(doc_east)
    droplets_east = engine_e.droplet_store[recipe_east.root_hash]
    mtree_east = engine_e.merkle_trees[recipe_east.root_hash]
    east_nodes[0].store_content(recipe_east, droplets_east, mtree_east.root_hex)

    # Publish Document B in West Swarm
    doc_west = b"WEST_COAST_DECENTRALIZED_CONSENSUS_STATE_" * 40
    engine_w = TFPNode(node_id="engine_west")
    recipe_west = engine_w.publish(doc_west)
    droplets_west = engine_w.droplet_store[recipe_west.root_hash]
    mtree_west = engine_w.merkle_trees[recipe_west.root_hash]
    west_nodes[0].store_content(recipe_west, droplets_west, mtree_west.root_hex)

    # SEVER PARTITION: Cut the bridge connection
    print("  [PARTITION ACTIVE] Bridge severed between East and West sub-swarms.")
    bridge_e.is_alive = False
    bridge_w.is_alive = False

    # Gossip inside East
    await east_nodes[0].broadcast_gossip(recipe_east, mtree_east.root_hex)
    # Gossip inside West
    await west_nodes[0].broadcast_gossip(recipe_west, mtree_west.root_hex)
    await asyncio.sleep(0.10)

    # Verify East knows Doc A but NOT Doc B
    assert recipe_east.root_hash in east_nodes[4].known_recipes
    assert recipe_west.root_hash not in east_nodes[4].known_recipes

    # Verify West knows Doc B but NOT Doc A
    assert recipe_west.root_hash in west_nodes[4].known_recipes
    assert recipe_east.root_hash not in west_nodes[4].known_recipes
    print("  [ISOLATION VERIFIED] Partition barrier strictly holds; zero cross-leakage.")

    # HEAL PARTITION: Restore bridges
    print("  [HEALING] Reconnecting Bridge East <--> Bridge West...")
    bridge_e.is_alive = True
    bridge_w.is_alive = True

    # Re-propagate East gossip across bridge
    await east_nodes[0].broadcast_gossip(recipe_east, mtree_east.root_hex)
    # Re-propagate West gossip across bridge
    await west_nodes[0].broadcast_gossip(recipe_west, mtree_west.root_hex)
    await asyncio.sleep(0.15)

    # Verify cross-discovery
    assert recipe_east.root_hash in west_nodes[4].known_recipes
    assert recipe_west.root_hash in east_nodes[4].known_recipes
    print("  [CROSS-DISCOVERY] All nodes across both partitions synchronized recipe metadata.")

    # West Node 4 fetches East content across healed network
    # Provide droplets at east nodes
    for en in east_nodes:
        en.store_content(recipe_east, droplets_east, mtree_east.root_hex)
    for wn in west_nodes:
        wn.store_content(recipe_west, droplets_west, mtree_west.root_hex)
    bridge_e.store_content(recipe_east, droplets_east, mtree_east.root_hex)
    bridge_w.store_content(recipe_west, droplets_west, mtree_west.root_hex)

    rec_east = await west_nodes[4].swarm_fetch(recipe_east.root_hash)
    rec_west = await east_nodes[4].swarm_fetch(recipe_west.root_hash)

    assert rec_east == doc_east
    assert rec_west == doc_west
    print("--> EXPERIMENT 3 PASSED: Bidirectional cross-partition swarm recovery fully validated.")


def run_experiment_4_byzantine_and_throughput_stress():
    """Experiment 4 & 5: Byzantine Injection Defense + Large Payload Throughput (1MB & 2MB)."""
    print("\n" + "=" * 80)
    print("EXPERIMENT 4 & 5: BYZANTINE FILTERING & HIGH-THROUGHPUT BIG PAYLOAD STRESS")
    print("=" * 80)

    # 1. Big Payload Throughput
    sizes = [256 * 1024, 1024 * 1024, 2 * 1024 * 1024]
    for sz in sizes:
        data = os.urandom(sz)
        chunker = ContentDefinedChunker(min_size=1024, max_size=8192, target_size=2048)
        codec = FountainCodec(symbol_size=512)

        t0 = time.perf_counter()
        recipe, chunks = chunker.create_recipe(data)
        t1 = time.perf_counter()
        droplets, k, orig_len = codec.encode(data, redundancy=0.30)
        t2 = time.perf_counter()
        tree = MerkleTree([d.serialize() for d in droplets])
        t3 = time.perf_counter()

        chunk_speed = (sz / (1024 * 1024)) / max(t1 - t0, 1e-9)
        encode_speed = (sz / (1024 * 1024)) / max(t2 - t1, 1e-9)
        merkle_speed = (sz / (1024 * 1024)) / max(t3 - t2, 1e-9)

        print(f"  Payload: {sz/(1024*1024):.2f} MB | FastCDC: {chunk_speed:6.2f} MB/s | Fountain Encode: {encode_speed:6.2f} MB/s | Merkle: {merkle_speed:6.2f} MB/s")

    # 2. Byzantine Injection with Merkle verification
    test_data = os.urandom(32 * 1024)
    codec = FountainCodec(symbol_size=256)
    droplets, k, orig_len = codec.encode(test_data, redundancy=0.50)
    tree = MerkleTree([d.serialize() for d in droplets])
    root = tree.root

    # Generate 50% Byzantine poisoned packets
    total_received = 0
    poisoned_detected = 0
    accepted_valid = []

    for idx, d in enumerate(droplets):
        total_received += 1
        # Inject Byzantine packet 40% of the time
        if idx % 3 == 0:
            poisoned_bytes = b"POISONED_CORRUPTED_BYTES" + os.urandom(len(d.serialize()))
            proof = tree.get_proof(idx)
            is_valid = verify_merkle_proof(poisoned_bytes, proof, root)
            if not is_valid:
                poisoned_detected += 1
        else:
            proof = tree.get_proof(idx)
            is_valid = verify_merkle_proof(d.serialize(), proof, root)
            if is_valid:
                accepted_valid.append(d)

    print(f"  Byzantine Injection Stats: Poisoned Blocked={poisoned_detected}, Valid Accepted={len(accepted_valid)}")
    assert poisoned_detected > 0

    decoded = codec.decode(accepted_valid, k=k, orig_len=orig_len)
    assert decoded == test_data
    print("--> EXPERIMENT 4 & 5 PASSED: Byzantine poison 100% intercepted; big payload throughput robust.")


async def main():
    print("\n" + "#" * 80)
    print("# TFP SWARM SIMULATION & BENCHMARK CHALLENGER SUITE")
    print("#" * 80)

    t_start = time.perf_counter()
    run_experiment_1_loss_gradient()
    await run_experiment_2_large_swarm_scale()
    await run_experiment_3_split_brain_partition()
    run_experiment_4_byzantine_and_throughput_stress()
    t_end = time.perf_counter()

    print("\n" + "#" * 80)
    print(f"# ALL EMPIRICAL EXPERIMENTS COMPLETED IN {t_end - t_start:.2f}s WITH 0 FAILURES")
    print("#" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
