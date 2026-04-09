import pytest
from tfp_client.lib.routing.asymmetric_uplink.router import (
    AsymmetricUplinkRouter,
    ChannelMetrics,
    CHANNEL_5G,
    CHANNEL_WIFI_MESH,
    CHANNEL_LEO,
)


def test_choose_uplink_returns_channel_id():
    router = AsymmetricUplinkRouter()
    channels = [
        ChannelMetrics(channel_id=CHANNEL_5G, latency=10.0, energy=5.0, drop_rate=0.01),
        ChannelMetrics(channel_id=CHANNEL_WIFI_MESH, latency=20.0, energy=3.0, drop_rate=0.05),
        ChannelMetrics(channel_id=CHANNEL_LEO, latency=50.0, energy=10.0, drop_rate=0.02),
    ]
    result = router.choose_uplink_channel(channels)
    assert isinstance(result, int)
    assert result in (CHANNEL_5G, CHANNEL_WIFI_MESH, CHANNEL_LEO)


def test_lowest_cost_wins():
    router = AsymmetricUplinkRouter(w_latency=0.4, w_energy=0.3, w_drop=0.3)
    channels = [
        ChannelMetrics(channel_id=CHANNEL_5G, latency=100.0, energy=100.0, drop_rate=0.1),
        ChannelMetrics(channel_id=CHANNEL_WIFI_MESH, latency=1.0, energy=1.0, drop_rate=0.01),
        ChannelMetrics(channel_id=CHANNEL_LEO, latency=200.0, energy=200.0, drop_rate=0.2),
    ]
    result = router.choose_uplink_channel(channels)
    assert result == CHANNEL_WIFI_MESH


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        AsymmetricUplinkRouter(w_latency=0.5, w_energy=0.5, w_drop=0.5)


def test_exponential_backoff_on_high_drop_rate():
    router = AsymmetricUplinkRouter()
    high_drop = ChannelMetrics(channel_id=CHANNEL_5G, latency=10.0, energy=5.0, drop_rate=0.8)
    low_drop = ChannelMetrics(channel_id=CHANNEL_5G, latency=10.0, energy=5.0, drop_rate=0.1)
    cost_high = router._cost(high_drop)
    cost_low = router._cost(low_drop)
    assert cost_high > cost_low
    # backoff multiplier > 1 when drop_rate > 0.5
    base_cost = router.w_latency * 10.0 + router.w_energy * 5.0 + router.w_drop * 0.8
    assert cost_high > base_cost  # backoff applied


def test_all_channels_equal_returns_first():
    router = AsymmetricUplinkRouter()
    channels = [
        ChannelMetrics(channel_id=CHANNEL_5G, latency=10.0, energy=5.0, drop_rate=0.1),
        ChannelMetrics(channel_id=CHANNEL_WIFI_MESH, latency=10.0, energy=5.0, drop_rate=0.1),
        ChannelMetrics(channel_id=CHANNEL_LEO, latency=10.0, energy=5.0, drop_rate=0.1),
    ]
    result = router.choose_uplink_channel(channels)
    assert result == CHANNEL_5G  # tie-break = lowest channel_id
