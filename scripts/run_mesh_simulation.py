#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Interactive Simulation: Offline Community Wi-Fi Mesh with Cooperative Swarm Repair.

Demonstrates how mobile edge nodes and community gateways in an offline village
or campus recover complete content after an upstream broadcast tower cuts off,
using peer-to-peer droplet reconciliation with zero internet connectivity.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import sys
import time

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_core_v4.cdc import ContentDefinedChunker
from tfp_core_v4.fountain import FountainCodec
from tfp_core_v4.mesh import MeshPeer, SwarmNetwork
from tfp_client.lib.mesh.gateway import MeshGatewayNode
from tfp_client.lib.mesh.peer_sync import PeerSyncManager


async def run_simulation():
    print("=" * 70)
    print("   THE FOUNDATION PROTOCOL: OFFLINE COMMUNITY MESH SIMULATION")
    print("=" * 70)
    print("Scenario: Village Community Network with Sudden Broadcast Tower Failure")
    print("-" * 70)

    # 1. Prepare sample emergency medical manual
    doc_text = (
        "THE FOUNDATION PROTOCOL: EMERGENCY MEDICAL & DISASTER MANUAL\n"
        "SECTION 1: TRIAGE & WATER PURIFICATION GUIDELINES\n"
        "1.1 Water Disinfection: Boil at rolling boil for 1 min (3 min above 2000m).\n"
        "1.2 Sodium Hypochlorite: 2 drops 5% unscented household bleach per liter.\n"
        "1.3 Oral Rehydration Solution: 6 level tsp sugar + 0.5 tsp salt per 1L water.\n"
        "SECTION 2: FIELD HYPOTHERMIA & TRAUMA PROTOCOLS\n"
        "2.1 Rapid assessment: Airway, Breathing, Circulation, Disability, Exposure.\n"
    ) * 16  # ~4.8 KB payload

    payload = doc_text.encode("utf-8")
    expected_hash = hashlib.sha3_256(payload).hexdigest()
    print(f"Content Payload : {len(payload)} bytes (SHA3: {expected_hash[:16]}...)")

    # 2. Package and encode with FountainCodec
    chunker = ContentDefinedChunker(min_size=1024, target_size=2048, max_size=4096)
    recipe, _ = chunker.create_recipe(payload)
    codec = FountainCodec(symbol_size=128)
    droplets, k, orig_len = codec.encode(payload, redundancy=0.60)
    total_droplets = len(droplets)
    print(f"Fountain Slicing: K={k} source symbols, {total_droplets} total droplets (60% repair margin)")

    # 3. Build Mesh Topology
    net = SwarmNetwork()
    gateway = MeshGatewayNode("gateway_clinic", symbol_size=128)
    alice = net.add_peer("peer_alice", symbol_size=128)
    bob = net.add_peer("peer_bob", symbol_size=128)
    charlie = net.add_peer("peer_charlie", symbol_size=128)

    # Wi-Fi topology: Gateway <-> Alice <-> Bob <-> Charlie
    gateway.connect(alice)
    alice.connect(bob)
    bob.connect(charlie)
    print("\nAd-Hoc Wi-Fi Links Established: [Gateway] <-> [Alice] <-> [Bob] <-> [Charlie]")

    # 4. Simulate Partial Broadcast from Tower before Sudden Dropout
    print("\n[EVENT] Upstream Tower begins unidirectional transmission...")
    # Gateway receives 70% of droplets
    gateway.store_content(recipe, droplets[: int(total_droplets * 0.70)], "root")
    # Alice receives the first 40% (seeds 0..N)
    alice.store_content(recipe, droplets[: int(total_droplets * 0.40)], "root")
    # Bob receives the middle 40% (seeds N/2..3N/2)
    start_b = int(total_droplets * 0.30)
    end_b = int(total_droplets * 0.70)
    bob.store_content(recipe, droplets[start_b:end_b], "root")
    # Charlie receives only the tail 25% (seeds 3N/4..end)
    charlie.store_content(recipe, droplets[int(total_droplets * 0.75):], "root")

    print(f"  - Gateway received: {len(gateway.droplet_store[recipe.root_hash])}/{total_droplets} droplets")
    print(f"  - Alice   received: {len(alice.droplet_store[recipe.root_hash])}/{total_droplets} droplets (need {k})")
    print(f"  - Bob     received: {len(bob.droplet_store[recipe.root_hash])}/{total_droplets} droplets (need {k})")
    print(f"  - Charlie received: {len(charlie.droplet_store[recipe.root_hash])}/{total_droplets} droplets (need {k})")

    print("\n[ALERT] Upstream Tower connection CUT OFF! Internet is completely offline.")
    print("None of the mobile edge nodes have enough droplets to decode independently.")

    # 5. Cooperative Peer-to-Peer Reconciliation Phase
    print("\n[MESH PHASE 1] Alice and Bob initiate peer-to-peer Wi-Fi reconciliation...")
    a_to_b, b_to_a = await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    print(f"  -> Alice sent {a_to_b} missing droplets to Bob")
    print(f"  -> Bob sent {b_to_a} missing droplets to Alice")

    print("\n[MESH PHASE 2] Bob and Charlie reconcile...")
    b_to_c, c_to_b = await PeerSyncManager.reconcile(bob, charlie, recipe.root_hash)
    print(f"  -> Bob sent {b_to_c} missing droplets to Charlie")
    print(f"  -> Charlie sent {c_to_b} missing droplets to Bob")

    print("\n[MESH PHASE 3] Gateway clinic node broadcasts complementary shards...")
    g_to_a, _ = await PeerSyncManager.reconcile(gateway, alice, recipe.root_hash)
    print(f"  -> Gateway supplied {g_to_a} missing droplets to Alice")
    await PeerSyncManager.reconcile(alice, bob, recipe.root_hash)
    await PeerSyncManager.reconcile(bob, charlie, recipe.root_hash)

    # 6. Verify Node Reconstructions
    print("\n" + "=" * 70)
    print("                    RECONSTRUCTION RESULTS")
    print("=" * 70)

    nodes = [("Gateway", gateway), ("Alice", alice), ("Bob", bob), ("Charlie", charlie)]
    all_success = True

    for name, peer in nodes:
        held = list(peer.droplet_store[recipe.root_hash].values())
        try:
            recovered = codec.decode(held, k=k, orig_len=orig_len)
            is_match = (hashlib.sha3_256(recovered).hexdigest() == expected_hash)
            status = "SUCCESS (BIT-EXACT MATCH)" if is_match else "CORRUPTED"
            if not is_match:
                all_success = False
        except Exception as e:
            status = f"FAILED ({e})"
            all_success = False

        print(f"  Node {name:<10}: Held {len(held):>2} droplets | Status: {status}")

    print("=" * 70)
    if all_success:
        print("  ALL 4 COMMUNITY NODES RESTORED 100% BIT-EXACT DATA COMPLETELY OFFLINE!")
    else:
        print("  SIMULATION FAILED: Incomplete reconstruction.")
    print("=" * 70)
    return all_success


def main():
    success = asyncio.run(run_simulation())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
