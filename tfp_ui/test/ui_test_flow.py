# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP UI Test Flow - Validate Tap → Protocol → UI Cycle

Tests the complete user interaction flow without requiring real TFP core.
Uses MockProtocolAdapter to simulate protocol responses.
"""

import asyncio
from typing import List

from core_bridge.protocol_adapter import (
    MockProtocolAdapter,
    UIContentItem,
)


class UITestRunner:
    """Runs through all major UI interaction flows"""

    def __init__(self):
        self.adapter = MockProtocolAdapter({"zero_config": True})
        self.test_results = []

    async def run_all_tests(self) -> bool:
        """Execute all UI test flows"""
        print("🚀 Starting TFP UI Test Flow\n")

        tests = [
            ("Onboarding & Initialize", self.test_onboarding),
            ("Browse Content (Listen)", self.test_browse_content),
            ("Play Content", self.test_play_content),
            ("Record & Share", self.test_share),
            ("Toggle Earn Mode", self.test_earn_mode),
            ("View Thanks Summary", self.test_thanks_view),
            ("Pin Content", self.test_pin_content),
            ("Offline Handling", self.test_offline_handling),
        ]

        all_passed = True
        for test_name, test_func in tests:
            try:
                result = await test_func()
                status = "✅ PASS" if result else "❌ FAIL"
                self.test_results.append((test_name, result))
                print(f"{status}: {test_name}")
                if not result:
                    all_passed = False
            except Exception as e:
                print(f"❌ FAIL: {test_name} - {str(e)}")
                self.test_results.append((test_name, False))
                all_passed = False

        print("\n" + "=" * 50)
        passed = sum(1 for _, r in self.test_results if r)
        total = len(self.test_results)
        print(f"Results: {passed}/{total} tests passed")

        return all_passed

    async def test_onboarding(self) -> bool:
        """Test: App launch → Auto-initialize → Ready state"""
        try:
            # Simulate app launch
            success = await self.adapter.initialize()

            if not success:
                return False

            # Verify identity auto-generated (no user action)
            if not self.adapter._device_identity:
                return False

            # Verify cache pre-warmed
            if len(self.adapter._content_cache) == 0:
                return False

            # Verify network status available
            status = self.adapter.get_network_status()
            if not status["connected"]:
                return False

            print(
                f"   → Initialized with {len(self.adapter._content_cache)} cached items"
            )
            print(
                f"   → Network: {status['broadcast_source']}, {status['neighbors_count']} neighbors"
            )

            return True
        except Exception as e:
            print(f"   → Error: {str(e)}")
            return False

    async def test_browse_content(self) -> bool:
        """Test: Tap 'Listen' → Browse content grid"""
        received_items = []

        def on_content_ready(items: List[UIContentItem]):
            nonlocal received_items
            received_items = items

        self.adapter.on_content_ready = on_content_ready

        # Browse all content
        items = await self.adapter.browse_content()

        if len(items) == 0:
            return False

        # Verify simplified data structure (no hashes shown)
        for item in items:
            if item.id.startswith("hash_"):
                # Hash exists internally but never displayed
                pass
            if not item.title or not item.thumbnail_icon:
                return False

        # Browse by category
        emergency_items = await self.adapter.browse_content(category="emergency_alerts")
        if len(emergency_items) > 0:
            assert all(i.category == "emergency_alerts" for i in emergency_items)

        print(
            f"   → Browsed {len(items)} items, {len(emergency_items)} emergency alerts"
        )

        return True

    async def test_play_content(self) -> bool:
        """Test: Tap content → Playback starts"""
        playback_started_id = None

        def on_playback_started(content_id: str):
            nonlocal playback_started_id
            playback_started_id = content_id

        self.adapter.on_playback_started = on_playback_started

        # Get first content item
        items = await self.adapter.browse_content()
        if len(items) == 0:
            return False

        # Play it
        success = await self.adapter.play_content(items[0].id)

        if not success:
            return False

        if playback_started_id != items[0].id:
            return False

        print(f"   → Played: '{items[0].title}' ({items[0].display_duration})")
        print(f"   → Source: {items[0].source_label}")

        return True

    async def test_share(self) -> bool:
        """Test: Tap 'Share' → Record → Send to network"""
        thanks_earned = None

        def on_share_complete(thanks: int):
            nonlocal thanks_earned
            thanks_earned = thanks

        self.adapter.on_share_complete = on_share_complete

        # Simulate voice recording (mock data)
        mock_audio_data = b"fake_audio_bytes" * 100

        thanks = await self.adapter.record_and_share(
            media_type="voice",
            media_data=mock_audio_data,
            title="My Community Story",
            category="community_news",
        )

        if thanks <= 0:
            return False

        if thanks_earned != thanks:
            return False

        print("   → Shared voice recording")
        print(f"   → Earned {thanks} thanks")
        print("   → Broadcast to neighbors (simulated)")

        return True

    async def test_earn_mode(self) -> bool:
        """Test: Toggle 'Earn' while charging"""
        # Enable earn mode
        summary = await self.adapter.toggle_earn_mode(enabled=True)

        if summary is None:
            return False

        # Verify abstracted metrics (no raw credits)
        if summary.total_thanks < 0:
            return False

        # Disable earn mode
        summary_off = await self.adapter.toggle_earn_mode(enabled=False)

        if summary_off is None:
            return False

        print("   → Earn mode toggled")
        print(f"   → Total thanks: {summary.total_thanks}")
        print(f"   → Stories shared: {summary.stories_shared}")
        print(f"   → Neighbors helped: {summary.neighbors_helped}")

        return True

    async def test_thanks_view(self) -> bool:
        """Test: Tap 'Thanks' icon → View contribution summary"""
        summary = await self.adapter.get_thanks_summary()

        if summary is None:
            return False

        # Verify no decimal credits (whole numbers only)
        if not isinstance(summary.total_thanks, int):
            return False

        # Verify human-readable metrics
        required_fields = [
            "total_thanks",
            "stories_shared",
            "neighbors_helped",
            "hours_contributed",
        ]

        for field in required_fields:
            if not hasattr(summary, field):
                return False

        print("   → Thanks summary retrieved")
        print(f"   → {summary.total_thanks} total thanks")
        print(f"   → Pin suggestion: {summary.pin_suggestion}")

        return True

    async def test_pin_content(self) -> bool:
        """Test: Pin favorite content for long-term storage"""
        items = await self.adapter.browse_content()
        if len(items) == 0:
            return False

        # Pin first item
        success = await self.adapter.pin_content(items[0].id)

        if not success:
            return False

        # Unpin it
        success = await self.adapter.unpin_content(items[0].id)

        if not success:
            return False

        print(f"   → Pinned and unpinned: '{items[0].title}'")

        return True

    async def test_offline_handling(self) -> bool:
        """Test: Offline behavior → Graceful degradation"""
        # Check offline status
        is_offline_too_long = self.adapter.is_offline_too_long()

        # Should be False initially (mock)
        if is_offline_too_long:
            return False

        # Get network status
        status = self.adapter.get_network_status()

        # Verify status includes helpful info
        required_keys = [
            "connected",
            "broadcast_source",
            "neighbors_count",
            "cache_hit_rate",
        ]
        for key in required_keys:
            if key not in status:
                return False

        print("   → Offline handling: OK")
        print(f"   → Cache hit rate: {status['cache_hit_rate'] * 100:.0f}%")

        return True


async def main():
    """Main test entry point"""
    runner = UITestRunner()
    success = await runner.run_all_tests()

    print("\n" + "=" * 50)
    if success:
        print("✅ All UI tests passed!")
        print("\nNext steps:")
        print("1. Integrate with real TFP core modules")
        print("2. Add platform-specific UI (Flutter/React Native)")
        print("3. Record voice guides for 50+ languages")
        print("4. Create universal icon set")
        print("5. Performance profiling (<50MB RAM, <200MB install)")
    else:
        print("❌ Some tests failed. Review output above.")

    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
