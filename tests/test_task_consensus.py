# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Test suite for TFP Task Mesh Gates - Economic Hardening Layer
"""

import time
import unittest

from tfp_core.economy.task_mesh_gates import (
    HardwareCapability,
    TaskMeshGates,
    TaskResult,
    TaskSpec,
    is_econ_gates_enabled,
)


class TestTaskMeshGates(unittest.TestCase):
    """Test cases for TaskMeshGates class."""

    def setUp(self):
        """Set up test fixtures."""
        self.gates = TaskMeshGates(
            consensus_threshold=3,
            max_redundancy=5,
            base_decay_rate=0.05,
            min_stake=10.0,
        )

    def test_device_registration(self):
        """Test device registration with stake and capability."""
        success = self.gates.register_device(
            "device_A", HardwareCapability.CPU_BASIC, 50.0
        )
        self.assertTrue(success)

        # Check stake was created
        balance = self.gates.get_stake_balance("device_A")
        self.assertGreater(balance, 0.0)

    def test_device_registration_insufficient_stake(self):
        """Test rejection of device with insufficient stake."""
        success = self.gates.register_device(
            "device_B", HardwareCapability.CPU_BASIC, 5.0
        )
        self.assertFalse(success)

    def test_capability_gating_accept(self):
        """Test task acceptance based on hardware capability."""
        self.gates.register_device("device_tee", HardwareCapability.TEE_SECURE, 100.0)

        task = TaskSpec(
            task_id="task_1",
            difficulty=5,
            required_capability=HardwareCapability.CPU_BASIC,
            input_hash="input_abc",
            output_schema="schema_v1",
            base_reward=10.0,
            deadline=time.time() + 3600,
        )

        can_accept, reason = self.gates.can_accept_task("device_tee", task)
        self.assertTrue(can_accept)

    def test_capability_gating_reject(self):
        """Test task rejection due to insufficient capability."""
        self.gates.register_device("device_basic", HardwareCapability.CPU_BASIC, 50.0)

        task = TaskSpec(
            task_id="task_2",
            difficulty=8,
            required_capability=HardwareCapability.TEE_SECURE,
            input_hash="input_xyz",
            output_schema="schema_v2",
            base_reward=20.0,
            deadline=time.time() + 3600,
        )

        can_accept, reason = self.gates.can_accept_task("device_basic", task)
        self.assertFalse(can_accept)
        self.assertIn("Insufficient capability", reason)

    def test_consensus_achievement(self):
        """Test achieving consensus with matching results."""
        # Register devices
        for i, cap in enumerate(
            [
                HardwareCapability.CPU_BASIC,
                HardwareCapability.TEE_SECURE,
                HardwareCapability.GPU_ACCEL,
            ]
        ):
            self.gates.register_device(f"device_{i}", cap, 50.0 + i * 10)

        # Submit matching results from 3 devices
        for i in range(3):
            result = TaskResult(
                task_id="consensus_task",
                device_id=f"device_{i}",
                output_hash="matching_output",
                execution_time_ms=100.0,
                hardware_proof=f"proof_{i}",
                timestamp=time.time(),
            )

            response = self.gates.submit_result(result)

            if i < 2:
                self.assertFalse(response["task_verified"])
                self.assertTrue(response["consensus_pending"])
            else:
                self.assertTrue(response["task_verified"])
                self.assertGreater(response["credit_yield"], 0.0)

    def test_consensus_mismatch(self):
        """Test failure to achieve consensus with mismatched outputs."""
        # Register devices
        for i in range(3):
            self.gates.register_device(
                f"mismatch_device_{i}", HardwareCapability.CPU_BASIC, 50.0
            )

        # Submit different results
        for i in range(3):
            result = TaskResult(
                task_id="mismatch_task",
                device_id=f"mismatch_device_{i}",
                output_hash=f"different_output_{i}",
                execution_time_ms=100.0,
                hardware_proof=f"proof_{i}",
                timestamp=time.time(),
            )

            response = self.gates.submit_result(result)

        # Should not achieve consensus
        stats = self.gates.get_economic_stats()
        self.assertEqual(stats["pending_tasks"], 1)

    def test_stake_decay(self):
        """Test credit stake decay over time."""
        self.gates.register_device("decay_device", HardwareCapability.CPU_BASIC, 100.0)

        initial_balance = self.gates.get_stake_balance("decay_device")

        # Simulate time passing (1 hour)
        # Manually adjust stake timestamp for testing
        stake = self.gates._credit_stakes["decay_device"]
        stake.stake_timestamp = time.time() - 3600  # 1 hour ago

        decayed_balance = self.gates.get_stake_balance("decay_device")

        # Should have decayed (5% per hour for CPU_BASIC with 1.5 multiplier = 7.5%)
        self.assertLess(decayed_balance, initial_balance)
        self.assertGreater(
            decayed_balance, initial_balance * 0.9
        )  # Should still have >90%

    def test_slashing(self):
        """Test stake slashing for misbehavior."""
        self.gates.register_device("bad_device", HardwareCapability.CPU_BASIC, 100.0)

        initial_balance = self.gates.get_stake_balance("bad_device")

        # Slash for misbehavior
        success = self.gates.slash_stake("bad_device", 20.0, "Invalid result")
        self.assertTrue(success)

        new_balance = self.gates.get_stake_balance("bad_device")
        self.assertAlmostEqual(new_balance, initial_balance - 20.0, places=2)

    def test_max_redundancy_limit(self):
        """Test that tasks are rejected after reaching max redundancy."""
        self.gates = TaskMeshGates(consensus_threshold=2, max_redundancy=2)

        self.gates.register_device("red_device_1", HardwareCapability.CPU_BASIC, 50.0)
        self.gates.register_device("red_device_2", HardwareCapability.CPU_BASIC, 50.0)
        self.gates.register_device("red_device_3", HardwareCapability.CPU_BASIC, 50.0)

        task = TaskSpec(
            task_id="redundant_task",
            difficulty=3,
            required_capability=HardwareCapability.CPU_BASIC,
            input_hash="input_red",
            output_schema="schema_red",
            base_reward=5.0,
            deadline=time.time() + 3600,
        )

        # First two devices accepted
        can1, _ = self.gates.can_accept_task("red_device_1", task)
        self.assertTrue(can1)

        can2, _ = self.gates.can_accept_task("red_device_2", task)
        self.assertTrue(can2)

        # Simulate results being submitted (this populates _task_results)
        from tfp_core.economy.task_mesh_gates import TaskResult

        result1 = TaskResult(
            task_id="redundant_task",
            device_id="red_device_1",
            output_hash="hash1",
            execution_time_ms=100.0,
            hardware_proof="proof1",
            timestamp=time.time(),
        )
        result2 = TaskResult(
            task_id="redundant_task",
            device_id="red_device_2",
            output_hash="hash2",
            execution_time_ms=105.0,
            hardware_proof="proof2",
            timestamp=time.time(),
        )
        self.gates.submit_result(result1)
        self.gates.submit_result(result2)

        # Third device rejected (max redundancy reached)
        can3, reason = self.gates.can_accept_task("red_device_3", task)
        self.assertFalse(can3)
        self.assertIn("max redundancy", reason)

    def test_economic_stats(self):
        """Test economic statistics reporting."""
        self.gates.register_device("stat_device_1", HardwareCapability.CPU_BASIC, 100.0)
        self.gates.register_device(
            "stat_device_2", HardwareCapability.TEE_SECURE, 200.0
        )

        stats = self.gates.get_economic_stats()

        self.assertEqual(stats["registered_devices"], 2)
        self.assertGreater(stats["total_staked"], 0.0)
        self.assertEqual(stats["total_earned"], 0.0)
        self.assertEqual(stats["total_slashed"], 0.0)

    def test_feature_gate(self):
        """Test feature gate check."""
        result = is_econ_gates_enabled()
        self.assertFalse(result)


class TestEconomicIntegration(unittest.TestCase):
    """Integration tests for economic hardening."""

    def test_full_task_lifecycle(self):
        """Test complete task lifecycle from registration to payout."""
        gates = TaskMeshGates(consensus_threshold=2, max_redundancy=3)

        # Register heterogeneous devices - multiple TEE devices for consensus
        devices = [
            ("worker_1", HardwareCapability.TEE_SECURE, 50.0),
            ("worker_2", HardwareCapability.TEE_SECURE, 100.0),
            (
                "worker_3",
                HardwareCapability.PUF_VERIFIED,
                75.0,
            ),  # PUF also satisfies high-security tasks
        ]

        for device_id, cap, stake in devices:
            gates.register_device(device_id, cap, stake)

        # Create high-value task requiring TEE
        task = TaskSpec(
            task_id="high_value_task",
            difficulty=8,
            required_capability=HardwareCapability.TEE_SECURE,
            input_hash="secure_input",
            output_schema="secure_output",
            base_reward=50.0,
            deadline=time.time() + 7200,
        )

        # Check which workers can accept
        accepted_workers = []
        for device_id, _, _ in devices:
            can_accept, _ = gates.can_accept_task(device_id, task)
            if can_accept:
                accepted_workers.append(device_id)

        # At least 2 TEE-capable workers should be accepted
        self.assertGreaterEqual(
            len(accepted_workers),
            2,
            f"Expected at least 2 workers, got {len(accepted_workers)}: {accepted_workers}",
        )

        # Submit results from 2 workers to achieve consensus
        for device_id in accepted_workers[:2]:
            result = TaskResult(
                task_id="high_value_task",
                device_id=device_id,
                output_hash="verified_secure_output",
                execution_time_ms=200.0,
                hardware_proof=f"attestation_{device_id}",
                timestamp=time.time(),
            )

            response = gates.submit_result(result)

        # Verify consensus achieved and credits distributed
        stats = gates.get_economic_stats()
        self.assertEqual(stats["consensus_tasks"], 1)
        self.assertGreater(stats["total_earned"], 0.0)

    def test_bot_farm_resistance(self):
        """Test resistance to bot farm attacks via decay pricing."""
        gates = TaskMeshGates(consensus_threshold=3, base_decay_rate=0.1)

        # Simulate bot farm with many low-stake devices
        for i in range(20):
            gates.register_device(f"bot_{i}", HardwareCapability.CPU_BASIC, 10.0)

        # Single honest high-stake device
        gates.register_device("honest_node", HardwareCapability.PUF_VERIFIED, 500.0)

        # Honest node has lower decay rate (more trusted)
        honest_stake = gates._credit_stakes["honest_node"]
        bot_stake = gates._credit_stakes["bot_0"]

        # PUF_VERIFIED should have lower decay than CPU_BASIC
        self.assertLess(honest_stake.decay_rate, bot_stake.decay_rate)


if __name__ == "__main__":
    unittest.main()
