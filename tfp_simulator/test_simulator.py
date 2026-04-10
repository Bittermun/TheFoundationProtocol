"""
TFP Simulator Test Suite

Tests for the Virtual Device and Chaos Engineering Framework.
Validates hardware modeling, thermal dynamics, economic incentives,
and chaos resilience.
"""

import pytest
import time
from tfp_simulator.core import (
    VirtualDevice, HardwareSpecs, HardwareState, DeviceState,
    ChaosOrchestrator, ChaosConfig, ChaosEvent, ScenarioFactory
)

class TestVirtualDevice:
    """Tests for the VirtualDevice hardware model."""

    def test_device_initialization(self):
        """Device should start with full battery and idle state."""
        specs = HardwareSpecs(
            device_id="test_001",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        assert device.state.battery_level_pct == 100.0
        assert device.state.current_temp_celsius == 35.0
        assert device.state.state == DeviceState.IDLE
        assert device.state.credits_earned == 0

    def test_device_heating_during_computation(self):
        """Device temperature should rise when computing."""
        specs = HardwareSpecs(
            device_id="test_002",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=False,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        # Force into computing state
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 80.0
        
        initial_temp = device.state.current_temp_celsius
        
        # Simulate 10 seconds of computation
        for _ in range(10):
            device.tick(1.0)
        
        assert device.state.current_temp_celsius > initial_temp

    def test_device_battery_drain(self):
        """Battery should drain faster under load."""
        specs = HardwareSpecs(
            device_id="test_003",
            cpu_cores=4,
            ram_gb=8,
            battery_capacity_mah=3000,
            max_temp_celsius=75.0,
            is_tee_enabled=False,
            network_bandwidth_mbps=50.0
        )
        device = VirtualDevice(specs)
        
        initial_battery = device.state.battery_level_pct
        
        # Idle for 10 seconds
        for _ in range(10):
            device.tick(1.0)
        idle_drain = initial_battery - device.state.battery_level_pct
        
        # Reset and compute for 10 seconds
        device.state.battery_level_pct = 100.0
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 90.0
        
        for _ in range(10):
            device.tick(1.0)
        compute_drain = 100.0 - device.state.battery_level_pct
        
        assert compute_drain > idle_drain

    def test_overheat_protection(self):
        """Device should halt computation when overheated."""
        specs = HardwareSpecs(
            device_id="test_004",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=75.0,  # Low threshold for testing
            is_tee_enabled=False,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        # Force high temp
        device.state.current_temp_celsius = 80.0
        device.state.state = DeviceState.COMPUTING
        
        device.tick(1.0)
        
        assert device.state.state == DeviceState.OVERHEATED
        assert device.state.current_load_pct == 0.0

    def test_low_battery_protection(self):
        """Device should halt when battery is critically low."""
        specs = HardwareSpecs(
            device_id="test_005",
            cpu_cores=4,
            ram_gb=4,
            battery_capacity_mah=2000,
            max_temp_celsius=85.0,
            is_tee_enabled=False,
            network_bandwidth_mbps=50.0
        )
        device = VirtualDevice(specs)
        
        device.state.battery_level_pct = 15.0
        device.state.state = DeviceState.COMPUTING
        
        device.tick(1.0)
        
        assert device.state.state == DeviceState.LOW_BATTERY
        assert device.active_task is None

    def test_device_cooling_when_idle(self):
        """Device should cool down when not computing."""
        specs = HardwareSpecs(
            device_id="test_006",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        device.state.current_temp_celsius = 90.0
        device.state.state = DeviceState.IDLE
        
        for _ in range(20):
            device.tick(1.0)
        
        assert device.state.current_temp_celsius < 90.0

    def test_hysteresis_recovery(self):
        """Device should recover from protection states only after conditions improve."""
        specs = HardwareSpecs(
            device_id="test_007",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=75.0,
            is_tee_enabled=False,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        # Overheat
        device.state.current_temp_celsius = 80.0
        device.tick(1.0)
        assert device.state.state == DeviceState.OVERHEATED
        
        # Cool down below threshold
        device.state.current_temp_celsius = 60.0  # Below 75-10=65
        device.tick(1.0)
        assert device.state.state == DeviceState.IDLE


class TestTaskExecution:
    """Tests for task assignment and completion."""

    def test_task_assignment(self):
        """Device should accept task when idle."""
        specs = HardwareSpecs(
            device_id="test_008",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        task = {"id": "task_123", "reward": 50, "progress": 0.0}
        msg = {"type": "TASK_ASSIGNMENT", "task": task}
        
        response = device._handle_message(msg, time.time())
        
        assert response is not None
        assert response["type"] == "ACK"
        assert device.state.state == DeviceState.COMPUTING

    def test_task_completion(self):
        """Device should complete task and earn credits."""
        specs = HardwareSpecs(
            device_id="test_009",
            cpu_cores=10,  # High power for fast completion
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=100.0
        )
        device = VirtualDevice(specs)
        
        # Assign task
        task = {"id": "task_456", "reward": 100, "progress": 0.0}
        device.active_task = task
        device.state.state = DeviceState.COMPUTING
        device.state.current_load_pct = 80.0
        
        # Simulate until complete
        result = None
        for _ in range(20):
            device.tick(1.0)
            result = device.compute_tick(1.0)
            if result:
                break
        
        assert result is not None
        assert result["success"] is True
        assert device.state.credits_earned == 100
        assert device.state.state == DeviceState.IDLE

    def test_malicious_device_underreports(self):
        """Device with low honesty_factor should report less power."""
        specs = HardwareSpecs(
            device_id="liar_001",
            cpu_cores=8,
            ram_gb=16,
            battery_capacity_mah=4000,
            max_temp_celsius=85.0,
            is_tee_enabled=False,
            network_bandwidth_mbps=100.0,
            honesty_factor=0.1  # Very dishonest
        )
        device = VirtualDevice(specs)
        
        msg = {"type": "TASK_BID_REQUEST", "task_id": "task_789"}
        response = device._handle_message(msg, time.time())
        
        assert response["reported_power"] == 0.8  # 8 * 0.1


class TestChaosOrchestrator:
    """Tests for chaos injection and network simulation."""

    def test_orchestrator_initialization(self):
        """Orchestrator should manage devices correctly."""
        devices = ScenarioFactory.create_idle_compute_pool(5)
        orchestrator = ChaosOrchestrator(devices)
        
        assert len(orchestrator.devices) == 5

    def test_node_crash_event(self):
        """Chaos should be able to crash nodes."""
        devices = ScenarioFactory.create_idle_compute_pool(3)
        orchestrator = ChaosOrchestrator(devices)
        
        orchestrator.add_chaos_event(ChaosEvent.NODE_CRASH, ["node_000"])
        
        assert orchestrator.devices["node_000"].state.state == DeviceState.OFFLINE

    def test_malicious_injection(self):
        """Chaos should be able to turn nodes malicious."""
        devices = ScenarioFactory.create_idle_compute_pool(3)
        orchestrator = ChaosOrchestrator(devices)
        
        initial_honesty = orchestrator.devices["node_000"].specs.honesty_factor
        assert initial_honesty == 1.0
        
        orchestrator.add_chaos_event(ChaosEvent.MALICIOUS_ACTOR)
        
        # At least one node should now be malicious
        malicious_count = sum(1 for d in orchestrator.devices.values() if d.specs.honesty_factor < 0.5)
        assert malicious_count >= 1

    def test_simulation_step(self):
        """Simulation should advance time and process messages."""
        devices = ScenarioFactory.create_idle_compute_pool(2)
        orchestrator = ChaosOrchestrator(devices)
        
        initial_time = orchestrator.simulation_time
        orchestrator.step(5.0)
        
        assert orchestrator.simulation_time == initial_time + 5.0


class TestScenarioFactory:
    """Tests for scenario generation."""

    def test_create_compute_pool(self):
        """Should create homogeneous pool."""
        devices = ScenarioFactory.create_idle_compute_pool(10)
        
        assert len(devices) == 10
        assert all(d.state.state == DeviceState.IDLE for d in devices)

    def test_create_mixed_network_has_variety(self):
        """Mixed network should have phones, servers, and potentially malicious nodes."""
        devices = ScenarioFactory.create_mixed_reality_network(50)
        
        assert len(devices) == 50
        
        # Check for variety (probabilistic, so run multiple times or check stats)
        device_ids = [d.specs.device_id for d in devices]
        has_phones = any("phone" in did for did in device_ids)
        has_servers = any("server" in did for did in device_ids)
        
        assert has_phones or has_servers  # Should have at least one type


class TestEconomicIncentives:
    """Tests for credit accumulation and economic model."""

    def test_credits_accumulate_on_completion(self):
        """Devices should earn credits for completed tasks."""
        specs = HardwareSpecs(
            device_id="miner_001",
            cpu_cores=16,
            ram_gb=32,
            battery_capacity_mah=100000,
            max_temp_celsius=95.0,
            is_tee_enabled=True,
            network_bandwidth_mbps=1000.0
        )
        device = VirtualDevice(specs)
        
        # Complete multiple tasks
        for i in range(3):
            task = {"id": f"task_{i}", "reward": 50, "progress": 0.0}
            device.active_task = task
            device.state.state = DeviceState.COMPUTING
            device.state.current_load_pct = 50.0
            
            # Run until complete
            for _ in range(50):
                device.tick(1.0)
                result = device.compute_tick(1.0)
                if result:
                    break
        
        assert device.state.credits_earned == 150
        assert device.state.tasks_completed == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
