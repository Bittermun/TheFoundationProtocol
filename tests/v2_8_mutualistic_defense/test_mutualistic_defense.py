"""
TDD Tests for Mutualistic Defense System v2.8

Tests cover:
1. Local trust cache behavior (no global consensus)
2. Tag decay and refresh mechanisms
3. Randomized sampling for low-volume content
4. Cooldown vs slashing
5. Domain-specific expertise weighting
6. Heuristic pack versioning and signature verification
7. Gossip signal propagation
8. Edge cases: Sybil attacks, false positives, audit fatigue
"""

import unittest
import time
from tfp_core.security.mutualistic_defense import (
    TrustLevel, AuditorProfile, ContentTag, HeuristicPack,
    LocalTrustCache, GossipVerifier, MutualisticAuditor
)


class TestAuditorProfile(unittest.TestCase):
    """Test auditor reputation tracking."""
    
    def test_initial_state(self):
        profile = AuditorProfile(auditor_id='test_1')
        self.assertEqual(profile.trust_level, TrustLevel.NEUTRAL)
        self.assertEqual(profile.accuracy_score, 0.5)
        self.assertFalse(profile.is_on_cooldown())
    
    def test_accuracy_updates(self):
        profile = AuditorProfile(auditor_id='test_1')
        
        # Simulate 10 correct audits
        for _ in range(10):
            profile.update_accuracy(was_correct=True)
        
        self.assertEqual(profile.total_audits, 10)
        self.assertEqual(profile.correct_audits, 10)
        self.assertEqual(profile.accuracy_score, 1.0)
    
    def test_trust_level_promotion(self):
        profile = AuditorProfile(auditor_id='test_1')
        
        # Reach HIGHLY_TRUSTED threshold
        for _ in range(50):
            profile.update_accuracy(was_correct=True)
        
        self.assertEqual(profile.trust_level, TrustLevel.HIGHLY_TRUSTED)
    
    def test_trust_level_demotion(self):
        profile = AuditorProfile(auditor_id='test_1')
        
        # Many false positives
        for _ in range(10):
            profile.update_accuracy(was_correct=False)
        
        self.assertEqual(profile.trust_level, TrustLevel.SUSPICIOUS)
    
    def test_cooldown_application(self):
        profile = AuditorProfile(auditor_id='test_1')
        self.assertFalse(profile.is_on_cooldown())
        
        profile.apply_cooldown(duration_hours=1.0)
        self.assertTrue(profile.is_on_cooldown())
        
        # Wait for cooldown to expire (simulated)
        profile.cooldown_until = time.time() - 100
        self.assertFalse(profile.is_on_cooldown())
    
    def test_domain_expertise(self):
        profile = AuditorProfile(auditor_id='test_1')
        
        # Update accuracy in specific domain
        for _ in range(5):
            profile.update_accuracy(was_correct=True, category='video')
        
        self.assertGreater(profile.get_domain_weight('video'), 0.5)
        self.assertEqual(profile.get_domain_weight('audio'), 0.5)  # Default


class TestContentTag(unittest.TestCase):
    """Test content tagging with decay."""
    
    def test_tag_creation(self):
        tag = ContentTag(
            content_hash='abc123',
            tag_type='malware',
            confidence=0.9
        )
        self.assertEqual(tag.confidence, 0.9)
        self.assertEqual(len(tag.attestations), 0)
    
    def test_tag_decay(self):
        tag = ContentTag(
            content_hash='abc123',
            tag_type='malware',
            confidence=1.0,
            half_life_days=7.0
        )
        
        # Simulate 7 days passing
        original_time = tag.last_refreshed
        tag.last_refreshed = time.time() - (7 * 86400)
        
        new_confidence = tag.decay()
        self.assertAlmostEqual(new_confidence, 0.5, places=1)
    
    def test_needs_refresh(self):
        tag = ContentTag(
            content_hash='abc123',
            tag_type='suspicious',
            confidence=0.8
        )
        
        # Fresh tag with no attestations needs refresh
        self.assertTrue(tag.needs_refresh())
        
        # Add attestations
        tag.add_attestation('auditor_1')
        tag.add_attestation('auditor_2')
        tag.last_refreshed = time.time()
        tag.confidence = 0.9
        
        self.assertFalse(tag.needs_refresh())
    
    def test_attestation_addition(self):
        tag = ContentTag(
            content_hash='abc123',
            tag_type='malware',
            confidence=0.7
        )
        
        original_refreshed = tag.last_refreshed
        tag.add_attestation('auditor_1')
        self.assertIn('auditor_1', tag.attestations)
        # last_refreshed should be updated (greater than or equal to original)
        self.assertGreaterEqual(tag.last_refreshed, original_refreshed)
        
        # Duplicate attestation should not add again
        initial_count = len(tag.attestations)
        tag.add_attestation('auditor_1')
        self.assertEqual(len(tag.attestations), initial_count)


class TestLocalTrustCache(unittest.TestCase):
    """Test local trust cache isolation."""
    
    def test_cache_isolation(self):
        cache1 = LocalTrustCache(device_id='device_1')
        cache2 = LocalTrustCache(device_id='device_2')
        
        # Pin different auditors
        cache1.pin_auditor('auditor_a')
        cache2.pin_auditor('auditor_b')
        
        self.assertIn('auditor_a', cache1.trusted_pinned)
        self.assertNotIn('auditor_a', cache2.trusted_pinned)
    
    def test_eviction_policy(self):
        cache = LocalTrustCache(device_id='device_1', max_auditors=5)
        
        # Add 6 auditors with varying accuracy
        for i in range(6):
            aid = f'auditor_{i}'
            cache.auditors[aid] = AuditorProfile(auditor_id=aid)
            cache.auditors[aid].accuracy_score = 0.5 + (i * 0.1)
        
        # Trigger eviction
        cache._evict_lowest_trust()
        
        self.assertEqual(len(cache.auditors), 5)
        # Lowest accuracy auditor should be removed
        self.assertNotIn('auditor_0', cache.auditors)
    
    def test_pinned_auditor_protection(self):
        cache = LocalTrustCache(device_id='device_1', max_auditors=3)
        
        # Add and pin an auditor
        cache.auditors['protected'] = AuditorProfile(auditor_id='protected')
        cache.auditors['protected'].accuracy_score = 0.1  # Very low
        cache.pin_auditor('protected')
        
        # Add more auditors to trigger eviction
        for i in range(4):
            cache.auditors[f'auditor_{i}'] = AuditorProfile(auditor_id=f'auditor_{i}')
        
        cache._evict_lowest_trust()
        
        # Protected auditor should remain despite low score
        self.assertIn('protected', cache.auditors)
    
    def test_domain_filtered_auditors(self):
        cache = LocalTrustCache(device_id='device_1')
        
        # Add auditor with video expertise
        profile = AuditorProfile(auditor_id='video_expert')
        profile.trust_level = TrustLevel.TRUSTED
        profile.domain_expertise['video'] = 0.9
        cache.auditors['video_expert'] = profile
        
        result = cache.get_trusted_auditors(category='video')
        self.assertIn('video_expert', result)
        
        # Should not appear for unrelated category
        result_audio = cache.get_trusted_auditors(category='audio')
        self.assertNotIn('video_expert', result_audio)


class TestGossipVerifier(unittest.TestCase):
    """Test gossip protocol for trust signals."""
    
    def test_signal_broadcast(self):
        gossip = GossipVerifier(device_id='device_1')
        signal = gossip.broadcast_trust_signal(
            auditor_id='auditor_x',
            outcome=True,
            category='video'
        )
        
        self.assertEqual(signal['reporter'], 'device_1')
        self.assertEqual(signal['auditor'], 'auditor_x')
        self.assertTrue(signal['outcome'])
        self.assertIn('signature', signal)
    
    def test_signal_expiry(self):
        gossip = GossipVerifier(device_id='device_1')
        
        # Create expired signal
        old_signal = {
            'reporter': 'device_2',
            'auditor': 'auditor_x',
            'outcome': True,
            'timestamp': time.time() - (48 * 3600),  # 48 hours ago
            'signature': 'fake_sig'
        }
        
        result = gossip.receive_trust_signal(old_signal)
        self.assertFalse(result)  # Should reject expired
    
    def test_signal_aggregation(self):
        gossip = GossipVerifier(device_id='device_1')
        
        # Add multiple signals
        for i in range(10):
            signal = {
                'reporter': f'device_{i}',
                'auditor': 'target_auditor',
                'outcome': i % 2 == 0,  # 5 positive, 5 negative
                'timestamp': time.time(),
                'signature': 'sig'
            }
            gossip.received_signals.append(signal)
        
        avg, count = gossip.aggregate_signals('target_auditor')
        self.assertEqual(count, 10)
        self.assertAlmostEqual(avg, 0.5, places=2)


class TestMutualisticAuditor(unittest.TestCase):
    """Test main auditing engine."""
    
    def setUp(self):
        self.auditor = MutualisticAuditor(device_id='test_device')
    
    def test_randomized_sampling_high_volume(self):
        """High-volume content always gets audited."""
        result = self.auditor.audit_content(
            content_hash='popular_video',
            content_data=b'test_data',
            category='video',
            request_count=150  # > 100 threshold
        )
        
        self.assertNotEqual(result['status'], 'skipped')
    
    def test_randomized_sampling_low_volume(self):
        """Low-volume content sampled at 3% rate."""
        # Run multiple times to check sampling rate
        audited_count = 0
        total_runs = 1000
        
        for _ in range(total_runs):
            result = self.auditor.audit_content(
                content_hash=f'obscure_{_}',
                content_data=b'test_data',
                category='video',
                request_count=50  # < 100 threshold
            )
            if result['status'] != 'skipped':
                audited_count += 1
        
        # Should be approximately 3%
        sample_rate = audited_count / total_runs
        self.assertAlmostEqual(sample_rate, 0.03, delta=0.02)
    
    def test_cooldown_instead_of_slashing(self):
        """False positives trigger cooldown, not credit destruction."""
        # Setup auditor profile
        self.auditor.trust_cache.auditors['bad_auditor'] = AuditorProfile(
            auditor_id='bad_auditor'
        )
        
        # Report multiple false positives
        for _ in range(5):
            self.auditor.report_audit_outcome(
                auditor_id='bad_auditor',
                was_correct=False,
                category='video'
            )
        
        # Should be on cooldown
        profile = self.auditor.trust_cache.get_auditor('bad_auditor')
        self.assertTrue(profile.is_on_cooldown())
        # Credits should NOT be destroyed (no slashing)
        # Accuracy can be 0 if all audits are wrong, but profile still exists
        self.assertIsNotNone(profile)
        self.assertEqual(profile.total_audits, 5)  # Audits tracked, not erased
    
    def test_heuristic_pack_signature_verification(self):
        """Invalid heuristic packs rejected."""
        import hashlib
        
        valid_pack = HeuristicPack(
            version='1.0.0',
            signature='invalid_sig',
            rules={'rule1': {'pattern': 'deadbeef', 'severity': 'critical'}}
        )
        
        # Generate correct signature
        data = f"{valid_pack.version}:{str(valid_pack.rules)}".encode()
        valid_pack.signature = hashlib.sha3_256(data).hexdigest()[:16]
        
        result = self.auditor.update_heuristic_pack(valid_pack, b'public_key')
        self.assertTrue(result)
        
        # Tampered pack should fail
        valid_pack.rules['rule1']['severity'] = 'low'
        result = self.auditor.update_heuristic_pack(valid_pack, b'public_key')
        self.assertFalse(result)
    
    def test_tag_decay_cleanup(self):
        """Old low-confidence tags removed."""
        # Add tag
        self.auditor.active_tags['old_tag'] = ContentTag(
            content_hash='old_tag',
            tag_type='suspicious',
            confidence=0.4
        )
        # Age it
        self.auditor.active_tags['old_tag'].last_refreshed = time.time() - (30 * 86400)
        
        self.auditor.decay_all_tags()
        
        # Should be removed due to low confidence
        self.assertNotIn('old_tag', self.auditor.active_tags)
    
    def test_domain_specific_weighting(self):
        """Auditors weighted by domain expertise."""
        # Setup trusted auditor with video expertise
        profile = AuditorProfile(auditor_id='video_expert')
        profile.trust_level = TrustLevel.HIGHLY_TRUSTED
        profile.accuracy_score = 0.95
        profile.domain_expertise['video'] = 0.95
        self.auditor.trust_cache.auditors['video_expert'] = profile
        self.auditor.trust_cache.pin_auditor('video_expert')
        
        # Audit video content
        result = self.auditor.audit_content(
            content_hash='video_test',
            content_data=b'high_entropy_data' + b'\xff' * 100,
            category='video',
            request_count=150
        )
        
        # Confidence should be boosted by expert auditor
        self.assertGreater(result['confidence'], 0.5)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and attack scenarios."""
    
    def test_sybil_attack_resistance(self):
        """Multiple fake auditors have limited impact on local cache."""
        auditor = MutualisticAuditor(device_id='victim_device')
        
        # Attacker creates 100 fake auditor identities
        for i in range(100):
            fake_id = f'fake_auditor_{i}'
            auditor.trust_cache.auditors[fake_id] = AuditorProfile(auditor_id=fake_id)
            auditor.trust_cache.auditors[fake_id].accuracy_score = 0.4  # Low accuracy
        
        # Victim has 2 pinned trusted auditors
        real_auditor = AuditorProfile(auditor_id='real_expert')
        real_auditor.trust_level = TrustLevel.HIGHLY_TRUSTED
        real_auditor.accuracy_score = 0.98
        real_auditor.domain_expertise['video'] = 0.95
        auditor.trust_cache.auditors['real_expert'] = real_auditor
        auditor.trust_cache.pin_auditor('real_expert')
        
        # Get trusted auditors for video
        trusted = auditor.trust_cache.get_trusted_auditors(category='video')
        
        # Only real expert should be in list (fakes have low accuracy)
        self.assertIn('real_expert', trusted)
        self.assertLess(len(trusted), 10)  # Not all 100 fakes
    
    def test_audit_fatigue_prevention(self):
        """Rate limiting prevents request flooding."""
        auditor = MutualisticAuditor(device_id='test')
        
        # Simulate rapid requests
        results = []
        for i in range(100):
            result = auditor.audit_content(
                content_hash=f'flood_{i}',
                content_data=b'data',
                category='video',
                request_count=1000  # High volume
            )
            results.append(result)
        
        # All should be processed (no artificial limit in single device)
        # But in production, gateway would rate-limit
        self.assertEqual(len([r for r in results if r['status'] == 'audited']), 100)
    
    def test_false_positive_recovery(self):
        """Auditors can recover from mistakes via cooldown expiry."""
        auditor = MutualisticAuditor(device_id='test')
        
        profile = AuditorProfile(auditor_id='mistaken_auditor')
        auditor.trust_cache.auditors['mistaken_auditor'] = profile
        
        # Make mistakes
        for _ in range(5):
            auditor.report_audit_outcome(
                auditor_id='mistaken_auditor',
                was_correct=False,
                category='video'
            )
        
        # On cooldown
        self.assertTrue(profile.is_on_cooldown())
        
        # Simulate cooldown expiry
        profile.cooldown_until = time.time() - 1000
        
        # Make correct audits
        for _ in range(10):
            auditor.report_audit_outcome(
                auditor_id='mistaken_auditor',
                was_correct=True,
                category='video'
            )
        
        # Should recover trust
        self.assertGreater(profile.accuracy_score, 0.6)
        self.assertFalse(profile.is_on_cooldown())
    
    def test_low_volume_malware_detection(self):
        """Randomized sampling catches malware even with <100 requests."""
        auditor = MutualisticAuditor(device_id='test')
        
        # Add heuristic rule for malware pattern
        import hashlib
        pack = HeuristicPack(
            version='1.0.0',
            signature='',
            rules={
                'malware_sig': {
                    'pattern': 'deadbeefcafe',
                    'severity': 'critical',
                    'category': 'video'
                }
            }
        )
        data = f"{pack.version}:{str(pack.rules)}".encode()
        pack.signature = hashlib.sha3_256(data).hexdigest()[:16]
        auditor.update_heuristic_pack(pack, b'key')
        
        # Malicious content with low requests
        malware_data = b'normal_video_header' + b'\xde\xad\xbe\xef\xca\xfe' + b'rest_of_video'
        
        detected = False
        # Run multiple times to catch via random sampling
        for _ in range(100):
            result = auditor.audit_content(
                content_hash='stealth_malware',
                content_data=malware_data,
                category='video',
                request_count=50  # Below threshold
            )
            if result.get('heuristic_match'):
                detected = True
                break
        
        # Should eventually detect via random sampling
        self.assertTrue(detected)


if __name__ == '__main__':
    unittest.main()
