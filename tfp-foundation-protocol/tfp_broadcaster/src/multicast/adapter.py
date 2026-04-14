# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from typing import List


class MulticastAdapter:
    """Mock multicast adapter — swap for ATSC 3.0 / DVB-S2 bindings."""

    def __init__(self):
        self._transmissions = []

    def transmit(self, shards: List[bytes], channel: str = "ATSC3.0") -> None:
        self._transmissions.append({"shards": shards, "channel": channel})

    @property
    def transmission_count(self) -> int:
        return len(self._transmissions)
