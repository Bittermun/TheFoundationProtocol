import dataclasses
from typing import List

CHANNEL_5G = 0
CHANNEL_WIFI_MESH = 1
CHANNEL_LEO = 2


@dataclasses.dataclass
class ChannelMetrics:
    channel_id: int
    latency: float  # ms
    energy: float  # mJ
    drop_rate: float  # 0.0–1.0


class AsymmetricUplinkRouter:
    def __init__(
        self, w_latency: float = 0.4, w_energy: float = 0.3, w_drop: float = 0.3
    ):
        total = w_latency + w_energy + w_drop
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        self.w_latency = w_latency
        self.w_energy = w_energy
        self.w_drop = w_drop

    def _cost(self, m: ChannelMetrics) -> float:
        backoff = 1.0
        if m.drop_rate > 0.5:
            backoff = 2 ** (m.drop_rate * 2)
        return (
            self.w_latency * m.latency
            + self.w_energy * m.energy
            + self.w_drop * m.drop_rate
        ) * backoff

    def choose_uplink_channel(
        self, channels: List[ChannelMetrics], proof_bytes: bytes = None
    ) -> int:
        if not channels:
            raise ValueError("No channels provided")
        best = min(channels, key=lambda c: (self._cost(c), c.channel_id))
        return best.channel_id
