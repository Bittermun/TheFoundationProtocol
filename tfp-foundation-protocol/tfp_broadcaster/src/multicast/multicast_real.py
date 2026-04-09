"""
Real multicast adapter — UDP socket multicast (239.0.0.1:5007).
Falls back to in-memory queue if socket bind fails (test/CI environments).
Interface matches MulticastAdapter exactly.
"""
from __future__ import annotations
import asyncio
import logging
import os
import socket
import struct
import time
from typing import List

log = logging.getLogger(__name__)

MCAST_GRP = os.getenv("TFP_MCAST_GRP", "239.0.0.1")
MCAST_PORT = int(os.getenv("TFP_MCAST_PORT", "5007"))
_TIMEOUT = float(os.getenv("TFP_MCAST_TIMEOUT", "2.0"))
_RETRIES = int(os.getenv("TFP_MCAST_RETRIES", "2"))
_MAX_SHARD_UDP = 65000  # max UDP payload per datagram


class RealMulticastAdapter:
    """
    Real UDP multicast adapter.
    Sends shards over 239.0.0.1:5007 (IP multicast group).
    Falls back to in-memory queue if socket is unavailable.
    """

    def __init__(self, group: str = MCAST_GRP, port: int = MCAST_PORT):
        self._group = group
        self._port = port
        self._transmissions: List[dict] = []
        self._sock: socket.socket | None = None
        self._fallback_mode = False
        self._init_socket()

    def _init_socket(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
            sock.settimeout(_TIMEOUT)
            self._sock = sock
        except OSError as e:
            log.warning("Multicast socket init failed (%s) — fallback mode active", e)
            self._fallback_mode = True

    def transmit(self, shards: List[bytes], channel: str = "UDP-Multicast") -> None:
        """Sync transmit — runs async in executor."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._async_transmit(shards, channel))
        finally:
            loop.close()

    async def _async_transmit(self, shards: List[bytes], channel: str = "UDP-Multicast") -> None:
        self._transmissions.append({"shards": shards, "channel": channel, "ts": time.time()})
        if self._fallback_mode or self._sock is None:
            log.debug("Multicast fallback: %d shards queued in-memory", len(shards))
            return

        dest = (self._group, self._port)
        for attempt in range(_RETRIES + 1):
            try:
                loop = asyncio.get_event_loop()
                for i, shard in enumerate(shards):
                    # Chunk if shard exceeds UDP MTU
                    for offset in range(0, len(shard), _MAX_SHARD_UDP):
                        chunk = shard[offset:offset + _MAX_SHARD_UDP]
                        await loop.run_in_executor(
                            None, self._sock.sendto, chunk, dest
                        )
                return
            except (OSError, socket.timeout) as e:
                backoff = 0.1 * (2 ** attempt)
                log.warning("Multicast transmit attempt %d failed: %s — retry %.2fs", attempt, e, backoff)
                if attempt < _RETRIES:
                    await asyncio.sleep(backoff)
                else:
                    log.warning("Multicast giving up after %d retries, data queued in-memory", _RETRIES)

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    @property
    def transmission_count(self) -> int:
        return len(self._transmissions)
