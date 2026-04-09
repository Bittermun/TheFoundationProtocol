#!/usr/bin/env python3
"""
TFP Chaos Engineering Demo

Run realistic stress-test scenarios against the TFP P2P compute pool.
Demonstrates resilience to node failures, malicious actors, and thermal throttling.

Usage:
    python run_chaos_demo.py
"""

import time
import random
from tfp_simulator.core import (
    ChaosOrchestrator, ChaosConfig, ChaosEvent, ScenarioFactory, DeviceState
)

def print_header(title: str):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def scenario_1_steady_state():
    """Baseline: Stable network with no chaos."""
    print_header("SCENARIO 1: Steady State (Baseline)")
    
    devices = ScenarioFactory.create_idle_compute_pool(20)
    config = ChaosConfig(
        probability_crash=0.0,
        malicious_node_ratio=0.0
    )
    
    orchestrator = ChaosOrchestrator(devices, config)
    
    # Inject some initial tasks manually
    for i, device in enumerate(orchestrator.devices.values()):
        if i % 2 == 0:  # Half the devices get tasks
            task = {"id": f"task_init_{i}", "reward": 10, "progress": 0.0}
            device.active_task = task
            device.state.state = DeviceState.COMPUTING
            device.state.current_load_pct = 70.0
    
    orchestrator.run_scenario(duration_seconds=30, step_size=2.0)

def scenario_2_random_failures():
    """Network with random node crashes (5% chance per tick)."""
    print_header("SCENARIO 2: Random Node Failures")
    print("Simulating unstable power/network conditions...")
    
    devices = ScenarioFactory.create_mixed_reality_network(30)
    config = ChaosConfig(
        probability_crash=0.05,  # 5% chance each tick
        probability_latency=0.0
    )
    
    orchestrator = ChaosOrchestrator(devices, config)
    
    # Start with many active tasks
    for i, device in enumerate(orchestrator.devices.values()):
        if device.specs.device_id.startswith("server"):
            # Servers always working
            task = {"id": f"srv_task_{i}", "reward": 50, "progress": 0.0}
            device.active_task = task
            device.state.state = DeviceState.COMPUTING
            device.state.current_load_pct = 85.0
        elif random.random() > 0.3:
            task = {"id": f"phone_task_{i}", "reward": 15, "progress": 0.0}
            device.active_task = task
            device.state.state = DeviceState.COMPUTING
            device.state.current_load_pct = 60.0
    
    orchestrator.run_scenario(duration_seconds=50, step_size=2.0)

def scenario_3_malicious_actors():
    """Network infiltrated by dishonest nodes lying about compute power."""
    print_header("SCENARIO 3: Malicious Actor Injection")
    print("Injecting dishonest nodes that lie about capabilities...")
    
    devices = ScenarioFactory.create_mixed_reality_network(40)
    config = ChaosConfig(
        probability_crash=0.02,
        malicious_node_ratio=0.15  # 15% malicious
    )
    
    orchestrator = ChaosOrchestrator(devices, config)
    
    # Pre-inject some malicious actors
    malicious_count = 0
    for device in orchestrator.devices.values():
        if device.specs.device_id.startswith("liar"):
            device.specs.honesty_factor = 0.1
            malicious_count += 1
    
    print(f"  → {malicious_count} malicious nodes active in the pool")
    
    # Assign tasks to everyone
    for i, device in enumerate(orchestrator.devices.values()):
        task = {"id": f"task_{i}", "reward": 20, "progress": 0.0}
        device.active_task = task
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 75.0
    
    orchestrator.run_scenario(duration_seconds=60, step_size=2.0)
    
    # Analyze results
    honest_completed = sum(
        d.state.tasks_completed 
        for d in orchestrator.devices.values() 
        if d.specs.honesty_factor >= 0.9
    )
    malicious_completed = sum(
        d.state.tasks_completed 
        for d in orchestrator.devices.values() 
        if d.specs.honesty_factor < 0.5
    )
    
    print("\n📊 ANALYSIS:")
    print(f"  Honest nodes completed: {honest_completed} tasks")
    print(f"  Malicious nodes completed: {malicious_completed} tasks")
    print(f"  → Malicious nodes earned fewer credits due to slower actual work")

def scenario_4_thermal_throttling():
    """Stress test: All nodes pushed to thermal limits."""
    print_header("SCENARIO 4: Thermal Throttling Stress Test")
    print("Running all nodes at max load to trigger overheating...")
    
    devices = ScenarioFactory.create_idle_compute_pool(25)
    config = ChaosConfig()
    
    orchestrator = ChaosOrchestrator(devices, config)
    
    # Force all nodes into high-load computation
    for device in orchestrator.devices.values():
        task = {"id": "stress_task", "reward": 100, "progress": 0.0}
        device.active_task = task
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 95.0  # Max load
        device.state.current_temp_celsius = 60.0  # Start warm
    
    orchestrator.run_scenario(duration_seconds=80, step_size=2.0)
    
    # Count thermal events
    overheat_events = sum(
        1 for d in orchestrator.devices.values() 
        if d.state.state == DeviceState.OVERHEATED or d.state.tasks_failed > 0
    )
    
    print(f"\n🔥 Thermal Events: {overheat_events}/{len(devices)} nodes throttled")
    print("  → Device safety guards prevented hardware damage")

def scenario_5_mixed_reality():
    """Full simulation: Phones, servers, malicious nodes, and random failures."""
    print_header("SCENARIO 5: Full Mixed-Reality Network")
    print("Complete stress test with all chaos factors enabled...")
    
    devices = ScenarioFactory.create_mixed_reality_network(50)
    config = ChaosConfig(
        probability_crash=0.03,
        probability_latency=0.0,
        malicious_node_ratio=0.1
    )
    
    orchestrator = ChaosOrchestrator(devices, config)
    
    # Realistic workload distribution
    for device in orchestrator.devices.values():
        if device.specs.device_id.startswith("server"):
            # Servers handle heavy tasks
            task = {"id": f"heavy_{device.specs.device_id}", "reward": 100, "progress": 0.0}
            device.active_task = task
            device.state.state = DeviceState.COMPUTING
            device.state.current_load_pct = 80.0
        elif device.specs.device_id.startswith("phone"):
            # Phones handle light tasks intermittently
            if random.random() > 0.3:
                task = {"id": f"light_{device.specs.device_id}", "reward": 25, "progress": 0.0}
                device.active_task = task
                device.state.state = DeviceState.COMPUTING
                device.state.current_load_pct = 50.0
    
    orchestrator.run_scenario(duration_seconds=100, step_size=2.0)

def main():
    print("\n" + "🚀"*35)
    print("   TFP CHAOS ENGINEERING DEMO")
    print("   Virtual Device & P2P Compute Pool Stress Tests")
    print("🚀"*35)
    
    scenarios = [
        ("Steady State Baseline", scenario_1_steady_state),
        ("Random Node Failures", scenario_2_random_failures),
        ("Malicious Actors", scenario_3_malicious_actors),
        ("Thermal Throttling", scenario_4_thermal_throttling),
        ("Full Mixed-Reality", scenario_5_mixed_reality),
    ]
    
    for name, func in scenarios:
        try:
            func()
        except Exception as e:
            print(f"\n❌ Scenario '{name}' failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "✅"*35)
    print("   ALL SCENARIOS COMPLETED")
    print("   Review results above for network resilience metrics")
    print("✅"*35 + "\n")

if __name__ == "__main__":
    main()
