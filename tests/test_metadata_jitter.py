"""
Test suite for TFP Metadata Shield - Privacy Protection Layer
"""

import unittest
import time
from tfp_core.privacy.metadata_shield import (
    MetadataShield,
    PrivacyConfig,
    InterestRecord,
    is_privacy_enabled
)


class TestMetadataShield(unittest.TestCase):
    """Test cases for MetadataShield class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = PrivacyConfig(
            enable_padding=True,
            enable_dummy_requests=True,
            dummy_request_ratio=0.2,
            min_delay_ms=10,
            max_delay_ms=100,
            cache_hit_suppression_window=5.0,
            max_recent_interests=100
        )
        self.shield = MetadataShield(self.config)
    
    def test_initialization(self):
        """Test shield initialization with default and custom config."""
        default_shield = MetadataShield()
        self.assertEqual(default_shield.config.dummy_request_ratio, 0.2)
        
        custom_shield = MetadataShield(self.config)
        self.assertEqual(custom_shield.config.min_delay_ms, 10)
    
    def test_should_send_interest_first_time(self):
        """Test that first interest is allowed with delay."""
        should_send, delay = self.shield.should_send_interest("/tfp/content/test1")
        
        self.assertTrue(should_send)
        self.assertGreaterEqual(delay, 0.0)
        self.assertLessEqual(delay, 0.5)  # Max 500ms default
    
    def test_cache_hit_suppression(self):
        """Test that repeated interests are suppressed within window."""
        interest = "/tfp/content/test2"
        
        # First request
        should_send1, _ = self.shield.should_send_interest(interest)
        self.assertTrue(should_send1)
        self.shield.record_interest(interest)
        
        # Immediate second request should be suppressed
        should_send2, delay2 = self.shield.should_send_interest(interest)
        self.assertFalse(should_send2)
        self.assertEqual(delay2, 0.0)
    
    def test_cache_hit_expiry(self):
        """Test that cache hit suppression expires after window."""
        interest = "/tfp/content/test3"
        
        # Create shield with very short window
        short_config = PrivacyConfig(cache_hit_suppression_window=0.1)
        short_shield = MetadataShield(short_config)
        
        # First request
        should_send1, _ = short_shield.should_send_interest(interest)
        self.assertTrue(should_send1)
        short_shield.record_interest(interest)
        
        # Wait for window to expire
        time.sleep(0.2)
        
        # Should be allowed again (backoff also needs to expire)
        # Clear backoff state to test only cache hit expiry
        short_shield._backoff_state.clear()
        
        should_send2, _ = short_shield.should_send_interest(interest)
        self.assertTrue(should_send2)
    
    def test_dummy_interest_generation(self):
        """Test dummy interest generation for padding."""
        dummies = self.shield.generate_dummy_interests(5)
        
        self.assertEqual(len(dummies), 5)
        for dummy in dummies:
            self.assertTrue(dummy.startswith("/tfp/dummy/"))
            self.assertEqual(len(dummy), len("/tfp/dummy/") + 32)  # hex encoded
    
    def test_dummy_interest_uniqueness(self):
        """Test that generated dummy interests are unique."""
        dummies1 = self.shield.generate_dummy_interests(10)
        time.sleep(0.01)
        dummies2 = self.shield.generate_dummy_interests(10)
        
        all_dummies = dummies1 + dummies2
        self.assertEqual(len(all_dummies), len(set(all_dummies)))
    
    def test_privacy_stats_tracking(self):
        """Test privacy statistics tracking."""
        interest = "/tfp/content/test4"
        
        # Send real interest
        should_send, _ = self.shield.should_send_interest(interest)
        if should_send:
            self.shield.record_interest(interest)
        
        # Generate dummy interests
        dummies = self.shield.generate_dummy_interests(4)
        for dummy in dummies:
            self.shield.record_interest(dummy, is_dummy=True)
        
        stats = self.shield.get_privacy_stats()
        
        self.assertEqual(stats["real_interests"], 1)
        self.assertEqual(stats["dummy_interests"], 4)
        self.assertGreater(stats["total_interests"], 0)
        self.assertAlmostEqual(stats["dummy_ratio"], 0.8, places=1)
    
    def test_backoff_state_management(self):
        """Test exponential backoff state management."""
        interest = "/tfp/content/test5"
        
        # First request
        should_send1, delay1 = self.shield.should_send_interest(interest)
        self.assertTrue(should_send1)
        
        # Update backoff manually for testing
        self.shield._backoff_state[self.shield._hash_interest(interest)] = time.time() + 0.5
        
        # Second request should be delayed
        should_send2, delay2 = self.shield.should_send_interest(interest)
        self.assertFalse(should_send2)
        self.assertGreater(delay2, 0.4)
    
    def test_prune_old_records(self):
        """Test pruning of old interest records."""
        # Fill recent interests
        for i in range(150):
            interest = f"/tfp/content/test{i}"
            self.shield.record_interest(interest)
        
        # Trigger prune by calling with current time
        self.shield._prune_old_records(time.time())
        
        # Should respect max_recent_interests
        self.assertLessEqual(len(self.shield._recent_interests), 100)
    
    def test_hash_interest_consistency(self):
        """Test that interest hashing is consistent."""
        interest = "/tfp/content/consistent_test"
        
        hash1 = self.shield._hash_interest(interest)
        hash2 = self.shield._hash_interest(interest)
        
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA3-256 hex length
    
    def test_randomized_delay_bounds(self):
        """Test that randomized delays stay within bounds."""
        interest = "/tfp/content/delay_test"
        
        for _ in range(100):
            _, delay = self.shield.should_send_interest(f"{interest}_{_}")
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, self.config.max_backoff_ms / 1000.0)
    
    def test_feature_gate(self):
        """Test feature gate check."""
        # Default should be False (env var not set in test)
        result = is_privacy_enabled()
        self.assertFalse(result)


class TestPrivacyIntegration(unittest.TestCase):
    """Integration tests for privacy features."""
    
    def test_full_interest_flow(self):
        """Test complete interest flow with privacy protection."""
        shield = MetadataShield(PrivacyConfig(
            min_delay_ms=5,
            max_delay_ms=50,
            cache_hit_suppression_window=2.0,
            dummy_request_ratio=0.3
        ))
        
        # Simulate user requesting content
        content_interests = [
            "/tfp/content/video1",
            "/tfp/content/audio2",
            "/tfp/content/doc3",
        ]
        
        sent_count = 0
        suppressed_count = 0
        
        for interest in content_interests:
            should_send, delay = shield.should_send_interest(interest)
            
            if should_send:
                shield.record_interest(interest)
                sent_count += 1
                
                # Add dummy traffic
                dummies = shield.generate_dummy_interests(2)
                for dummy in dummies:
                    shield.record_interest(dummy, is_dummy=True)
            else:
                suppressed_count += 1
        
        # Verify some were sent and privacy stats are tracked
        stats = shield.get_privacy_stats()
        self.assertGreater(stats["total_interests"], 0)
        self.assertGreater(stats["dummy_ratio"], 0.1)
    
    def test_concurrent_interest_handling(self):
        """Test handling of concurrent interests."""
        import threading
        
        shield = MetadataShield(PrivacyConfig(max_recent_interests=50))
        results = []
        
        def send_interest(idx):
            interest = f"/tfp/content/concurrent_{idx}"
            should_send, delay = shield.should_send_interest(interest)
            if should_send:
                shield.record_interest(interest)
            results.append((idx, should_send))
        
        threads = [threading.Thread(target=send_interest, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All threads should complete without errors
        self.assertEqual(len(results), 20)
        self.assertTrue(all(isinstance(r[1], bool) for r in results))


if __name__ == "__main__":
    unittest.main()
