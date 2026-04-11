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
import time
from typing import List

log = logging.getLogger(__name__)

MCAST_GRP = os.getenv("TFP_MCAST_GRP", "239.0.0.1")
_MCAST_PORT_RAW = os.getenv("TFP_MCAST_PORT", "5007")
try:
    MCAST_PORT = int(_MCAST_PORT_RAW)
    if not (1 <= MCAST_PORT <= 65535):
        raise ValueError(f"Port must be 1-65535, got {MCAST_PORT}")
except ValueError as e:
    log.error("Invalid TFP_MCAST_PORT '%s': %s. Using default 5007", _MCAST_PORT_RAW, e)
    MCAST_PORT = 5007

_TIMEOUT_RAW = os.getenv("TFP_MCAST_TIMEOUT", "2.0")
try:
    _TIMEOUT = float(_TIMEOUT_RAW)
    if _TIMEOUT <= 0 or _TIMEOUT > 60:
        raise ValueError(f"Timeout must be 0-60 seconds, got {_TIMEOUT}")
except ValueError as e:
    log.error("Invalid TFP_MCAST_TIMEOUT '%s': %s. Using default 2.0", _TIMEOUT_RAW, e)
    _TIMEOUT = 2.0

_RETRIES_RAW = os.getenv("TFP_MCAST_RETRIES", "2")
try:
    _RETRIES = int(_RETRIES_RAW)
    if _RETRIES < 0 or _RETRIES > 10:
        raise ValueError(f"Retries must be 0-10, got {_RETRIES}")
except ValueError as e:
    log.error("Invalid TFP_MCAST_RETRIES '%s': %s. Using default 2", _RETRIES_RAW, e)
    _RETRIES = 2
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

    async def _async_transmit(
        self, shards: List[bytes], channel: str = "UDP-Multicast"
    ) -> None:
        self._transmissions.append(
            {"shards": shards, "channel": channel, "ts": time.time()}
        )
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
                        chunk = shard[offset : offset + _MAX_SHARD_UDP]
                        await loop.run_in_executor(None, self._sock.sendto, chunk, dest)
                return
            except (OSError, socket.timeout) as e:
                backoff = 0.1 * (2**attempt)
                log.warning(
                    "Multicast transmit attempt %d failed: %s — retry %.2fs",
                    attempt,
                    e,
                    backoff,
                )
                if attempt < _RETRIES:
                    await asyncio.sleep(backoff)
                else:
                    log.warning(
                        "Multicast giving up after %d retries, data queued in-memory",
                        _RETRIES,
                    )

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    @property
    def transmission_count(self) -> int:
        return len(self._transmissions)
