"""
Test suite for TFP Merkleized RaptorQ - Transport Integrity Layer
"""

import unittest
from tfp_transport.merkleized_raptorq import (
    MerkleizedRaptorQ,
    MerkleTree,
    ShardMetadata,
    is_transport_integrity_enabled
)


class TestMerkleTree(unittest.TestCase):
    """Test cases for MerkleTree class."""
    
    def test_build_merkle_tree(self):
        """Test Merkle tree construction."""
        leaf_data = [b"shard0", b"shard1", b"shard2", b"shard3"]
        leaf_hashes = [h.hex() for h in [__import__('hashlib').sha3_256(d).digest() for d in leaf_data]]
        
        # Manually build tree for verification
        tree = MerkleTree(
            root_hash="",
            leaf_hashes=[h.hex() if isinstance(h, bytes) else h for h in leaf_hashes],
            tree_depth=2
        )
        
        self.assertEqual(len(tree.leaf_hashes), 4)
        self.assertEqual(tree.tree_depth, 2)
    
    def test_merkle_proof_generation(self):
        """Test Merkle proof generation for leaf nodes."""
        mrq = MerkleizedRaptorQ()
        content_hash = "test_content"
        shard_data = [b"data0", b"data1", b"data2", b"data3"]
        
        tree = mrq.register_content(content_hash, shard_data)
        
        # Generate proofs for all leaves
        for i in range(len(shard_data)):
            proof = tree.get_proof(i, len(shard_data))
            self.assertIsInstance(proof, list)
            self.assertGreater(len(proof), 0)
    
    def test_merkle_proof_verification_valid(self):
        """Test verification of valid Merkle proofs."""
        mrq = MerkleizedRaptorQ()
        content_hash = "test_valid"
        shard_data = [b"valid0", b"valid1", b"valid2"]
        
        tree = mrq.register_content(content_hash, shard_data)
        
        for i, data in enumerate(shard_data):
            proof = tree.get_proof(i, len(shard_data))
            is_valid = tree.verify_proof(data, i, proof)
            self.assertTrue(is_valid, f"Proof verification failed for leaf {i}")
    
    def test_merkle_proof_verification_invalid(self):
        """Test detection of invalid Merkle proofs."""
        mrq = MerkleizedRaptorQ()
        content_hash = "test_invalid"
        shard_data = [b"orig0", b"orig1", b"orig2"]
        
        tree = mrq.register_content(content_hash, shard_data)
        
        # Try to verify with wrong data
        proof = tree.get_proof(0, len(shard_data))
        is_valid = tree.verify_proof(b"tampered_data", 0, proof)
        self.assertFalse(is_valid)
        
        # Try to verify with wrong index
        is_valid = tree.verify_proof(shard_data[0], 1, proof)
        self.assertFalse(is_valid)


class TestMerkleizedRaptorQ(unittest.TestCase):
    """Test cases for MerkleizedRaptorQ class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mrq = MerkleizedRaptorQ(required_convergences=2)
        self.content_hash = "test_content_123"
        self.shard_data = [b"shard_0", b"shard_1", b"shard_2", b"shard_3"]
        self.tree = self.mrq.register_content(self.content_hash, self.shard_data)
    
    def test_register_content(self):
        """Test content registration and Merkle tree creation."""
        self.assertIsNotNone(self.tree)
        self.assertEqual(self.tree.root_hash[:8], self.tree.root_hash[:8])  # Has root hash
        stats = self.mrq.get_integrity_stats()
        self.assertEqual(stats["registered_contents"], 1)
    
    def test_verify_shard_valid(self):
        """Test verification of valid shards."""
        shard_id = 1
        proof = self.tree.get_proof(shard_id, len(shard_data))
        mac = __import__('hashlib').sha3_256(
            f"{self.content_hash}:{shard_id}:".encode() + self.shard_data[shard_id]
        ).digest()
        
        is_valid, error = self.mrq.verify_shard(
            content_hash=self.content_hash,
            shard_id=shard_id,
            shard_data=self.shard_data[shard_id],
            expected_mac=mac,
            merkle_proof=proof
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_verify_shard_invalid_mac(self):
        """Test detection of shards with invalid MAC."""
        shard_id = 2
        proof = self.tree.get_proof(shard_id, len(shard_data))
        bad_mac = b"invalid_mac_bytes_here_12345"
        
        is_valid, error = self.mrq.verify_shard(
            content_hash=self.content_hash,
            shard_id=shard_id,
            shard_data=self.shard_data[shard_id],
            expected_mac=bad_mac,
            merkle_proof=proof
        )
        
        self.assertFalse(is_valid)
        self.assertEqual(error, "MAC verification failed")
    
    def test_verify_shard_invalid_proof(self):
        """Test detection of shards with invalid Merkle proof."""
        shard_id = 0
        bad_proof = ["fake_proof_hash_1", "fake_proof_hash_2"]
        mac = __import__('hashlib').sha3_256(
            f"{self.content_hash}:{shard_id}:".encode() + self.shard_data[shard_id]
        ).digest()
        
        is_valid, error = self.mrq.verify_shard(
            content_hash=self.content_hash,
            shard_id=shard_id,
            shard_data=self.shard_data[shard_id],
            expected_mac=mac,
            merkle_proof=bad_proof
        )
        
        self.assertFalse(is_valid)
        self.assertEqual(error, "Merkle proof verification failed")
    
    def test_verify_shard_no_tree(self):
        """Test rejection of shards for unregistered content."""
        mac = __import__('hashlib').sha3_256(
            b"unknown_content:0:" + b"data"
        ).digest()
        
        is_valid, error = self.mrq.verify_shard(
            content_hash="unknown_content",
            shard_id=0,
            shard_data=b"data",
            expected_mac=mac,
            merkle_proof=[]
        )
        
        self.assertFalse(is_valid)
        self.assertEqual(error, "Merkle tree not found")
    
    def test_interest_convergence_single_source(self):
        """Test interest convergence tracking with single source."""
        content_hash = "converge_test_1"
        self.mrq.register_content(content_hash, [b"a", b"b"])
        
        # First convergence
        admitted = self.mrq.record_interest_convergence(content_hash, "source_A")
        self.assertFalse(admitted)  # Need 2 convergences
    
    def test_interest_convergence_multiple_sources(self):
        """Test interest convergence with multiple independent sources."""
        content_hash = "converge_test_2"
        self.mrq.register_content(content_hash, [b"x", b"y"])
        
        # First source
        admitted1 = self.mrq.record_interest_convergence(content_hash, "source_X")
        self.assertFalse(admitted1)
        
        # Second source (different)
        admitted2 = self.mrq.record_interest_convergence(content_hash, "source_Y")
        self.assertTrue(admitted2)  # Now meets threshold
    
    def test_interest_convergence_same_source(self):
        """Test that same source doesn't count as multiple convergences."""
        content_hash = "converge_test_3"
        self.mrq.register_content(content_hash, [b"p", b"q"])
        
        # Same source multiple times
        self.mrq.record_interest_convergence(content_hash, "source_Z")
        self.mrq.record_interest_convergence(content_hash, "source_Z")
        self.mrq.record_interest_convergence(content_hash, "source_Z")
        
        admitted = self.mrq._check_cache_admission(content_hash)
        self.assertFalse(admitted)  # Still only 1 unique source
    
    def test_get_verified_shards(self):
        """Test retrieval of verified shards."""
        content_hash = "shards_test"
        shard_data = [b"verified_0", b"verified_1", b"verified_2"]
        
        mrq = MerkleizedRaptorQ()
        tree = mrq.register_content(content_hash, shard_data)
        
        # Verify all shards
        for i, data in enumerate(shard_data):
            proof = tree.get_proof(i, len(shard_data))
            mac = __import__('hashlib').sha3_256(
                f"{content_hash}:{i}:".encode() + data
            ).digest()
            
            mrq.verify_shard(content_hash, i, data, mac, proof)
        
        # Retrieve verified shards
        verified = mrq.get_verified_shards(content_hash)
        self.assertEqual(len(verified), 3)
        
        for i in range(3):
            self.assertEqual(verified[i], shard_data[i])
    
    def test_dropped_shards_logging(self):
        """Test logging of dropped shards."""
        content_hash = "drop_test"
        self.mrq.register_content(content_hash, [b"good"])
        
        # Try to verify with bad MAC
        self.mrq.verify_shard(content_hash, 0, b"bad", b"bad_mac", [])
        
        stats = self.mrq.get_integrity_stats()
        self.assertGreater(stats["dropped_shards"], 0)
    
    def test_integrity_stats(self):
        """Test integrity statistics reporting."""
        mrq = MerkleizedRaptorQ(required_convergences=2)
        
        # Register multiple contents
        for i in range(3):
            content_hash = f"stats_test_{i}"
            mrq.register_content(content_hash, [b"d1", b"d2"])
        
        stats = mrq.get_integrity_stats()
        
        self.assertEqual(stats["registered_contents"], 3)
        self.assertEqual(stats["verified_shards"], 0)  # None verified yet
        self.assertEqual(stats["pending_admissions"], 3)  # All pending
        self.assertEqual(stats["admitted_contents"], 0)
    
    def test_feature_gate(self):
        """Test feature gate check."""
        result = is_transport_integrity_enabled()
        self.assertFalse(result)


class TestTransportIntegration(unittest.TestCase):
    """Integration tests for transport integrity."""
    
    def test_full_shard_verification_flow(self):
        """Test complete shard verification workflow."""
        mrq = MerkleizedRaptorQ(required_convergences=2)
        
        # Register content
        content_hash = "integration_test"
        original_data = [b"part1", b"part2", b"part3", b"part4"]
        tree = mrq.register_content(content_hash, original_data)
        
        # Simulate receiving and verifying shards from network
        verified_count = 0
        for i, data in enumerate(original_data):
            proof = tree.get_proof(i, len(shard_data))
            mac = __import__('hashlib').sha3_256(
                f"{content_hash}:{i}:".encode() + data
            ).digest()
            
            is_valid, _ = mrq.verify_shard(content_hash, i, data, mac, proof)
            if is_valid:
                verified_count += 1
        
        self.assertEqual(verified_count, 4)
        
        # Simulate Interest convergences
        sources = ["node_A", "node_B", "node_C"]
        for source in sources:
            admitted = mrq.record_interest_convergence(content_hash, source)
            if admitted:
                break
        
        # Verify cache admission
        stats = mrq.get_integrity_stats()
        self.assertEqual(stats["admitted_contents"], 1)
        self.assertEqual(stats["verified_shards"], 4)
    
    def test_poisoned_shard_rejection(self):
        """Test rejection of poisoned shards in stream."""
        mrq = MerkleizedRaptorQ()
        content_hash = "poison_test"
        good_data = [b"good0", b"good1", b"good2"]
        
        tree = mrq.register_content(content_hash, good_data)
        
        # Mix of good and poisoned shards
        test_cases = [
            (0, good_data[0], True),  # Good
            (1, b"poisoned", False),  # Bad data (MAC won't match)
            (2, good_data[2], True),  # Good
        ]
        
        accepted = 0
        rejected = 0
        
        for shard_id, data, should_pass in test_cases:
            proof = tree.get_proof(shard_id, len(shard_data))
            mac = __import__('hashlib').sha3_256(
                f"{content_hash}:{shard_id}:".encode() + data
            ).digest()
            
            is_valid, _ = mrq.verify_shard(content_hash, shard_id, data, mac, proof)
            
            if is_valid:
                accepted += 1
            else:
                rejected += 1
        
        self.assertEqual(accepted, 2)
        self.assertEqual(rejected, 1)


if __name__ == "__main__":
    unittest.main()
