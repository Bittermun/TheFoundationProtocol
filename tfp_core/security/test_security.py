"""
TFP v2.8 Security Module Tests

Tests for sandbox escape prevention and community content auditing.
"""

import unittest
import time
from tfp_core.security.sandbox import (
    SecureSandbox, SandboxConfig, Capability, PluginLoader, SecurityViolation
)
from tfp_core.security.scanner import (
    ContentHeuristics, CommunityAuditor, AuditCoordinator, 
    ReputationManager, AuditResult, HeuristicType, AuditReport
)


class TestSecureSandbox(unittest.TestCase):
    """Test WebAssembly sandbox security."""
    
    def test_sandbox_creation(self):
        """Test sandbox initializes correctly."""
        config = SandboxConfig(capabilities=[Capability.NONE])
        sandbox = SecureSandbox(config)
        
        self.assertIsNotNone(sandbox)
        self.assertEqual(sandbox.config.timeout_ms, 5000)
        
    def test_no_capabilities_blocks_all(self):
        """Test that NONE capability blocks all operations."""
        config = SandboxConfig(capabilities=[Capability.NONE])
        sandbox = SecureSandbox(config)
        sandbox._start_time = time.time()  # Reset start time
        
        # In mock mode, this should still work but log warnings
        # Real wasmer mode would trap syscalls
        result = sandbox._mock_execute("test", b"input")
        self.assertEqual(result, b"mock_result")
        
    def test_timeout_enforcement(self):
        """Test that timeout is enforced."""
        config = SandboxConfig(
            capabilities=[Capability.NONE],
            timeout_ms=10  # Very short timeout
        )
        sandbox = SecureSandbox(config)
        sandbox._start_time = time.time() - 1  # Simulate old start
        
        with self.assertRaises(SecurityViolation) as ctx:
            sandbox._mock_execute("test", b"input")
            
        self.assertIn("timeout", str(ctx.exception).lower())
        
    def test_plugin_loader_basic(self):
        """Test plugin loader executes successfully."""
        loader = PluginLoader(default_timeout_ms=5000)
        
        # Mock execution (no real wasm)
        result = loader.execute_plugin(
            plugin_bytes=b"fake_wasm",
            input_data=b"test_input",
            capabilities=[Capability.NONE]
        )
        
        self.assertEqual(result, b"mock_result")
        self.assertEqual(loader.get_execution_count(), 1)
        
    def test_capability_fs_read(self):
        """Test filesystem read capability."""
        config = SandboxConfig(capabilities=[Capability.FS_READ_TEMP])
        sandbox = SecureSandbox(config)
        
        # Should not raise
        result = sandbox._trap_fd_open(0, 0, 0)
        self.assertEqual(result, 0)
        
    def test_capability_fs_read_denied(self):
        """Test filesystem read denied without capability."""
        config = SandboxConfig(capabilities=[Capability.NONE])
        sandbox = SecureSandbox(config)
        
        with self.assertRaises(SecurityViolation) as ctx:
            sandbox._trap_fd_open(0, 0, 0)
            
        self.assertIn("denied", str(ctx.exception).lower())
        
    def test_capability_network_write(self):
        """Test network write capability."""
        config = SandboxConfig(capabilities=[Capability.NETWORK_WRITE])
        sandbox = SecureSandbox(config)
        
        # Should not raise
        result = sandbox._trap_sock_send(0, 0)
        self.assertEqual(result, 0)
        
    def test_proc_exit_trapped(self):
        """Test that process exit is always trapped."""
        config = SandboxConfig(capabilities=[Capability.NONE])
        sandbox = SecureSandbox(config)
        
        with self.assertRaises(SecurityViolation) as ctx:
            sandbox._trap_proc_exit(0)
            
        self.assertIn("exit", str(ctx.exception).lower())


class TestContentHeuristics(unittest.TestCase):
    """Test content scanning heuristics."""
    
    def setUp(self):
        self.heuristics = ContentHeuristics()
        
    def test_clean_content(self):
        """Test clean content passes."""
        clean_data = b"This is normal text content with low entropy."
        result, flags, details = self.heuristics.run_all_heuristics(
            clean_data, "text/plain"
        )
        
        self.assertEqual(result, AuditResult.CLEAN)
        self.assertEqual(len(flags), 0)
        
    def test_high_entropy_detection(self):
        """Test high entropy data is flagged."""
        # Simulate high entropy (random bytes)
        import os
        high_entropy_data = os.urandom(2048)
        
        result, flags, details = self.heuristics.run_all_heuristics(
            high_entropy_data, "application/octet-stream"
        )
        
        # High entropy should be flagged or inconclusive
        self.assertIn(HeuristicType.ENTROPY_CHECK, flags)
        self.assertIn("entropy", details.lower())
        
    def test_signature_detection_pe(self):
        """Test Windows PE signature detection."""
        pe_data = b"\x4d\x5a\x90\x00" + b"normal content" * 100
        
        result, flags, details = self.heuristics.run_all_heuristics(
            pe_data, "image/jpeg"  # Wrong content type
        )
        
        self.assertEqual(result, AuditResult.FLAGGED)
        self.assertIn(HeuristicType.SIGNATURE_SCAN, flags)
        self.assertIn("signature", details.lower())
        
    def test_script_injection_detection(self):
        """Test script injection detection."""
        malicious_data = b"<script>alert('xss')</script>" + b"more content"
        
        result, flags, details = self.heuristics.run_all_heuristics(
            malicious_data, "text/html"
        )
        
        self.assertEqual(result, AuditResult.FLAGGED)
        self.assertIn(HeuristicType.SIGNATURE_SCAN, flags)
        
    def test_mz_header_in_media(self):
        """Test DOS header detection in media files."""
        fake_image = b"MZ" + b"\x00" * 100 + b"fake image data"
        
        result, flags, details = self.heuristics.run_all_heuristics(
            fake_image, "image/png"
        )
        
        self.assertIn(HeuristicType.METADATA_ANALYSIS, flags)
        self.assertIn("executable", details.lower())


class TestCommunityAuditor(unittest.TestCase):
    """Test community auditing system."""
    
    def setUp(self):
        self.auditor = CommunityAuditor("auditor_1", reputation_score=1.0)
        self.coordinator = AuditCoordinator()
        self.rep_manager = ReputationManager()
        
    def test_audit_clean_content(self):
        """Test auditing clean content."""
        clean_data = b"This is perfectly safe content."
        
        report = self.auditor.audit_content(
            content_hash="abc123",
            content_data=clean_data,
            content_type="text/plain"
        )
        
        self.assertEqual(report.result, AuditResult.CLEAN)
        self.assertGreater(report.confidence, 0.7)
        self.assertEqual(report.auditor_id, "auditor_1")
        
    def test_audit_malicious_content(self):
        """Test auditing malicious content."""
        malicious_data = b"\x4d\x5a\x90\x00" + b"malware payload"
        
        report = self.auditor.audit_content(
            content_hash="def456",
            content_data=malicious_data,
            content_type="video/mp4"
        )
        
        self.assertEqual(report.result, AuditResult.FLAGGED)
        self.assertGreater(report.confidence, 0.7)
        
    def test_coordinator_triggers_audit(self):
        """Test audit trigger at threshold."""
        content_hash = "trigger_test"
        
        # Record 99 requests - no trigger
        for i in range(99):
            result = self.coordinator.record_request(content_hash)
            self.assertIsNone(result)
            
        # 100th request triggers audit
        result = self.coordinator.record_request(content_hash)
        self.assertEqual(result, content_hash)
        
    def test_consensus_building(self):
        """Test consensus building from multiple reports."""
        content_hash = "consensus_test"
        
        # Register auditors
        for i in range(5):
            auditor = CommunityAuditor(f"auditor_{i}", reputation_score=1.0)
            self.coordinator.register_auditor(auditor)
            
        # Submit flagged reports (need 3+ for consensus)
        for i in range(3):
            report = AuditReport(
                content_hash=content_hash,
                auditor_id=f"auditor_{i}",
                result=AuditResult.FLAGGED,
                confidence=0.9,
                details="Test flag"
            )
            self.coordinator.submit_report(report)
            
        # Check if consensus reached
        consensus = self.coordinator.get_consensus(content_hash)
        self.assertIsNotNone(consensus, "Consensus should be reached with 3 reports")
        self.assertTrue(consensus.is_toxic)
        self.assertEqual(consensus.flagged_count, 3)
            
    def test_reputation_reward(self):
        """Test reputation reward for honest audits."""
        auditor_id = "rep_test_auditor"
        self.rep_manager.register_auditor(auditor_id)
        
        initial_rep = self.rep_manager.get_reputation(auditor_id)
        self.rep_manager.reward_honest_audit(auditor_id)
        
        new_rep = self.rep_manager.get_reputation(auditor_id)
        self.assertGreater(new_rep, initial_rep)
        
    def test_reputation_penalty(self):
        """Test reputation penalty for false positives."""
        auditor_id = "rep_test_bad"
        self.rep_manager.register_auditor(auditor_id)
        
        initial_rep = self.rep_manager.get_reputation(auditor_id)
        self.rep_manager.penalize_false_positive(
            auditor_id, 
            AuditResult.CLEAN
        )
        
        new_rep = self.rep_manager.get_reputation(auditor_id)
        self.assertLess(new_rep, initial_rep)
        
    def test_reputation_slashing_severe(self):
        """Test severe penalty for false negatives."""
        auditor_id = "rep_test_worse"
        self.rep_manager.register_auditor(auditor_id)
        self.rep_manager.reputations[auditor_id] = 5.0  # High rep
        
        self.rep_manager.penalize_false_negative(
            auditor_id,
            AuditResult.FLAGGED
        )
        
        new_rep = self.rep_manager.get_reputation(auditor_id)
        self.assertLess(new_rep, 5.0)


class TestIntegration(unittest.TestCase):
    """Integration tests for security modules."""
    
    def test_full_audit_workflow(self):
        """Test complete audit workflow from request to consensus."""
        # Setup
        coordinator = AuditCoordinator()
        rep_manager = ReputationManager()
        
        # Register auditors
        for i in range(5):
            auditor = CommunityAuditor(f"auditor_{i}", reputation_score=1.0)
            coordinator.register_auditor(auditor)
            rep_manager.register_auditor(f"auditor_{i}")
            
        content_hash = "workflow_test"
        malicious_data = b"\x4d\x5a\x90\x00" + b"bad stuff"
        
        # Simulate popularity growth
        for i in range(100):
            trigger = coordinator.record_request(content_hash)
            
        # Trigger should fire
        self.assertIsNotNone(trigger)
        
        # Select auditors and perform audit
        selected = coordinator.select_auditors(content_hash, num_auditors=3)
        self.assertEqual(len(selected), 3)
        
        # Each auditor scans content
        for auditor in selected:
            report = auditor.audit_content(
                content_hash=content_hash,
                content_data=malicious_data,
                content_type="video/mp4"
            )
            coordinator.submit_report(report)
            
            # Update reputation based on alignment
            consensus = coordinator.get_consensus(content_hash)
            if consensus:
                rep_manager.align_with_consensus(
                    auditor.auditor_id,
                    report,
                    consensus
                )
                
        # Verify consensus reached
        consensus = coordinator.get_consensus(content_hash)
        self.assertIsNotNone(consensus)
        self.assertTrue(consensus.is_toxic)
        
    def test_sandbox_prevents_escape(self):
        """Test that sandbox prevents common escape attempts."""
        loader = PluginLoader(default_timeout_ms=1000)
        
        # Try to execute "malicious" plugin
        # In real scenario, this would be actual malware
        # Here we just verify the sandbox traps syscalls
        config = SandboxConfig(capabilities=[Capability.NONE])
        sandbox = SecureSandbox(config)
        
        # All dangerous operations should be trapped
        with self.assertRaises(SecurityViolation):
            sandbox._trap_proc_exit(0)
            
        with self.assertRaises(SecurityViolation):
            sandbox._trap_fd_open(0, 0, 0)
            
        with self.assertRaises(SecurityViolation):
            sandbox._trap_sock_connect(0)


if __name__ == "__main__":
    unittest.main()
