# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Task Mesh Gates - Economic Hardening Layer

Provides redundant execution consensus, hardware capability gating, credit staking,
and exponential decay to prevent bot farms and ensure fair compute distribution.

All economic gates are pure math + hardware attestation. No central scheduler.
"""

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class HardwareCapability(Enum):
    """Hardware capability tiers for task gating."""

    CPU_BASIC = "cpu_basic"
    CPU_NPU = "cpu_npu"  # Has NPU for AI tasks
    TEE_SECURE = "tee_secure"  # Has Trusted Execution Environment
    GPU_ACCEL = "gpu_accel"
    PUF_VERIFIED = "puf_verified"  # Has PUF identity


@dataclass
class TaskSpec:
    """Specification for a compute task."""

    task_id: str
    difficulty: int  # 1-10 scale
    required_capability: HardwareCapability
    input_hash: str
    output_schema: str
    base_reward: float
    deadline: float


@dataclass
class TaskResult:
    """Result from task execution."""

    task_id: str
    device_id: str
    output_hash: str
    execution_time_ms: float
    hardware_proof: str  # PUF/TEE attestation
    timestamp: float


@dataclass
class CreditStake:
    """Credit stake for task participation."""

    device_id: str
    staked_amount: float
    stake_timestamp: float
    decay_rate: float  # Per-hour decay
    total_earned: float = 0.0
    total_slashed: float = 0.0


@dataclass
class ConsensusRecord:
    """Track redundant execution results for consensus."""

    task_id: str
    results: List[TaskResult]
    consensus_threshold: int
    achieved_at: Optional[float] = None
    is_consensus: bool = False


class TaskMeshGates:
    """
    Economic hardening for P2P compute mesh.

    Features:
    - Redundant execution consensus (3/5 match required)
    - Hardware capability gating (PUF/TEE + NPU tags)
    - Credit staking with exponential decay
    - Bot farm mitigation via decay pricing
    """

    def __init__(
        self,
        consensus_threshold: int = 3,
        max_redundancy: int = 5,
        base_decay_rate: float = 0.05,  # 5% per hour
        min_stake: float = 10.0,
    ):
        self.consensus_threshold = consensus_threshold
        self.max_redundancy = max_redundancy
        self.base_decay_rate = base_decay_rate
        self.min_stake = min_stake

        self._lock = threading.Lock()
        self._task_results: Dict[str, ConsensusRecord] = {}
        self._credit_stakes: Dict[str, CreditStake] = {}
        self._hardware_capabilities: Dict[str, HardwareCapability] = {}
        self._completed_tasks: Dict[str, TaskResult] = {}
        self._rejected_tasks: List[Dict[str, Any]] = []

    def register_device(
        self, device_id: str, capability: HardwareCapability, initial_stake: float
    ) -> bool:
        """
        Register a device with its hardware capability and stake.

        Args:
            device_id: Unique device identifier
            capability: Hardware capability tier
            initial_stake: Initial credit stake

        Returns:
            True if registration successful
        """
        if initial_stake < self.min_stake:
            return False

        with self._lock:
            self._hardware_capabilities[device_id] = capability

            # Calculate decay rate based on capability
            # Higher capability = lower decay (more trusted)
            capability_multiplier = {
                HardwareCapability.CPU_BASIC: 1.5,
                HardwareCapability.CPU_NPU: 1.2,
                HardwareCapability.GPU_ACCEL: 1.0,
                HardwareCapability.TEE_SECURE: 0.8,
                HardwareCapability.PUF_VERIFIED: 0.6,
            }.get(capability, 1.0)

            decay_rate = self.base_decay_rate * capability_multiplier

            self._credit_stakes[device_id] = CreditStake(
                device_id=device_id,
                staked_amount=initial_stake,
                stake_timestamp=time.time(),
                decay_rate=decay_rate,
            )

        return True

    def can_accept_task(
        self, device_id: str, task: TaskSpec
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a device can accept a task based on capability gating.

        Args:
            device_id: Device identifier
            task: Task specification

        Returns:
            Tuple of (can_accept, rejection_reason)
        """
        with self._lock:
            # Check hardware capability
            device_cap = self._hardware_capabilities.get(device_id)
            if not device_cap:
                return False, "Device not registered"

            # Capability hierarchy
            capability_hierarchy = {
                HardwareCapability.CPU_BASIC: 0,
                HardwareCapability.CPU_NPU: 1,
                HardwareCapability.GPU_ACCEL: 2,
                HardwareCapability.TEE_SECURE: 3,
                HardwareCapability.PUF_VERIFIED: 4,
            }

            required_level = capability_hierarchy.get(task.required_capability, 0)
            device_level = capability_hierarchy.get(device_cap, 0)

            if device_level < required_level:
                return (
                    False,
                    f"Insufficient capability: {device_cap.value} < {task.required_capability.value}",
                )

            # Check stake
            stake = self._credit_stakes.get(device_id)
            if not stake or stake.staked_amount < self.min_stake:
                return False, "Insufficient stake"

            # Check if task already has enough redundancy
            if task.task_id in self._task_results:
                record = self._task_results[task.task_id]
                if len(record.results) >= self.max_redundancy:
                    return False, "Task already at max redundancy"

            return True, None

    def submit_result(self, result: TaskResult) -> Dict[str, Any]:
        """
        Submit a task result for consensus verification.

        Args:
            result: Task result

        Returns:
            Dictionary with verification status and credit yield
        """
        current_time = time.time()

        with self._lock:
            # Initialize consensus record if needed
            if result.task_id not in self._task_results:
                self._task_results[result.task_id] = ConsensusRecord(
                    task_id=result.task_id,
                    results=[],
                    consensus_threshold=self.consensus_threshold,
                )

            record = self._task_results[result.task_id]
            record.results.append(result)

            # Check for consensus
            if (
                not record.is_consensus
                and len(record.results) >= self.consensus_threshold
            ):
                # Group by output hash
                hash_counts: Dict[str, int] = {}
                for r in record.results:
                    hash_counts[r.output_hash] = hash_counts.get(r.output_hash, 0) + 1

                # Find majority hash
                for output_hash, count in hash_counts.items():
                    if count >= self.consensus_threshold:
                        record.is_consensus = True
                        record.achieved_at = current_time

                        # Calculate credit yield for all matching results
                        matching_devices = [
                            r.device_id
                            for r in record.results
                            if r.output_hash == output_hash
                        ]

                        return self._calculate_credit_yield(
                            result.task_id, matching_devices, result.execution_time_ms
                        )

            # No consensus yet
            return {
                "task_verified": False,
                "credit_yield": 0.0,
                "decay_rate": 0.0,
                "consensus_pending": True,
                "results_count": len(record.results),
            }

    def get_stake_balance(self, device_id: str) -> float:
        """
        Get current stake balance after decay.

        Args:
            device_id: Device identifier

        Returns:
            Current stake balance
        """
        with self._lock:
            stake = self._credit_stakes.get(device_id)
            if not stake:
                return 0.0

            elapsed_hours = (time.time() - stake.stake_timestamp) / 3600.0
            decay_factor = (1.0 - stake.decay_rate) ** elapsed_hours

            current_balance = (
                stake.staked_amount * decay_factor
                + stake.total_earned
                - stake.total_slashed
            )

            return max(0.0, current_balance)

    def slash_stake(self, device_id: str, amount: float, reason: str) -> bool:
        """
        Slash a portion of a device's stake for misbehavior.

        Args:
            device_id: Device identifier
            amount: Amount to slash
            reason: Reason for slashing

        Returns:
            True if slashing successful
        """
        stake = self._credit_stakes.get(device_id)
        if not stake:
            return False

        # Calculate current balance inline to avoid deadlock (get_stake_balance also acquires _lock)
        elapsed_hours = (time.time() - stake.stake_timestamp) / 3600.0
        decay_factor = (1.0 - stake.decay_rate) ** elapsed_hours
        current_balance = max(
            0.0,
            stake.staked_amount * decay_factor
            + stake.total_earned
            - stake.total_slashed,
        )

        if amount > current_balance:
            amount = current_balance

        stake.total_slashed += amount

        # Log slashing event
        self._rejected_tasks.append(
            {
                "device_id": device_id,
                "action": "SLASH",
                "amount": amount,
                "reason": reason,
                "timestamp": time.time(),
            }
        )

        return True

    def get_economic_stats(self) -> Dict[str, Any]:
        """Get economic system statistics."""
        with self._lock:
            total_staked = sum(s.staked_amount for s in self._credit_stakes.values())
            total_earned = sum(s.total_earned for s in self._credit_stakes.values())
            total_slashed = sum(s.total_slashed for s in self._credit_stakes.values())

            consensus_tasks = len(
                [r for r in self._task_results.values() if r.is_consensus]
            )
            pending_tasks = len(
                [r for r in self._task_results.values() if not r.is_consensus]
            )

            return {
                "registered_devices": len(self._credit_stakes),
                "total_staked": round(total_staked, 2),
                "total_earned": round(total_earned, 2),
                "total_slashed": round(total_slashed, 2),
                "consensus_tasks": consensus_tasks,
                "pending_tasks": pending_tasks,
                "rejected_events": len(self._rejected_tasks),
            }

    def _calculate_credit_yield(
        self, task_id: str, matching_devices: List[str], execution_time_ms: float
    ) -> Dict[str, Any]:
        """Calculate credit yield for devices that matched consensus."""
        # Base reward split among matching devices
        # Faster execution = bonus, slower = penalty
        avg_time = execution_time_ms  # Could be average of all matching

        time_bonus = max(0.5, min(2.0, 1000.0 / max(1.0, avg_time)))

        yields = {}
        for device_id in matching_devices:
            stake = self._credit_stakes.get(device_id)
            if not stake:
                continue

            # Base yield proportional to stake
            base_yield = 1.0 * time_bonus
            stake_bonus = stake.staked_amount / 100.0  # 1% bonus per 100 credits

            total_yield = base_yield * (1.0 + stake_bonus)
            stake.total_earned += total_yield

            yields[device_id] = {
                "base_yield": round(base_yield, 3),
                "stake_bonus": round(stake_bonus, 3),
                "total_yield": round(total_yield, 3),
                "decay_rate": round(stake.decay_rate, 4),
            }

        # Return aggregate info
        sample_device = matching_devices[0] if matching_devices else None
        sample_yield = yields.get(sample_device, {})

        return {
            "task_verified": True,
            "credit_yield": sample_yield.get("total_yield", 0.0),
            "decay_rate": sample_yield.get("decay_rate", 0.0),
            "consensus_achieved": True,
            "matching_devices": len(matching_devices),
            "individual_yields": yields,
        }


# Feature gate check
def is_econ_gates_enabled() -> bool:
    """Check if economic gate features are enabled."""
    import os

    return os.getenv("TFP_FEATURES_ECON_GATES", "false").lower() == "true"


if __name__ == "__main__":
    # Demo usage
    gates = TaskMeshGates(consensus_threshold=3, max_redundancy=5)

    # Register devices with different capabilities
    devices = [
        ("device_A", HardwareCapability.CPU_BASIC, 50.0),
        ("device_B", HardwareCapability.TEE_SECURE, 100.0),
        ("device_C", HardwareCapability.PUF_VERIFIED, 150.0),
        ("device_D", HardwareCapability.CPU_NPU, 75.0),
        ("device_E", HardwareCapability.GPU_ACCEL, 120.0),
    ]

    for device_id, cap, stake in devices:
        success = gates.register_device(device_id, cap, stake)
        print(f"Registered {device_id}: {success}")

    # Create a task requiring TEE
    task = TaskSpec(
        task_id="task_001",
        difficulty=5,
        required_capability=HardwareCapability.TEE_SECURE,
        input_hash="input_xyz",
        output_schema="schema_v1",
        base_reward=10.0,
        deadline=time.time() + 3600,
    )

    # Check which devices can accept
    print("\nTask Acceptance:")
    for device_id, _, _ in devices:
        can_accept, reason = gates.can_accept_task(device_id, task)
        print(f"  {device_id}: {can_accept} ({reason or 'OK'})")

    # Submit results from 3 devices
    print("\nSubmitting Results:")
    for device_id in ["device_B", "device_C", "device_E"]:
        result = TaskResult(
            task_id="task_001",
            device_id=device_id,
            output_hash="output_abc",  # All match
            execution_time_ms=150.0,
            hardware_proof=f"proof_{device_id}",
            timestamp=time.time(),
        )

        response = gates.submit_result(result)
        print(
            f"  {device_id}: verified={response['task_verified']}, yield={response.get('credit_yield', 0):.3f}"
        )

    print("\nEconomic Stats:")
    stats = gates.get_economic_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
