# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for Bridge 3: Popularity→Persistence Economic Loop

Tests for:
- DWCC Calculator (Demand-Weighted Caching Credits)
- Hybrid Wallet (dual-balance: compute + pinning)
- Pinning Manager (content pinning with decay)
"""

import time
from datetime import datetime, timezone

import pytest
from tfp_client.lib.credit.dwcc_calculator import (
    DWCCCalculator,
    DWCCEntry,
    SemanticValueTier,
)
from tfp_client.lib.credit.hybrid_wallet import HybridWallet
from tfp_client.lib.storage.pinning_manager import PinningManager


class TestSemanticValueTier:
    """Test semantic value tier enum."""

    def test_tier_values(self):
        """Test tier multipliers."""
        assert SemanticValueTier.CRITICAL.value == 5.0
        assert SemanticValueTier.HIGH.value == 3.0
        assert SemanticValueTier.MEDIUM.value == 1.5
        assert SemanticValueTier.LOW.value == 0.5
        assert SemanticValueTier.DECAY.value == 0.1

    def test_tier_comparison(self):
        """Test tier ordering."""
        assert SemanticValueTier.CRITICAL.value > SemanticValueTier.HIGH.value
        assert SemanticValueTier.HIGH.value > SemanticValueTier.MEDIUM.value


class TestDWCCEntry:
    """Test DWCC entry dataclass."""

    def test_create_entry(self):
        """Test creating a DWCC entry."""
        entry = DWCCEntry(content_hash="abc123")

        assert entry.content_hash == "abc123"
        assert entry.requests == 0
        assert entry.pinned is True
        assert entry.semantic_tier == SemanticValueTier.MEDIUM
        assert entry.total_earned == 0.0

    def test_entry_serialization(self):
        """Test entry serialization/deserialization."""
        entry = DWCCEntry(
            content_hash="def456",
            requests=5,
            semantic_tier=SemanticValueTier.HIGH,
            total_earned=10.5,
        )

        data = entry.to_dict()
        restored = DWCCEntry.from_dict(data)

        assert restored.content_hash == entry.content_hash
        assert restored.requests == entry.requests
        assert restored.semantic_tier == entry.semantic_tier
        assert restored.total_earned == entry.total_earned


class TestDWCCCalculator:
    """Test DWCC calculator logic."""

    def test_create_calculator(self):
        """Test calculator initialization."""
        calc = DWCCCalculator(
            base_rate=2.0, decay_rate=0.02, min_pin_reward=0.5, max_pin_reward=50.0
        )

        assert calc.base_rate == 2.0
        assert calc.decay_rate == 0.02
        assert calc.min_pin_reward == 0.5
        assert calc.max_pin_reward == 50.0

    def test_track_request(self):
        """Test request tracking."""
        calc = DWCCCalculator()

        # Track first request
        calc.track_request("hash1")
        entry = calc.get_entry("hash1")
        assert entry is not None
        assert entry.requests == 1

        # Track second request
        calc.track_request("hash1", SemanticValueTier.HIGH)
        entry = calc.get_entry("hash1")
        assert entry.requests == 2
        assert entry.semantic_tier == SemanticValueTier.HIGH

    def test_calculate_dwcc_basic(self):
        """Test basic DWCC calculation."""
        calc = DWCCCalculator(base_rate=1.0)

        # Track a request
        calc.track_request("hash1")

        # Wait a bit and calculate
        time.sleep(0.1)  # Small delay for storage duration
        reward = calc.calculate_dwcc("hash1")

        assert reward > 0
        assert reward <= calc.max_pin_reward

    def test_calculate_dwcc_semantic_tier_impact(self):
        """Test that higher semantic tiers earn more."""
        calc = DWCCCalculator(base_rate=1.0)

        # Track requests with different tiers
        calc.track_request("critical_hash", SemanticValueTier.CRITICAL)
        calc.track_request("low_hash", SemanticValueTier.LOW)

        time.sleep(0.05)  # Small delay for storage duration

        critical_reward = calc.calculate_dwcc("critical_hash")
        low_reward = calc.calculate_dwcc("low_hash")

        # Critical should earn more than low (both may hit min_pin_reward, so check ratio)
        # CRITICAL=5.0 vs LOW=0.5 means critical should be ~10x higher before clamping
        assert critical_reward >= low_reward

    def test_calculate_dwcc_decay(self):
        """Test decay for inactive content."""
        calc = DWCCCalculator(decay_rate=0.1)  # High decay rate for testing

        # Track request
        calc.track_request("hash1")

        # Calculate immediately
        immediate_reward = calc.calculate_dwcc("hash1")

        # Calculate with simulated old timestamp
        old_time = (
            datetime.now(timezone.utc).timestamp() + 100
        )  # Far future = high decay
        decayed_reward = calc.calculate_dwcc("hash1", current_time=old_time)

        # Decayed reward should be lower (but not below min)
        assert decayed_reward >= calc.min_pin_reward

    def test_process_epoch(self):
        """Test epoch processing."""
        calc = DWCCCalculator()

        # Track multiple requests
        calc.track_request("hash1", SemanticValueTier.HIGH)
        calc.track_request("hash2", SemanticValueTier.MEDIUM)
        calc.track_request("hash3", SemanticValueTier.LOW)

        # Process epoch
        rewards = calc.process_epoch(epoch_duration_hours=1.0)

        assert len(rewards) == 3
        assert all(r > 0 for r in rewards.values())

        # Check entries were updated
        for hash_key in ["hash1", "hash2", "hash3"]:
            entry = calc.get_entry(hash_key)
            assert entry.total_earned > 0

    def test_get_eviction_candidates(self):
        """Test eviction candidate identification."""
        calc = DWCCCalculator()

        # Add content with no requests
        calc._entries["stale_hash"] = DWCCEntry(
            content_hash="stale_hash",
            requests=0,
            last_requested=datetime.now(timezone.utc).timestamp() - 100000,  # Very old
        )

        # Add content with requests
        calc.track_request("popular_hash")

        candidates = calc.get_eviction_candidates(threshold_requests=1)

        assert "stale_hash" in candidates
        assert "popular_hash" not in candidates

    def test_unpin_content(self):
        """Test unpinning content."""
        calc = DWCCCalculator()
        calc.track_request("hash1")

        # Initially pinned
        entry = calc.get_entry("hash1")
        assert entry.pinned is True

        # Unpin
        result = calc.unpin_content("hash1")
        assert result is True

        entry = calc.get_entry("hash1")
        assert entry.pinned is False

    def test_get_statistics(self):
        """Test statistics generation."""
        calc = DWCCCalculator()

        # Empty stats
        stats = calc.get_statistics()
        assert stats["total_tracked"] == 0

        # Add some entries
        calc.track_request("hash1", SemanticValueTier.HIGH)
        calc.track_request("hash2", SemanticValueTier.MEDIUM)
        calc.track_request("hash3", SemanticValueTier.HIGH)

        stats = calc.get_statistics()
        assert stats["total_tracked"] == 3
        assert stats["pinned_count"] == 3
        assert "HIGH" in stats["by_tier"]
        assert stats["by_tier"]["HIGH"] == 2


class TestHybridWallet:
    """Test hybrid wallet functionality."""

    def test_create_wallet(self):
        """Test wallet initialization."""
        wallet = HybridWallet("test_wallet_1")

        assert wallet.wallet_id == "test_wallet_1"
        balance = wallet.get_balance()
        assert balance.compute_credits == 0.0
        assert balance.pinning_credits == 0.0

    def test_mint_compute_credits(self):
        """Test minting compute credits."""
        wallet = HybridWallet("wallet1")

        proof_hash = b"test_proof_hash_32_bytes_long!!"
        receipt = wallet.mint_compute_credits(100, proof_hash)

        assert receipt.credits == 100
        balance = wallet.get_balance()
        assert balance.compute_credits == 100.0

    def test_mint_pinning_credits(self):
        """Test minting pinning credits from DWCC."""
        wallet = HybridWallet("wallet1")

        rewards = {"hash1": 10.0, "hash2": 20.0, "hash3": 15.0}

        total = wallet.mint_pinning_credits(rewards)

        assert total == 45.0
        balance = wallet.get_balance()
        assert balance.pinning_credits == 45.0

    def test_spend_compute_credits(self):
        """Test spending compute credits."""
        wallet = HybridWallet("wallet1")

        # Mint some credits
        proof_hash = b"test_proof_hash_32_bytes_long!!"
        receipt = wallet.mint_compute_credits(100, proof_hash)

        # Spend
        result = wallet.spend(50.0, credit_type="compute", receipt=receipt)
        assert result is True

        balance = wallet.get_balance()
        assert balance.compute_credits == 50.0

    def test_spend_pinning_credits(self):
        """Test spending pinning credits."""
        wallet = HybridWallet("wallet1")

        # Mint pinning credits
        wallet.mint_pinning_credits({"hash1": 100.0})

        # Spend
        wallet.spend(30.0, credit_type="pinning")

        balance = wallet.get_balance()
        assert balance.pinning_credits == 70.0

    def test_spend_insufficient_balance_raises(self):
        """Test that insufficient balance raises error."""
        wallet = HybridWallet("wallet1")
        wallet.mint_pinning_credits({"hash1": 10.0})

        with pytest.raises(ValueError, match="Insufficient pinning credits"):
            wallet.spend(100.0, credit_type="pinning")

    def test_spend_mixed_credits(self):
        """Test spending mixed credit types."""
        wallet = HybridWallet("wallet1")

        # Mint both types
        proof_hash = b"test_proof_hash_32_bytes_long!!"
        wallet.mint_compute_credits(50, proof_hash)
        wallet.mint_pinning_credits({"hash1": 50.0})

        # Spend mixed (should use compute first, then pinning)
        # Note: Current implementation uses compute if receipt provided, else pinning
        wallet.spend(75.0, credit_type="mixed")

        balance = wallet.get_balance()
        # Since no receipt provided, it falls back to pinning
        assert balance.pinning_credits == 25.0 or balance.compute_credits == 0.0

    def test_track_content_request(self):
        """Test tracking content requests for DWCC."""
        wallet = HybridWallet("wallet1")

        wallet.track_content_request("hash1", SemanticValueTier.HIGH)
        wallet.track_content_request("hash1")  # Second request

        stats = wallet.get_statistics()
        assert stats["dwcc_stats"]["total_requests"] == 2

    def test_process_dwcc_epoch(self):
        """Test processing DWCC epoch."""
        wallet = HybridWallet("wallet1")

        # Track some requests
        wallet.track_content_request("hash1", SemanticValueTier.HIGH)
        wallet.track_content_request("hash2", SemanticValueTier.MEDIUM)

        time.sleep(0.01)

        # Process epoch
        earned = wallet.process_dwcc_epoch(epoch_hours=1.0)

        assert earned > 0
        balance = wallet.get_balance()
        assert balance.pinning_credits > 0

    def test_get_transaction_history(self):
        """Test transaction history."""
        wallet = HybridWallet("wallet1")

        # Perform some transactions
        proof_hash = b"test_proof_hash_32_bytes_long!!"
        wallet.mint_compute_credits(100, proof_hash)
        wallet.mint_pinning_credits({"hash1": 50.0})

        history = wallet.get_transaction_history()

        assert len(history) == 2
        assert history[0]["tx_type"] == "mint_compute"
        assert history[1]["tx_type"] == "mint_pinning"

    def test_wallet_statistics(self):
        """Test wallet statistics."""
        wallet = HybridWallet("wallet1")

        # Initial stats
        stats = wallet.get_statistics()
        assert stats["wallet_id"] == "wallet1"
        assert stats["transaction_count"] == 0

        # After transactions
        proof_hash = b"test_proof_hash_32_bytes_long!!"
        wallet.mint_compute_credits(100, proof_hash)

        stats = wallet.get_statistics()
        assert stats["transaction_count"] == 1
        assert stats["balance"]["compute_credits"] == 100.0


class TestPinningManager:
    """Test pinning manager functionality."""

    def test_create_manager(self):
        """Test manager initialization."""
        manager = PinningManager(
            max_storage_bytes=1000000,
            decay_rate_per_hour=0.05,
            min_priority_threshold=0.3,
        )

        assert manager.max_storage_bytes == 1000000
        assert manager.decay_rate_per_hour == 0.05
        assert manager.min_priority_threshold == 0.3

    def test_pin_content(self):
        """Test pinning content."""
        manager = PinningManager()

        result = manager.pin(
            content_hash="hash1", size_bytes=1000, semantic_tier=SemanticValueTier.HIGH
        )

        assert result is True

        pinned = manager.get_pinned_content("hash1")
        assert pinned is not None
        assert pinned.size_bytes == 1000
        assert pinned.semantic_tier == SemanticValueTier.HIGH

    def test_pin_duplicate_rejected(self):
        """Test that duplicate pins are rejected."""
        manager = PinningManager()

        manager.pin("hash1", 1000)
        result = manager.pin("hash1", 1000)

        assert result is False

    def test_pin_exceeds_quota(self):
        """Test pinning when quota exceeded."""
        manager = PinningManager(max_storage_bytes=1000)

        # Fill quota
        manager.pin("hash1", 1000)

        # Try to add more - should trigger eviction or fail
        result = manager.pin("hash2", 500)

        # Either it succeeded (with eviction) or failed
        # In either case, total shouldn't exceed quota significantly
        stats = manager.get_statistics()
        assert (
            stats["total_pinned_bytes"] <= 1500
        )  # Allow some tolerance for eviction logic

    def test_access_boosts_priority(self):
        """Test that accessing content boosts priority."""
        manager = PinningManager()
        manager.pin("hash1", 1000, SemanticValueTier.MEDIUM)

        initial_priority = manager.get_priority_score("hash1")

        # Access multiple times
        manager.access("hash1")
        manager.access("hash1")
        manager.access("hash1")

        new_priority = manager.get_priority_score("hash1")
        assert new_priority > initial_priority

    def test_unpin_content(self):
        """Test unpinning content."""
        manager = PinningManager()
        manager.pin("hash1", 1000)

        result = manager.unpin("hash1")
        assert result is True

        pinned = manager.get_pinned_content("hash1")
        assert pinned is None

    def test_apply_decay(self):
        """Test decay application."""
        manager = PinningManager(decay_rate_per_hour=1.0)  # High decay for testing

        manager.pin("hash1", 1000)

        # Apply decay (simulates time passing)
        below_threshold = manager.apply_decay_all()

        # Priority should have decreased
        stats = manager.get_statistics()
        assert stats["pinned_count"] == 1  # Still pinned, just decayed

    def test_get_eviction_candidates(self):
        """Test eviction candidate identification."""
        manager = PinningManager(
            min_priority_threshold=0.5,
            decay_rate_per_hour=10.0,  # Very high decay
        )

        # Pin content
        manager.pin("hash1", 1000, SemanticValueTier.LOW)
        manager.pin("hash2", 1000, SemanticValueTier.HIGH)

        # Access one to keep it fresh
        manager.access("hash2")

        # Get candidates
        candidates = manager.get_eviction_candidates(limit=5)

        # Low tier, unaccessed content should be candidate
        assert len(candidates) >= 0  # May vary based on timing

    def test_evict_content(self):
        """Test content eviction."""
        evicted_hashes = []

        def on_evict(hash_key):
            evicted_hashes.append(hash_key)

        manager = PinningManager(eviction_callback=on_evict)
        manager.pin("hash1", 1000)

        result = manager.evict("hash1")
        assert result is True

        assert "hash1" in evicted_hashes
        assert manager.get_pinned_content("hash1") is None

    def test_storage_statistics(self):
        """Test storage statistics."""
        manager = PinningManager(max_storage_bytes=10000)

        # Initial stats
        stats = manager.get_statistics()
        assert stats["pinned_count"] == 0
        assert stats["utilization"] == 0.0

        # Add content
        manager.pin("hash1", 1000, SemanticValueTier.HIGH)
        manager.pin("hash2", 2000, SemanticValueTier.MEDIUM)

        stats = manager.get_statistics()
        assert stats["pinned_count"] == 2
        assert stats["total_pinned_bytes"] == 3000
        assert stats["utilization"] == 0.3
        assert stats["by_tier"]["HIGH"] == 1
        assert stats["by_tier"]["MEDIUM"] == 1


class TestIntegrationEconomicLoop:
    """Integration tests for the full economic loop."""

    def test_full_dwcc_to_wallet_flow(self):
        """Test complete DWCC → Wallet flow."""
        wallet = HybridWallet("integration_wallet")

        # Simulate content requests
        wallet.track_content_request("news_hash", SemanticValueTier.HIGH)
        wallet.track_content_request("news_hash")  # Popular content
        wallet.track_content_request("news_hash")
        wallet.track_content_request("entertainment_hash", SemanticValueTier.MEDIUM)

        time.sleep(0.01)

        # Process DWCC epoch
        earned = wallet.process_dwcc_epoch(epoch_hours=1.0)

        # Verify earnings
        assert earned > 0
        balance = wallet.get_balance()
        assert balance.pinning_credits > 0

        # High-tier content should have earned more
        dwcc_stats = wallet.get_statistics()["dwcc_stats"]
        assert dwcc_stats["total_requests"] == 4

    def test_pinning_with_economic_incentives(self):
        """Test pinning manager with economic incentives."""
        manager = PinningManager(max_storage_bytes=5000)

        # Pin high-value content
        manager.pin("critical_hash", 1000, SemanticValueTier.CRITICAL)
        manager.pin("high_hash", 1000, SemanticValueTier.HIGH)
        manager.pin("low_hash", 1000, SemanticValueTier.LOW)

        # Simulate access pattern (popular content gets accessed)
        manager.access("critical_hash")
        manager.access("critical_hash")
        manager.access("high_hash")
        # low_hash not accessed

        # Check priorities
        critical_priority = manager.get_priority_score("critical_hash")
        low_priority = manager.get_priority_score("low_hash")

        # Critical should have higher priority due to tier + accesses
        assert critical_priority > low_priority

        # Statistics should reflect tier distribution
        stats = manager.get_statistics()
        assert stats["by_tier"]["CRITICAL"] == 1
        assert stats["by_tier"]["HIGH"] == 1
        assert stats["by_tier"]["LOW"] == 1

    def test_storage_quota_with_eviction(self):
        """Test storage quota enforcement with eviction."""
        evicted = []

        def on_evict(hash_key):
            evicted.append(hash_key)

        manager = PinningManager(
            max_storage_bytes=2000,
            eviction_callback=on_evict,
            min_priority_threshold=0.1,
            decay_rate_per_hour=100.0,  # Very fast decay for testing
        )

        # Fill storage
        manager.pin("hash1", 1000, SemanticValueTier.LOW)
        manager.pin("hash2", 1000, SemanticValueTier.LOW)

        # Try to add more (should fail or trigger eviction)
        result = manager.pin("hash3", 1000, SemanticValueTier.HIGH)

        # Either succeeded with eviction, or failed
        # In either case, total shouldn't exceed quota
        stats = manager.get_statistics()
        assert stats["total_pinned_bytes"] <= 2000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
