"""
Tests for Tag Overlay Index and Bloom Filter
"""

import pytest
import hashlib
from tfp_client.lib.metadata import BloomFilter, TagOverlayIndex


class TestBloomFilter:
    """Test Bloom filter functionality."""
    
    def test_create_empty_filter(self):
        bf = BloomFilter(size_bits=1000, hash_count=5)
        assert bf.size_bits == 1000
        assert bf.hash_count == 5
        assert len(bf) == 0
    
    def test_add_and_contains(self):
        bf = BloomFilter(size_bits=1000, hash_count=5)
        bf.add(b"test_item")
        assert bf.contains(b"test_item") is True
    
    def test_string_support(self):
        bf = BloomFilter()
        bf.add("hello")
        assert bf.contains("hello") is True
    
    def test_false_negative_never_happens(self):
        bf = BloomFilter(size_bits=10000, hash_count=7)
        items = [f"item_{i}".encode() for i in range(100)]
        for item in items:
            bf.add(item)
        
        # All added items must be found (no false negatives)
        for item in items:
            assert bf.contains(item) is True
    
    def test_serialization_roundtrip(self):
        bf = BloomFilter(size_bits=1000, hash_count=5, seed=42)
        bf.add(b"item1")
        bf.add(b"item2")
        
        serialized = bf.serialize()
        restored = BloomFilter.deserialize(serialized)
        
        assert restored.size_bits == bf.size_bits
        assert restored.hash_count == bf.hash_count
        assert restored.seed == bf.seed
        assert restored.contains(b"item1") is True
        assert restored.contains(b"item2") is True
    
    def test_false_positive_rate_estimate(self):
        bf = BloomFilter(size_bits=10000, hash_count=7)
        assert bf.estimated_false_positive_rate() == 0.0
        
        # Add items and check FPR increases
        for i in range(100):
            bf.add(f"item_{i}".encode())
        
        fpr = bf.estimated_false_positive_rate()
        assert 0.0 < fpr < 0.1  # Should be low but not zero
    
    def test_clear_resets_filter(self):
        bf = BloomFilter()
        bf.add(b"test")
        assert bf.contains(b"test") is True
        
        bf.clear()
        assert bf.contains(b"test") is False
        assert len(bf) == 0
    
    def test_union_of_filters(self):
        bf1 = BloomFilter(size_bits=1000, hash_count=5, seed=42)
        bf2 = BloomFilter(size_bits=1000, hash_count=5, seed=42)
        
        bf1.add(b"item1")
        bf2.add(b"item2")
        
        union = bf1.union(bf2)
        assert union.contains(b"item1") is True
        assert union.contains(b"item2") is True
    
    def test_union_mismatch_raises(self):
        bf1 = BloomFilter(size_bits=1000, hash_count=5)
        bf2 = BloomFilter(size_bits=2000, hash_count=5)
        
        with pytest.raises(ValueError):
            bf1.union(bf2)
    
    def test_optimal_size_calculation(self):
        size = BloomFilter.optimal_size(n=1000, p=0.01)
        assert size > 0
        # For 1000 items at 1% FPR, should be ~9600 bits
        assert 9000 < size < 10000
    
    def test_optimal_hash_count_calculation(self):
        k = BloomFilter.optimal_hash_count(m=10000, n=1000)
        assert k >= 1
        # Should be around 7 for these parameters
        assert 5 < k < 10
    
    def test_validation_negative_size(self):
        with pytest.raises(ValueError):
            BloomFilter(size_bits=-1)
    
    def test_validation_negative_hash_count(self):
        with pytest.raises(ValueError):
            BloomFilter(hash_count=0)
    
    def test_deserialize_invalid_data(self):
        with pytest.raises(ValueError):
            BloomFilter.deserialize(b"too_short")


class TestTagOverlayIndex:
    """Test tag overlay index functionality."""
    
    @pytest.fixture
    def index(self):
        return TagOverlayIndex()
    
    def test_add_entry(self, index):
        content_hash = hashlib.sha3_256(b"test content").digest()
        index.add_entry("science", ["physics", "quantum"], content_hash, 0.9)
        
        stats = index.get_stats("science", index._get_current_epoch())
        assert stats["entry_count"] == 2  # One entry per tag
    
    def test_add_entry_invalid_hash(self, index):
        with pytest.raises(ValueError):
            index.add_entry("science", ["tag"], b"short", 0.5)
    
    def test_add_entry_invalid_popularity(self, index):
        content_hash = hashlib.sha3_256(b"test").digest()
        with pytest.raises(ValueError):
            # This will fail in TagEntry validation
            index.add_entry("science", ["tag"], content_hash, 1.5)
    
    def test_build_merkle_dag(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        
        assert dag.epoch == epoch
        assert dag.domain == "science"
        assert len(dag.entries) == 1
        assert len(dag.merkle_root) == 32
    
    def test_build_dag_no_entries(self, index):
        with pytest.raises(ValueError):
            index.build_merkle_dag(202501, "nonexistent")
    
    def test_export_bloom_filter(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics", "biology", "chemistry"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        bloom = index.export_bloom_filter(dag)
        
        assert isinstance(bloom, BloomFilter)
        assert bloom.contains("physics") is True
        assert bloom.contains("biology") is True
    
    def test_query_tag(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        bloom = index.export_bloom_filter(dag)
        
        assert index.query_tag(bloom, "physics") is True
        assert index.query_tag(bloom, "nonexistent") is False
    
    def test_get_entries_by_tag(self, index):
        hash1 = hashlib.sha3_256(b"content1").digest()
        hash2 = hashlib.sha3_256(b"content2").digest()
        
        index.add_entry("science", ["physics"], hash1, 0.9)
        index.add_entry("science", ["physics"], hash2, 0.7)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        entries = index.get_entries_by_tag(dag, "physics")
        
        assert len(entries) == 2
    
    def test_get_popular_entries(self, index):
        hash1 = hashlib.sha3_256(b"popular").digest()
        hash2 = hashlib.sha3_256(b"unpopular").digest()
        
        index.add_entry("science", ["tag"], hash1, 0.95)
        index.add_entry("science", ["tag"], hash2, 0.3)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        popular = index.get_popular_entries(dag, min_popularity=0.8)
        
        assert len(popular) == 1
        assert popular[0].popularity_score == 0.95
    
    def test_merkle_proof_generation(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        proof = index.get_merkle_proof(dag, "physics", content_hash)
        
        assert proof is not None
        assert isinstance(proof, list)
    
    def test_merkle_proof_verification(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        proof = index.get_merkle_proof(dag, "physics", content_hash)
        
        leaf_data = f"physics:{content_hash.hex()}:0.8"
        valid = index.verify_merkle_proof(leaf_data, proof, dag.merkle_root)
        assert valid is True
    
    def test_merkle_proof_tampering_detected(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        proof = index.get_merkle_proof(dag, "physics", content_hash)
        
        # Tamper with leaf data
        tampered_data = f"physics:{content_hash.hex()}:0.9"  # Changed popularity
        valid = index.verify_merkle_proof(tampered_data, proof, dag.merkle_root)
        assert valid is False
    
    def test_dag_serialization(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        
        serialized = dag.to_bytes()
        restored = TagIndexDAG.from_bytes(serialized)
        
        assert restored.epoch == dag.epoch
        assert restored.domain == dag.domain
        assert restored.merkle_root == dag.merkle_root
    
    def test_get_available_epochs(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["tag"], content_hash, 0.8)
        
        epochs = index.get_available_epochs("science")
        assert len(epochs) > 0
    
    def test_clear_epoch(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["tag"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        index.clear_epoch("science", epoch)
        
        epochs = index.get_available_epochs("science")
        assert epoch not in epochs
    
    def test_get_stats(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["physics", "biology"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        stats = index.get_stats("science", epoch)
        
        assert stats["entry_count"] == 2
        assert stats["unique_tags"] == 2
        assert stats["avg_popularity"] == 0.8
    
    def test_get_stats_nonexistent(self, index):
        stats = index.get_stats("nonexistent", 202501)
        assert stats["entry_count"] == 0
    
    def test_tag_normalization(self, index):
        content_hash = hashlib.sha3_256(b"content").digest()
        index.add_entry("science", ["Physics", "PHYSICS"], content_hash, 0.8)
        
        epoch = index._get_current_epoch()
        dag = index.build_merkle_dag(epoch, "science")
        
        # Both should normalize to "physics"
        entries = index.get_entries_by_tag(dag, "physics")
        assert len(entries) == 2


# Import needed for serialization test
from tfp_client.lib.metadata.tag_index import TagIndexDAG
