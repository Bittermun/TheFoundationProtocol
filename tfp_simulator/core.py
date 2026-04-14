# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Simulator: Virtual Device & Chaos Engineering Framework

This module provides a high-fidelity simulation of the TFP P2P network.
It replaces simple unit mocks with "Virtual Devices" that have stateful
hardware constraints (battery, heat, network) and an Orchestrator that
injects chaos (latency, partitions, malicious actors).

Strategy:
1. VirtualDevice: Acts as a "fake phone" with realistic hardware decay.
2. ChaosOrchestrator: Manages the network timeline and injects faults.
3. Scenarios: Pre-defined stress tests for economic and technical resilience.
"""

import hashlib
import logging
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tfp.simulator")

# ==============================================================================
# 1. VIRTUAL HARDWARE MODEL (The "Fake Phone")
# ==============================================================================


class DeviceState(Enum):
    IDLE = "idle"
    COMPUTING = "computing"
    OVERHEATED = "overheated"
    LOW_BATTERY = "low_battery"
    OFFLINE = "offline"


@dataclass
class HardwareSpecs:
    """Defines the static capabilities of a virtual device."""

    device_id: str
    cpu_cores: int
    ram_gb: float
    battery_capacity_mah: int
    max_temp_celsius: float
    is_tee_enabled: bool  # Trusted Execution Environment
    network_bandwidth_mbps: float
    honesty_factor: float = 1.0  # 1.0 = honest, 0.0 = always lies


@dataclass
class HardwareState:
    """Dynamic state that changes during simulation."""

    battery_level_pct: float = 100.0
    current_temp_celsius: float = 35.0
    uptime_seconds: float = 0.0
    current_load_pct: float = 0.0
    state: DeviceState = DeviceState.IDLE
    credits_earned: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0


class VirtualDevice:
    """
    A simulated node in the TFP network.
    Mimics tfp-core/compute/device_safety.py and task_mesh.py behavior.
    """

    def __init__(self, specs: HardwareSpecs):
        self.specs = specs
        self.state = HardwareState()
        self.active_task: Optional[Dict] = None
        self._lock = threading.Lock()
        self.message_queue: List[Dict] = []

    def tick(self, delta_seconds: float) -> None:
        """
        Advance the simulation by delta_seconds.
        Updates battery, temperature, and uptime.
        """
        with self._lock:
            if self.state.state == DeviceState.OFFLINE:
                return

            self.state.uptime_seconds += delta_seconds

            # Thermal Dynamics
            if self.state.state == DeviceState.COMPUTING:
                heat_gen = (
                    self.state.current_load_pct / 100.0
                ) * 2.5  # Degrees per sec
                cooling = 0.8  # Passive cooling
                self.state.current_temp_celsius += (heat_gen - cooling) * delta_seconds
                self.state.battery_level_pct -= (
                    (self.state.current_load_pct / 100.0) * 0.05 * delta_seconds
                )
            else:
                # Cooling down when idle
                self.state.current_temp_celsius -= 0.5 * delta_seconds
                self.state.battery_level_pct -= (
                    0.001 * delta_seconds
                )  # Background drain

            # Clamp values
            self.state.current_temp_celsius = max(
                20.0, min(95.0, self.state.current_temp_celsius)
            )
            self.state.battery_level_pct = max(
                0.0, min(100.0, self.state.battery_level_pct)
            )

            # Safety Checks (Mirroring device_safety.py)
            self._enforce_safety_limits()

    def _enforce_safety_limits(self):
        if self.state.battery_level_pct < 20.0:
            self.state.state = DeviceState.LOW_BATTERY
            self.active_task = None
            self.state.current_load_pct = 0.0
        elif self.state.current_temp_celsius > self.specs.max_temp_celsius:
            self.state.state = DeviceState.OVERHEATED
            self.active_task = None
            self.state.current_load_pct = 0.0
        elif self.state.state in [DeviceState.LOW_BATTERY, DeviceState.OVERHEATED]:
            # Hysteresis: must cool down/charge before resuming
            if (
                self.state.battery_level_pct > 30.0
                and self.state.current_temp_celsius < (self.specs.max_temp_celsius - 10)
            ):
                self.state.state = DeviceState.IDLE

    def receive_message(self, msg: Dict):
        with self._lock:
            self.message_queue.append(msg)

    def process_messages(self, current_time: float) -> List[Dict]:
        responses = []
        with self._lock:
            for msg in self.message_queue:
                resp = self._handle_message(msg, current_time)
                if resp:
                    responses.append(resp)
            self.message_queue.clear()
        return responses

    def _handle_message(self, msg: Dict, now: float) -> Optional[Dict]:
        msg_type = msg.get("type")

        if msg_type == "TASK_BID_REQUEST":
            if self.state.state == DeviceState.IDLE:
                # Calculate bid based on specs and honesty
                reported_power = self.specs.cpu_cores * self.specs.honesty_factor
                return {
                    "type": "TASK_BID",
                    "from": self.specs.device_id,
                    "task_id": msg["task_id"],
                    "bid_price": 10,  # Simplified
                    "reported_power": reported_power,
                    "tee_available": self.specs.is_tee_enabled,
                }

        elif msg_type == "TASK_ASSIGNMENT":
            if self.state.state == DeviceState.IDLE:
                self.active_task = msg["task"]
                self.state.state = DeviceState.COMPUTING
                self.state.current_load_pct = random.uniform(60, 90)
                return {
                    "type": "ACK",
                    "from": self.specs.device_id,
                    "task_id": msg["task"]["id"],
                }

        elif msg_type == "RESULT_SUBMIT":
            # Handled internally during computation tick
            pass

        return None

    def compute_tick(self, delta: float) -> Optional[Dict]:
        """Simulate doing work. Returns result if task finishes."""
        if self.state.state != DeviceState.COMPUTING or not self.active_task:
            return None

        # Simulate progress
        progress = self.active_task.get("progress", 0.0)
        speed = (self.specs.cpu_cores * self.specs.honesty_factor) / 10.0
        new_progress = progress + (speed * delta)

        if new_progress >= 1.0:
            # Task Complete
            self.state.tasks_completed += 1
            self.state.credits_earned += self.active_task.get("reward", 0)
            self.state.state = DeviceState.IDLE
            self.state.current_load_pct = 0.0
            result = {
                "type": "TASK_RESULT",
                "from": self.specs.device_id,
                "task_id": self.active_task["id"],
                "result_hash": hashlib.sha3_256(
                    f"{self.active_task['id']}-{time.time()}".encode()
                ).hexdigest(),
                "success": True,
            }
            self.active_task = None
            return result
        else:
            self.active_task["progress"] = new_progress
            return None


# ==============================================================================
# 2. CHAOS ORCHESTRATOR (The Network Simulator)
# ==============================================================================


class ChaosEvent(Enum):
    NETWORK_PARTITION = "partition"
    LATENCY_SPIKE = "latency_spike"
    NODE_CRASH = "crash"
    MALICIOUS_ACTOR = "malicious_injection"
    POWER_OUTAGE = "power_outage"


@dataclass
class ChaosConfig:
    probability_partition: float = 0.0
    probability_latency: float = 0.0
    probability_crash: float = 0.0
    malicious_node_ratio: float = 0.0


class ChaosOrchestrator:
    """
    Manages the simulation loop, connecting devices and injecting chaos.
    """

    def __init__(self, devices: List[VirtualDevice], config: ChaosConfig = None):
        self.devices = {d.specs.device_id: d for d in devices}
        self.config = config or ChaosConfig()
        self.simulation_time = 0.0
        self.broadcast_log: List[Dict] = []
        self.running = False

    def add_chaos_event(self, event_type: ChaosEvent, target_ids: List[str] = None):
        """Manually trigger a chaos event."""
        if event_type == ChaosEvent.NODE_CRASH:
            targets = target_ids or list(self.devices.keys())
            for tid in targets:
                if tid in self.devices:
                    self.devices[tid].state.state = DeviceState.OFFLINE
                    logger.warning(f"CHAOS: Node {tid} crashed.")

        elif event_type == ChaosEvent.MALICIOUS_ACTOR:
            # Inject a liar into the pool if not already present
            if len(self.devices) > 0:
                target = random.choice(list(self.devices.keys()))
                self.devices[target].specs.honesty_factor = 0.1
                logger.warning(
                    f"CHAOS: Node {target} turned malicious (lying about power)."
                )

    def step(self, delta_seconds: float = 1.0):
        """Advance simulation by one step."""
        self.simulation_time += delta_seconds

        # 1. Random Chaos Injection
        if random.random() < self.config.probability_crash:
            self.add_chaos_event(ChaosEvent.NODE_CRASH)

        # 2. Device Physics Tick
        for device in self.devices.values():
            device.tick(delta_seconds)

        # 3. Message Passing (Simplified Broadcast)
        # Collect all outgoing messages
        outgoing = []
        for device in self.devices.values():
            if device.state.state != DeviceState.OFFLINE:
                # Process incoming
                responses = device.process_messages(self.simulation_time)
                outgoing.extend(responses)

                # Compute work
                result = device.compute_tick(delta_seconds)
                if result:
                    outgoing.append(result)

        # Distribute messages (Simulate network latency/drops)
        for msg in outgoing:
            self._broadcast_message(msg)

    def _broadcast_message(self, msg: Dict):
        """Simple flood broadcast. In real NDN, this would be content-routed."""
        sender = msg.get("from")
        for did, device in self.devices.items():
            if did != sender and device.state.state != DeviceState.OFFLINE:
                # Apply latency/drop logic here if needed
                device.receive_message(msg)

    def run_scenario(self, duration_seconds: float, step_size: float = 1.0):
        """Run the simulation for a set duration."""
        logger.info(f"Starting simulation for {duration_seconds}s...")
        end_time = self.simulation_time + duration_seconds
        while self.simulation_time < end_time:
            self.step(step_size)

        self.print_summary()

    def print_summary(self):
        total_tasks = sum(d.state.tasks_completed for d in self.devices.values())
        total_credits = sum(d.state.credits_earned for d in self.devices.values())
        failed = sum(d.state.tasks_failed for d in self.devices.values())
        offline = sum(
            1 for d in self.devices.values() if d.state.state == DeviceState.OFFLINE
        )

        print("\n" + "=" * 40)
        print(f"SIMULATION SUMMARY @ t={self.simulation_time:.1f}s")
        print("=" * 40)
        print(f"Active Nodes: {len(self.devices) - offline}/{len(self.devices)}")
        print(f"Tasks Completed: {total_tasks}")
        print(f"Tasks Failed: {failed}")
        print(f"Total Credits Minted: {total_credits}")
        print(
            f"Network Health: {'CRITICAL' if failed > total_tasks * 0.2 else 'STABLE'}"
        )
        print("=" * 40 + "\n")


# ==============================================================================
# 3. SCENARIO FACTORY
# ==============================================================================


class ScenarioFactory:
    """Generates pre-configured simulation scenarios."""

    @staticmethod
    def create_idle_compute_pool(count: int = 10) -> List[VirtualDevice]:
        devices = []
        for i in range(count):
            specs = HardwareSpecs(
                device_id=f"node_{i:03d}",
                cpu_cores=random.choice([4, 6, 8]),
                ram_gb=random.choice([4, 8, 16]),
                battery_capacity_mah=4000,
                max_temp_celsius=85.0,
                is_tee_enabled=(i % 3 == 0),  # 1/3 have TEE
                network_bandwidth_mbps=100.0,
                honesty_factor=1.0,
            )
            devices.append(VirtualDevice(specs))
        return devices

    @staticmethod
    def create_mixed_reality_network(count: int = 20) -> List[VirtualDevice]:
        """Mix of phones, servers, and malicious nodes."""
        devices = []
        for i in range(count):
            role = random.choices(
                ["phone", "server", "malicious"], weights=[0.7, 0.2, 0.1]
            )[0]

            if role == "phone":
                specs = HardwareSpecs(
                    device_id=f"phone_{i}",
                    cpu_cores=6,
                    ram_gb=6,
                    battery_capacity_mah=3500,
                    max_temp_celsius=75.0,
                    is_tee_enabled=False,
                    network_bandwidth_mbps=50.0,
                    honesty_factor=1.0,
                )
            elif role == "server":
                specs = HardwareSpecs(
                    device_id=f"server_{i}",
                    cpu_cores=32,
                    ram_gb=64,
                    battery_capacity_mah=100000,  # Plugged in
                    max_temp_celsius=95.0,
                    is_tee_enabled=True,
                    network_bandwidth_mbps=1000.0,
                    honesty_factor=1.0,
                )
            else:  # Malicious
                specs = HardwareSpecs(
                    device_id=f"liar_{i}",
                    cpu_cores=6,
                    ram_gb=6,
                    battery_capacity_mah=3500,
                    max_temp_celsius=75.0,
                    is_tee_enabled=False,
                    network_bandwidth_mbps=50.0,
                    honesty_factor=0.1,  # Lies about power
                )

            devices.append(VirtualDevice(specs))
        return devices
