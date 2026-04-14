# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for TFP Compute & Access Control Expansion

Tests for:
- task_mesh.py: P2P micro-task coordination
- verify_habp.py: Hardware-Agnostic Benchmark Proof verification
- device_safety.py: Device safety guards
- credit_formula.py: Credit calculation
- license_manager.py: License management (plugin)
- threshold_release.py: Multi-sig threshold releases (plugin)
- plugin_access_boundary.py: Core/plugin separation verification
"""

import os
import sys
import time
import unittest

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tfp_core.compute.credit_formula import CreditFormula, calculate_task_credits
from tfp_core.compute.device_safety import (
    DeviceSafetyGuard,
    SafetyStatus,
    create_device_metrics,
)
from tfp_core.compute.task_mesh import ComputeMesh, DeviceBid, TaskRecipe
from tfp_core.compute.verify_habp import HABPVerifier, generate_execution_proof
from tfp_plugins.access_control.license_manager import (
    LicenseManager,
    LicenseType,
    create_community_content,
    create_paywalled_content,
    create_time_locked_content,
)
from tfp_plugins.access_control.threshold_release import (
    ThresholdReleaser,
    create_multi_sig_release,
)


class TestComputeMesh(unittest.TestCase):
    """Test P2P compute task mesh."""

    def setUp(self):
        self.mesh = ComputeMesh()
        self.task = TaskRecipe(
            task_id="task_001",
            difficulty=5,
            input_hash="abc123",
            output_schema={"type": "image"},
            deadline=time.time() + 3600,
            credit_reward=100,
            creator_sig="sig_xyz",
        )

    def test_broadcast_task(self):
        """Test broadcasting a task to the mesh."""
        task_id = self.mesh.broadcast_task(self.task)
        self.assertEqual(task_id, "task_001")
        self.assertEqual(self.mesh.get_task_status("task_001"), "awaiting_bids")

    def test_submit_bid(self):
        """Test submitting a bid for a task."""
        self.mesh.broadcast_task(self.task)

        bid = DeviceBid(
            device_id="device_001",
            task_id="task_001",
            estimated_time=60.0,
            hardware_trust=0.9,
            current_load=0.3,
            battery_level=80,
            is_charging=True,
            timestamp=time.time(),
            signature="bid_sig",
        )

        result = self.mesh.submit_bid(bid)
        self.assertTrue(result)
        self.assertEqual(len(self.mesh._bids["task_001"]), 1)

    def test_submit_bid_low_battery(self):
        """Test that low battery bids are rejected."""
        self.mesh.broadcast_task(self.task)

        bid = DeviceBid(
            device_id="device_001",
            task_id="task_001",
            estimated_time=60.0,
            hardware_trust=0.9,
            current_load=0.3,
            battery_level=20,  # Below minimum
            is_charging=False,
            timestamp=time.time(),
            signature="bid_sig",
        )

        result = self.mesh.submit_bid(bid)
        self.assertFalse(result)

    def test_select_winner(self):
        """Test selecting the best bid."""
        self.mesh.broadcast_task(self.task)

        # Submit multiple bids
        bids_data = [
            ("device_001", 0.9, 0.3, 80, True),
            ("device_002", 0.7, 0.5, 90, False),
            ("device_003", 0.95, 0.2, 75, True),
        ]

        for device_id, trust, load, battery, charging in bids_data:
            bid = DeviceBid(
                device_id=device_id,
                task_id="task_001",
                estimated_time=60.0,
                hardware_trust=trust,
                current_load=load,
                battery_level=battery,
                is_charging=charging,
                timestamp=time.time(),
                signature="sig",
            )
            self.mesh.submit_bid(bid)

        winner = self.mesh.select_winner("task_001")
        self.assertIsNotNone(winner)
        self.assertEqual(winner.status, "pending")
        # Best bid should be selected (high trust, low load, charging)
        self.assertIn(winner.device_id, ["device_001", "device_003"])

    def test_complete_task(self):
        """Test completing a task."""
        self.mesh.broadcast_task(self.task)

        bid = DeviceBid(
            device_id="device_001",
            task_id="task_001",
            estimated_time=60.0,
            hardware_trust=0.9,
            current_load=0.3,
            battery_level=80,
            is_charging=True,
            timestamp=time.time(),
            signature="sig",
        )
        self.mesh.submit_bid(bid)
        self.mesh.select_winner("task_001")

        completed = self.mesh.complete_task("task_001", "result_hash", True)
        self.assertTrue(completed)
        self.assertEqual(self.mesh.get_task_status("task_001"), "completed")


class TestHABPVerifier(unittest.TestCase):
    """Test Hardware-Agnostic Benchmark Proof verification."""

    def setUp(self):
        self.verifier = HABPVerifier(consensus_threshold=3, redundancy_factor=5)

    def test_consensus_verification_success(self):
        """Test successful consensus verification."""
        task_id = "task_001"
        output_data = b"expected_output"

        # Submit 3 matching proofs
        for i in range(3):
            proof = generate_execution_proof(
                device_id=f"device_{i}",
                task_id=task_id,
                output_data=output_data,
                execution_time=10.0,
            )
            self.verifier.submit_proof(proof)

        result = self.verifier.verify_consensus(task_id)
        self.assertIsNotNone(result)
        self.assertTrue(result.verified)
        self.assertEqual(result.method, "consensus")
        self.assertGreater(result.confidence, 0.0)

    def test_consensus_verification_failure(self):
        """Test failed consensus (all different outputs)."""
        task_id = "task_002"

        # Submit 3 different outputs
        for i in range(3):
            proof = generate_execution_proof(
                device_id=f"device_{i}",
                task_id=task_id,
                output_data=f"different_{i}".encode(),
                execution_time=10.0,
            )
            self.verifier.submit_proof(proof)

        result = self.verifier.verify_consensus(task_id)
        self.assertIsNotNone(result)
        self.assertFalse(result.verified)
        self.assertEqual(result.credit_weight, 0.0)

    def test_tee_verification(self):
        """Test TEE attestation verification."""
        task_id = "task_003"
        output_data = b"expected_output"

        proof = generate_execution_proof(
            device_id="device_tee",
            task_id=task_id,
            output_data=output_data,
            execution_time=10.0,
            has_tee=True,
        )

        expected_hash = proof.output_hash
        result = self.verifier.verify_tee(proof, expected_hash)

        self.assertIsNotNone(result)
        self.assertTrue(result.verified)
        self.assertEqual(result.method, "tee")
        self.assertEqual(result.credit_weight, 1.5)  # TEE bonus

    def test_insufficient_proofs(self):
        """Test verification with insufficient proofs."""
        task_id = "task_004"

        # Submit only 2 proofs (need 3)
        for i in range(2):
            proof = generate_execution_proof(
                device_id=f"device_{i}",
                task_id=task_id,
                output_data=b"output",
                execution_time=10.0,
            )
            self.verifier.submit_proof(proof)

        result = self.verifier.verify_consensus(task_id)
        self.assertIsNone(result)  # Not enough proofs yet


class TestDeviceSafety(unittest.TestCase):
    """Test device safety guards."""

    def setUp(self):
        self.guard = DeviceSafetyGuard()

    def test_safe_device(self):
        """Test safe device metrics."""
        metrics = create_device_metrics(
            battery_level=80,
            is_charging=True,
            temperature_c=45.0,
            cpu_load=0.3,
            memory_load=0.4,
            uptime_hours=10.0,
        )

        result = self.guard.check_safety(metrics)
        self.assertEqual(result.status, SafetyStatus.SAFE)
        self.assertTrue(result.can_accept_task)
        self.assertFalse(result.should_halt_current)

    def test_low_battery(self):
        """Test low battery detection."""
        metrics = create_device_metrics(
            battery_level=20,
            is_charging=False,
            temperature_c=45.0,
            cpu_load=0.3,
            memory_load=0.4,
            uptime_hours=10.0,
        )

        result = self.guard.check_safety(metrics)
        self.assertFalse(result.can_accept_task)
        self.assertIn("Battery low", str(result.warnings))

    def test_critical_temperature(self):
        """Test critical temperature detection."""
        metrics = create_device_metrics(
            battery_level=80,
            is_charging=True,
            temperature_c=85.0,  # Above max
            cpu_load=0.3,
            memory_load=0.4,
            uptime_hours=10.0,
        )

        result = self.guard.check_safety(metrics)
        self.assertEqual(result.status, SafetyStatus.CRITICAL)
        self.assertTrue(result.should_halt_current)

    def test_high_cpu_load(self):
        """Test high CPU load detection."""
        metrics = create_device_metrics(
            battery_level=80,
            is_charging=True,
            temperature_c=45.0,
            cpu_load=0.95,  # Above max
            memory_load=0.4,
            uptime_hours=10.0,
        )

        result = self.guard.check_safety(metrics)
        self.assertFalse(result.can_accept_task)


class TestCreditFormula(unittest.TestCase):
    """Test credit calculation formula."""

    def setUp(self):
        self.formula = CreditFormula()

    def test_base_calculation(self):
        """Test basic credit calculation."""
        result = self.formula.calculate_credits(
            difficulty=5,
            hardware_trust=1.0,
            uptime_hours=24.0,
            verification_confidence=1.0,
            is_charging=False,
        )

        self.assertEqual(result.base_reward, 75)  # Difficulty 5
        self.assertGreater(result.final_credits, 0)

    def test_charging_bonus(self):
        """Test charging bonus."""
        result_no_charge = self.formula.calculate_credits(
            difficulty=5,
            hardware_trust=1.0,
            uptime_hours=24.0,
            verification_confidence=1.0,
            is_charging=False,
        )

        result_charging = self.formula.calculate_credits(
            difficulty=5,
            hardware_trust=1.0,
            uptime_hours=24.0,
            verification_confidence=1.0,
            is_charging=True,
        )

        self.assertGreater(
            result_charging.final_credits, result_no_charge.final_credits
        )

    def test_low_trust_penalty(self):
        """Test low hardware trust penalty."""
        result = self.formula.calculate_credits(
            difficulty=5,
            hardware_trust=0.5,  # Low trust
            uptime_hours=24.0,
            verification_confidence=1.0,
            is_charging=False,
        )

        # Should get fewer credits than full trust
        full_trust = calculate_task_credits(5, 1.0, 24.0, 1.0, False)
        self.assertLess(result.final_credits, full_trust)

    def test_convenience_function(self):
        """Test convenience function."""
        credits = calculate_task_credits(
            difficulty=3,
            hardware_trust=1.0,
            uptime_hours=24.0,
            verification_confidence=1.0,
            is_charging=True,
        )
        self.assertGreater(credits, 0)


class TestLicenseManager(unittest.TestCase):
    """Test license manager plugin."""

    def setUp(self):
        self.manager = LicenseManager()

    def test_open_content(self):
        """Test open content access."""
        content_hash = "hash_001"
        has_access, reason = self.manager.check_access(content_hash, "user_001")
        self.assertTrue(has_access)
        self.assertIn("open", reason.lower())

    def test_time_locked_content(self):
        """Test time-locked content."""
        content_hash = "hash_002"
        future_time = time.time() + 3600

        create_time_locked_content(
            manager=self.manager,
            content_hash=content_hash,
            creator_id="creator_001",
            unlock_timestamp=future_time,
        )

        has_access, reason = self.manager.check_access(content_hash, "user_001")
        self.assertFalse(has_access)
        self.assertIn("Time locked", reason)

    def test_paywalled_content(self):
        """Test paywalled content."""
        content_hash = "hash_003"

        create_paywalled_content(
            manager=self.manager,
            content_hash=content_hash,
            creator_id="creator_001",
            price_credits=100,
        )

        has_access, reason = self.manager.check_access(content_hash, "user_001")
        self.assertFalse(has_access)
        self.assertIn("Payment", reason)

    def test_grant_access(self):
        """Test granting access."""
        content_hash = "hash_004"

        self.manager.create_license(
            content_hash=content_hash,
            license_type=LicenseType.OPEN,
            creator_id="creator_001",
        )

        grant = self.manager.grant_access(
            content_hash=content_hash,
            user_id="user_001",
            reason="Special access",
            duration_hours=24,
        )

        self.assertEqual(grant.user_id, "user_001")
        self.assertEqual(grant.grant_reason, "Special access")

    def test_community_gate(self):
        """Test community-gated content."""
        content_hash = "hash_005"

        create_community_content(
            manager=self.manager,
            content_hash=content_hash,
            creator_id="creator_001",
            allowed_groups=["researchers"],
        )

        # User not in group
        has_access, _ = self.manager.check_access(content_hash, "user_001")
        self.assertFalse(has_access)

        # Add user to group
        self.manager.register_user_group("user_001", "researchers")

        # Now user has access
        has_access, reason = self.manager.check_access(content_hash, "user_001")
        self.assertTrue(has_access)


class TestThresholdRelease(unittest.TestCase):
    """Test threshold release plugin."""

    def setUp(self):
        self.releaser = ThresholdReleaser()

    def test_create_release(self):
        """Test creating a threshold release."""
        release = create_multi_sig_release(
            releaser=self.releaser,
            content_hash="hash_001",
            threshold=3,
            participants=["key_a", "key_b", "key_c", "key_d"],
            duration_days=7,
        )

        self.assertEqual(release.required_signatures, 3)
        self.assertEqual(len(release.authorized_keys), 4)
        self.assertFalse(release.released)

    def test_contribute_signatures(self):
        """Test contributing signatures."""
        release = self.releaser.create_release(
            content_hash="hash_002",
            required_signatures=2,
            authorized_keys=["key_a", "key_b", "key_c"],
        )

        # First signature
        success, msg = self.releaser.contribute_signature(
            release_id=release.release_id, key_id="key_a", signature="sig_a"
        )
        self.assertTrue(success)

        # Second signature (threshold reached)
        success, msg = self.releaser.contribute_signature(
            release_id=release.release_id, key_id="key_b", signature="sig_b"
        )
        self.assertTrue(success)
        self.assertIn("complete", msg.lower())

    def test_unauthorized_key(self):
        """Test unauthorized key contribution."""
        release = self.releaser.create_release(
            content_hash="hash_003",
            required_signatures=2,
            authorized_keys=["key_a", "key_b"],
        )

        success, msg = self.releaser.contribute_signature(
            release_id=release.release_id, key_id="unauthorized_key", signature="sig_x"
        )
        self.assertFalse(success)
        self.assertIn("not authorized", msg.lower())

    def test_get_release_key(self):
        """Test getting released key."""
        release = self.releaser.create_release(
            content_hash="hash_004",
            required_signatures=2,
            authorized_keys=["key_a", "key_b"],
        )

        # Before threshold
        key = self.releaser.get_release_key(release.release_id)
        self.assertIsNone(key)

        # Reach threshold
        self.releaser.contribute_signature(release.release_id, "key_a", "sig_a")
        self.releaser.contribute_signature(release.release_id, "key_b", "sig_b")

        # After threshold
        key = self.releaser.get_release_key(release.release_id)
        self.assertIsNotNone(key)


class TestPluginAccessBoundary(unittest.TestCase):
    """Test that core does NOT import from plugins."""

    def test_core_modules_exist(self):
        """Test that core modules exist and are importable."""
        # These should work without any plugin imports
        from tfp_core.compute.credit_formula import CreditFormula
        from tfp_core.compute.device_safety import DeviceSafetyGuard
        from tfp_core.compute.task_mesh import ComputeMesh
        from tfp_core.compute.verify_habp import HABPVerifier

        self.assertIsNotNone(ComputeMesh)
        self.assertIsNotNone(HABPVerifier)
        self.assertIsNotNone(DeviceSafetyGuard)
        self.assertIsNotNone(CreditFormula)

    def test_plugin_independence(self):
        """Test that plugins can be used independently."""
        # Should be able to use license manager without core compute
        from tfp_plugins.access_control.license_manager import LicenseManager

        manager = LicenseManager()
        self.assertIsNotNone(manager)

        # Should be able to use threshold release independently
        from tfp_plugins.access_control.threshold_release import ThresholdReleaser

        releaser = ThresholdReleaser()
        self.assertIsNotNone(releaser)

    def test_no_drm_in_core(self):
        """Test that core has no DRM enforcement."""
        # Core modules should not have any access control logic
        import inspect

        from tfp_core.compute.task_mesh import ComputeMesh

        source = inspect.getsource(ComputeMesh)

        # Core should not reference license, drm, or access control
        self.assertNotIn("drm", source.lower())
        self.assertNotIn("enforce", source.lower())
        self.assertNotIn("block_access", source.lower())


if __name__ == "__main__":
    unittest.main()
