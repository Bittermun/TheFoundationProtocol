# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Pytest integration wrapper for TFP UI interaction flow.
"""

import pytest

try:
    from tests.ui_test_flow import UITestRunner
except ImportError:
    from ui_test_flow import UITestRunner


@pytest.fixture
async def initialized_runner():
    runner = UITestRunner()
    await runner.adapter.initialize()
    return runner


@pytest.mark.asyncio
async def test_ui_onboarding_flow():
    """Verify onboarding and initial device identity generation."""
    runner = UITestRunner()
    success = await runner.test_onboarding()
    assert success is True


@pytest.mark.asyncio
async def test_ui_browse_content_flow(initialized_runner):
    """Verify content discovery and category browsing."""
    success = await initialized_runner.test_browse_content()
    assert success is True


@pytest.mark.asyncio
async def test_ui_play_content_flow(initialized_runner):
    """Verify playback request flow."""
    success = await initialized_runner.test_play_content()
    assert success is True


@pytest.mark.asyncio
async def test_ui_share_flow(initialized_runner):
    """Verify recording and sharing flow."""
    success = await initialized_runner.test_share()
    assert success is True


@pytest.mark.asyncio
async def test_ui_earn_mode_flow(initialized_runner):
    """Verify earn mode toggling."""
    success = await initialized_runner.test_earn_mode()
    assert success is True


@pytest.mark.asyncio
async def test_ui_thanks_view_flow(initialized_runner):
    """Verify thanks contribution summary view."""
    success = await initialized_runner.test_thanks_view()
    assert success is True


@pytest.mark.asyncio
async def test_ui_pin_content_flow(initialized_runner):
    """Verify pinning and unpinning content."""
    success = await initialized_runner.test_pin_content()
    assert success is True


@pytest.mark.asyncio
async def test_ui_offline_handling_flow(initialized_runner):
    """Verify offline handling and network status checks."""
    success = await initialized_runner.test_offline_handling()
    assert success is True
