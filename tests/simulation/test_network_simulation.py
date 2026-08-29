# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Network Simulation & Fault Injection Test Suite

Covers:
1. Multi-node mesh topology creation and routing (linear, star, ring, full-mesh).
2. Dynamic latency, packet jitter, and loss injection (0% to 50% drop rates).
3. Random node churn, crash, and mid-stream origin death survival.
4. Network split-brain partition and post-partition healing recovery validation.
5. Virtual device hardware decay and chaos physics integration.
"""

import asyncio
import hashlib
import random
import time
from typing import Dict, List, Set
import pytest

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


# ==============================================================================
# 1. Multi-Node Mesh Topology & Routing
# ==============================================================================

@pytest.mark.simulation
@pytest.mark.asyncio
class TestMeshTopologyAndRouting:
    """Validate multi-node topology generation and message routing across diverse topologies."""

    async def test_linear_mesh_routing_and_ttl_propagation(self):
        """Test multi-hop gossip propagation through a 5-node linear chain (N1 -> N2 -> N3 -> N4 -> N5)."""
        net = SwarmNetwork()
        nodes = [net.add_peer(f"linear_node_{i}", loss_rate=0.0) for i in range(5)]

        # Connect linearly
        for i in range(len(nodes) - 1):
            nodes[i].connect(nodes[i + 1])

        # Publish content at origin (node 0)
        node_engine = TFPNode(node_id="engine_0")
        test_payload = b"LINEAR_TOPOLOGY_TEST_VECTOR_DATA_CHAIN_" * 20
        recipe = node_engine.publish(test_payload)
        droplets = node_engine.droplet_store[recipe.root_hash]
        mtree = node_engine.merkle_trees[recipe.root_hash]

        nodes[0].store_content(recipe, droplets, mtree.root_hex)

        # Broadcast gossip with TTL=5 (enough to reach node 4)
        msg_id = hashlib.sha3_256(f"linear_gossip_{recipe.root_hash}".encode()).hexdigest()
        msg = GossipMessage(
            msg_id=msg_id,
            sender_id=nodes[0].node_id,
            recipe=recipe,
            merkle_root=mtree.root_hex,
            ttl=5,
        )
        nodes[0].seen_gossip.add(msg_id)
        for neighbor in nodes[0].neighbors:
            asyncio.create_task(neighbor.receive_gossip(msg))

        # Give async tasks time to propagate through 4 hops
        await asyncio.sleep(0.1)

        # Verify all nodes received recipe and Merkle root
        for i, peer in enumerate(nodes):
            assert recipe.root_hash in peer.known_recipes, f"Node {i} failed to receive gossip"
            assert peer.merkle_roots[recipe.root_hash] == mtree.root_hex

    async def test_star_topology_routing(self):
        """Test star topology with central hub routing to spoke nodes."""
        net = SwarmNetwork()
        hub = net.add_peer("star_hub", loss_rate=0.0)
        spokes = [net.add_peer(f"star_spoke_{i}", loss_rate=0.0) for i in range(6)]

        for spoke in spokes:
            spoke.connect(hub)

        # Spoke 0 publishes
        node_engine = TFPNode(node_id="spoke_pub")
        test_payload = b"STAR_TOPOLOGY_PAYLOAD_CONTENT_BROADCAST" * 15
        recipe = node_engine.publish(test_payload)
        droplets = node_engine.droplet_store[recipe.root_hash]
        mtree = node_engine.merkle_trees[recipe.root_hash]

        spokes[0].store_content(recipe, droplets, mtree.root_hex)
        await spokes[0].broadcast_gossip(recipe, mtree.root_hex)
        await asyncio.sleep(0.08)

        # Hub and all other spokes should learn about recipe
        assert recipe.root_hash in hub.known_recipes
        for i in range(1, 6):
            assert recipe.root_hash in spokes[i].known_recipes

    async def test_ring_topology_redundant_routing(self):
        """Test ring topology routing resilience when a single link in the ring fails."""
        net = SwarmNetwork()
        nodes = [net.add_peer(f"ring_node_{i}", loss_rate=0.0) for i in range(6)]

        # Connect in a ring: 0-1, 1-2, 2-3, 3-4, 4-5, 5-0
        for i in range(len(nodes)):
            nodes[i].connect(nodes[(i + 1) % len(nodes)])

        # Break the link between node 0 and node 1 by removing from neighbors
        nodes[0].neighbors.remove(nodes[1])
        nodes[1].neighbors.remove(nodes[0])

        # Publish at node 0
        node_engine = TFPNode(node_id="ring_pub")
        payload = b"RING_TOPOLOGY_FAILOVER_DATA_STRING" * 25
        recipe = node_engine.publish(payload)
        droplets = node_engine.droplet_store[recipe.root_hash]
        mtree = node_engine.merkle_trees[recipe.root_hash]

        nodes[0].store_content(recipe, droplets, mtree.root_hex)

        # Broadcast with TTL=8 to traverse 5 hops around the ring
        msg_id = hashlib.sha3_256(f"ring_gossip_{recipe.root_hash}".encode()).hexdigest()
        msg = GossipMessage(
            msg_id=msg_id,
            sender_id=nodes[0].node_id,
            recipe=recipe,
            merkle_root=mtree.root_hex,
            ttl=8,
        )
        nodes[0].seen_gossip.add(msg_id)
        for neighbor in nodes[0].neighbors:
            asyncio.create_task(neighbor.receive_gossip(msg))

        await asyncio.sleep(0.12)

        # Node 1 should still receive the gossip via the alternative path around the ring (0->5->4->3->2->1)
        assert recipe.root_hash in nodes[1].known_recipes
        assert nodes[1].known_recipes[recipe.root_hash].total_size == len(payload)

    async def test_full_mesh_interconnection_multi_source_swarm(self):
        """Test full mesh topology where multiple nodes seed parts of the content."""
        net = SwarmNetwork()
        nodes = [net.add_peer(f"mesh_peer_{i}", loss_rate=0.0) for i in range(5)]
        net.connect_all()

        node_engine = TFPNode()
        payload = b"FULL_MESH_SWARM_TEST_PAYLOAD_BYTES_" * 30
        recipe = node_engine.publish(payload)
        droplets = node_engine.droplet_store[recipe.root_hash]
        mtree = node_engine.merkle_trees[recipe.root_hash]

        # Seed distributed shards: node 0 has droplets 0..N/2, node 1 has N/2..N
        mid = len(droplets) // 2
        nodes[0].store_content(recipe, droplets[:mid], mtree.root_hex)
        nodes[1].store_content(recipe, droplets[mid:], mtree.root_hex)

        # Node 4 requests content
        nodes[4].known_recipes[recipe.root_hash] = recipe
        recovered = await nodes[4].swarm_fetch(recipe.root_hash)
        assert recovered == payload


# ==============================================================================
# 2. Dynamic Latency, Jitter, and Packet Loss Injection
# ==============================================================================

@pytest.mark.simulation
@pytest.mark.asyncio
class TestFaultInjectionAndLossTolerance:
    """Validate protocol behavior under simulated packet loss, latency jitter, and asymmetric drop channels."""

    @pytest.mark.parametrize("loss_rate", [0.0, 0.10, 0.25, 0.33, 0.50])
    async def test_fountain_resilience_under_loss_rates(self, loss_rate: float):
        """Verify rateless fountain reconstruction achieves 100% bit-exact recovery under various loss rates."""
        payload = (b"RESILIENCE_BENCHMARK_PAYLOAD_TEST_" + bytes([i % 256 for i in range(500)])) * 10
        engine = TFPNode(node_id=f"loss_node_{int(loss_rate*100)}")
        recipe = engine.publish(payload)

        # Fetch with simulated loss
        recovered = engine.fetch(recipe.root_hash, simulated_loss=loss_rate)
        assert recovered == payload
        assert len(recovered) == len(payload)
        assert hashlib.sha3_256(recovered).hexdigest() == hashlib.sha3_256(payload).hexdigest()

    async def test_asymmetric_peer_loss_swarm_transfer(self):
        """Test swarm retrieval when peers have varying asymmetric link loss rates."""
        net = SwarmNetwork()
        n_origin = net.add_peer("origin", loss_rate=0.0)
        n_lossy1 = net.add_peer("lossy_relay1", loss_rate=0.30)
        n_lossy2 = net.add_peer("lossy_relay2", loss_rate=0.20)
        n_clean = net.add_peer("clean_relay", loss_rate=0.05)
        n_consumer = net.add_peer("consumer", loss_rate=0.0)

        # Interconnect
        n_origin.connect(n_lossy1)
        n_origin.connect(n_lossy2)
        n_origin.connect(n_clean)
        n_consumer.connect(n_lossy1)
        n_consumer.connect(n_lossy2)
        n_consumer.connect(n_clean)

        payload = b"ASYMMETRIC_LOSS_CHANNEL_EXPERIMENT_DATA_" * 30
        engine = TFPNode(node_id="asymm_engine")
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        # Distribute droplets to all relays
        n_lossy1.store_content(recipe, droplets, mtree.root_hex)
        n_lossy2.store_content(recipe, droplets, mtree.root_hex)
        n_clean.store_content(recipe, droplets, mtree.root_hex)

        # Consumer learns recipe
        n_consumer.known_recipes[recipe.root_hash] = recipe

        # Consumer fetches across the multi-loss swarm
        recovered = await n_consumer.swarm_fetch(recipe.root_hash)
        assert recovered == payload

    async def test_packet_jitter_delayed_arrival(self):
        """Verify that simulated jitter and out-of-order droplet delivery do not impede rank accumulation."""
        codec = FountainCodec(symbol_size=128)
        data = b"JITTER_PACKET_STREAM_ORDER_INVARIANT_DATA_TESTING" * 16
        droplets, k, orig_len = codec.encode(data, redundancy=0.60)

        # Randomize droplet arrival order to simulate dynamic latency / packet jitter
        shuffled = list(droplets)
        random.seed(42)
        random.shuffle(shuffled)

        # Accumulate droplets one by one with jitter delays
        accumulated = []
        decoded = None
        for d in shuffled:
            accumulated.append(d)
            if len(accumulated) >= k:
                try:
                    decoded = codec.decode(accumulated, k=k, orig_len=orig_len)
                    break
                except ValueError:
                    continue

        assert decoded == data


# ==============================================================================
# 3. Node Churn and Crash Scenarios
# ==============================================================================

@pytest.mark.simulation
@pytest.mark.asyncio
class TestNodeChurnAndCrashScenarios:
    """Validate swarm survivability during abrupt origin node failure and peer churn."""

    async def test_mid_stream_origin_node_crash(self):
        """
        Verify that if the origin publisher crashes mid-stream after initial droplet dissemination,
        the remaining peers collaborate to reconstruct the full payload.
        """
        net = SwarmNetwork()
        origin = net.add_peer("origin_node", loss_rate=0.0)
        relay_a = net.add_peer("relay_a", loss_rate=0.10)
        relay_b = net.add_peer("relay_b", loss_rate=0.10)
        consumer = net.add_peer("consumer_target", loss_rate=0.0)

        origin.connect(relay_a)
        origin.connect(relay_b)
        relay_a.connect(consumer)
        relay_b.connect(consumer)

        payload = b"ORIGIN_CRASH_SURVIVAL_TRANSMISSION_PAYLOAD_" * 40
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        # Origin seeds droplets across relays before crashing
        relay_a.store_content(recipe, droplets, mtree.root_hex)
        relay_b.store_content(recipe, droplets, mtree.root_hex)
        consumer.known_recipes[recipe.root_hash] = recipe

        # ORIGIN CRASHES SUDDENLY
        origin.is_alive = False

        # Consumer fetches exclusively from relay_a and relay_b
        recovered = await consumer.swarm_fetch(recipe.root_hash)
        assert recovered == payload

    async def test_dynamic_node_churn_join_leave(self):
        """Simulate random node leaves and rejoins during a continuous query workflow."""
        net = SwarmNetwork()
        peers = [net.add_peer(f"churn_peer_{i}", loss_rate=0.05) for i in range(8)]
        net.connect_all()

        payload = b"DYNAMIC_NODE_CHURN_REPLICATION_CYCLE" * 20
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        # Seed content on first 4 peers
        for p in peers[:4]:
            p.store_content(recipe, droplets, mtree.root_hex)

        # Churn: kill 2 seeded peers and 1 unseeded peer
        peers[0].is_alive = False
        peers[1].is_alive = False
        peers[6].is_alive = False

        # Consumer is peer 7 (unseeded)
        peers[7].known_recipes[recipe.root_hash] = recipe

        # Fetch should succeed from remaining live peers (peers 2, 3)
        recovered = await peers[7].swarm_fetch(recipe.root_hash)
        assert recovered == payload

        # Rejoin peer 0 and verify it can now fetch as well
        peers[0].is_alive = True
        peers[0].reconstructed_payloads.clear()
        recovered_peer0 = await peers[0].swarm_fetch(recipe.root_hash)
        assert recovered_peer0 == payload


# ==============================================================================
# 4. Network Partition and Post-Partition Recovery
# ==============================================================================

@pytest.mark.simulation
@pytest.mark.asyncio
class TestNetworkPartitionAndRecovery:
    """Validate split-brain partition isolation and subsequent sync healing."""

    async def test_network_partition_and_healing(self):
        """
        Verify that:
        1. When network is partitioned into Partition A and Partition B via bridge failure,
           Partition B cannot retrieve content published in Partition A.
        2. When bridge is healed, gossip propagates and Partition B fully reconstructs the data.
        """
        net = SwarmNetwork()

        # Partition A
        a1 = net.add_peer("node_a1", loss_rate=0.0)
        a2 = net.add_peer("node_a2", loss_rate=0.05)
        a3 = net.add_peer("node_a3", loss_rate=0.05)
        a1.connect(a2)
        a2.connect(a3)

        # Bridge Node
        bridge = net.add_peer("bridge_gateway", loss_rate=0.0)
        a3.connect(bridge)

        # Partition B
        b1 = net.add_peer("node_b1", loss_rate=0.05)
        b2 = net.add_peer("node_b2", loss_rate=0.0)
        bridge.connect(b1)
        b1.connect(b2)

        # Publish content exclusively in Partition A (on node a1)
        payload = b"PARTITION_ISOLATION_AND_RECOVERY_VALIDATION_" * 35
        engine = TFPNode()
        recipe = engine.publish(payload)
        droplets = engine.droplet_store[recipe.root_hash]
        mtree = engine.merkle_trees[recipe.root_hash]

        a1.store_content(recipe, droplets, mtree.root_hex)

        # PARTITION: Sever the bridge
        bridge.is_alive = False

        # Broadcast gossip within Partition A
        await a1.broadcast_gossip(recipe, mtree.root_hex)
        await asyncio.sleep(0.06)

        # Verify Partition A has the recipe
        assert recipe.root_hash in a2.known_recipes
        assert recipe.root_hash in a3.known_recipes

        # Verify Partition B does NOT know about the recipe
        assert recipe.root_hash not in b1.known_recipes
        assert recipe.root_hash not in b2.known_recipes

        # Attempting fetch on Partition B during partition must fail
        with pytest.raises(KeyError):
            await b2.swarm_fetch(recipe.root_hash)

        # HEAL PARTITION: Restore the bridge gateway
        bridge.is_alive = True

        # Re-broadcast gossip across the healed bridge
        await a3.broadcast_gossip(recipe, mtree.root_hex)
        await asyncio.sleep(0.08)

        # Partition B nodes now receive the gossip
        assert recipe.root_hash in b1.known_recipes
        assert recipe.root_hash in b2.known_recipes

        # Partition B node b2 now fetches droplets across the healed bridge
        bridge.store_content(recipe, droplets, mtree.root_hex)
        b1.store_content(recipe, droplets, mtree.root_hex)

        recovered = await b2.swarm_fetch(recipe.root_hash)
        assert recovered == payload


# ==============================================================================
# 5. Virtual Device Hardware & Chaos Simulation Integration
# ==============================================================================

@pytest.mark.simulation
class TestVirtualDeviceChaosSimulation:
    """Validate stateful virtual device thermal decay and orchestrator fault injection."""

    def test_virtual_device_thermal_decay_and_cooling(self):
        """Verify device temperature increases under compute load and cools down during idle."""
        specs = HardwareSpecs(
            device_id="sim_phone_01",
            cpu_cores=8,
            ram_gb=8.0,
            battery_capacity_mah=4500,
            max_temp_celsius=65.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=100.0,
        )
        device = VirtualDevice(specs)
        initial_temp = device.state.current_temp_celsius
        initial_battery = device.state.battery_level_pct

        # Assign a computing task
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 80.0

        # Simulate 10 seconds of heavy compute
        device.tick(10.0)
        assert device.state.current_temp_celsius > initial_temp
        assert device.state.battery_level_pct < initial_battery

        # Set to idle and simulate cooling
        temp_after_compute = device.state.current_temp_celsius
        device.state.state = DeviceState.IDLE
        device.state.current_load_pct = 0.0
        device.tick(10.0)
        assert device.state.current_temp_celsius < temp_after_compute

    def test_chaos_orchestrator_targeted_faults(self):
        """Verify ChaosOrchestrator can inject targeted node crash and malicious actor events."""
        devices = [
            VirtualDevice(
                HardwareSpecs(
                    device_id=f"chaos_node_{i}",
                    cpu_cores=4,
                    ram_gb=4.0,
                    battery_capacity_mah=4000,
                    max_temp_celsius=60.0,
                    is_tee_enabled=True,
                    network_bandwidth_mbps=50.0,
                )
            )
            for i in range(5)
        ]
        orchestrator = ChaosOrchestrator(devices, ChaosConfig(probability_crash=0.0))

        # Crash a specific node
        orchestrator.add_chaos_event(ChaosEvent.NODE_CRASH, target_ids=["chaos_node_2"])
        assert devices[2].state.state == DeviceState.OFFLINE
        # Other nodes should remain alive
        assert devices[0].state.state == DeviceState.IDLE
        assert devices[1].state.state == DeviceState.IDLE

        # Inject malicious actor
        orchestrator.add_chaos_event(ChaosEvent.MALICIOUS_ACTOR)
        malicious_count = sum(1 for d in devices if d.specs.honesty_factor < 1.0)
        assert malicious_count >= 1
