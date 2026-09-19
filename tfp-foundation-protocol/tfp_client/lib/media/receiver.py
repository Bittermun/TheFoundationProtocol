# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Loss-Resilient Media Stream Receiver for TFP v4.0.

Collects rateless fountain packets, filters Byzantine attacks in O(1),
performs dynamic Gaussian elimination upon reaching rank K, and reassembles
continuous media streams without requiring an uplink ACK/NACK channel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import logging
from pathlib import Path
import socket
import sys
from typing import Callable, Dict, List, Optional, Set, Tuple

# Ensure tfp_core_v4 is importable
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.fountain import FountainCodec, FountainDroplet
from .fountain_streamer import (
    AntiPollutionError,
    MediaDropletPacket,
    MediaStreamError,
)
from .stream_packager import MediaManifest

log = logging.getLogger("tfp.media.receiver")


@dataclass
class ReceiverStats:
    """Real-time reception statistics."""

    packets_received: int = 0
    packets_accepted: int = 0
    packets_duplicate: int = 0
    packets_rejected_auth: int = 0
    bytes_received: int = 0
    chunks_reconstructed: int = 0


class FountainStreamReceiver:
    """
    Asynchronous receiver and decoder for rateless media fountain streams.
    """

    def __init__(
        self,
        symbol_size: int = 512,
        secret_key: bytes = b"tfp-default-streaming-salt",
        verify_tag: bool = True,
    ):
        self.symbol_size = symbol_size
        self.secret_key = secret_key
        self.verify_tag = verify_tag
        self.codec = FountainCodec(symbol_size=symbol_size)

        # Droplet buffers: chunk_index -> {seed: FountainDroplet}
        self._droplet_buffers: Dict[int, Dict[int, FountainDroplet]] = {}
        # Metadata storage: chunk_index -> (k, orig_len)
        self._chunk_meta: Dict[int, Tuple[int, int]] = {}
        # Reconstructed content: chunk_index -> bytes
        self.reconstructed_chunks: Dict[int, bytes] = {}
        # Reception statistics
        self.stats = ReceiverStats()

    def ingest_packet(self, pkt: MediaDropletPacket) -> Optional[Tuple[int, bytes]]:
        """
        Ingest a validated MediaDropletPacket.
        Attempts Gaussian elimination once K distinct droplets are collected.

        Returns:
            (chunk_index, reconstructed_bytes) if this packet triggered reconstruction,
            or None if more droplets are needed or chunk is already complete.
        """
        self.stats.packets_received += 1
        chunk_idx = pkt.chunk_index

        # Already completed?
        if chunk_idx in self.reconstructed_chunks:
            self.stats.packets_duplicate += 1
            return None

        if chunk_idx not in self._droplet_buffers:
            self._droplet_buffers[chunk_idx] = {}
            self._chunk_meta[chunk_idx] = (pkt.k, pkt.orig_len)

        buf = self._droplet_buffers[chunk_idx]
        if pkt.seed in buf:
            self.stats.packets_duplicate += 1
            return None

        droplet = pkt.to_droplet()
        buf[pkt.seed] = droplet
        self.stats.packets_accepted += 1

        k, orig_len = self._chunk_meta[chunk_idx]

        # Attempt reconstruction once we have at least k droplets
        if len(buf) >= k:
            try:
                droplet_list = list(buf.values())
                reconstructed = self.codec.decode(droplet_list, k, orig_len)
                self.reconstructed_chunks[chunk_idx] = reconstructed
                del self._droplet_buffers[chunk_idx]
                self.stats.chunks_reconstructed += 1
                return (chunk_idx, reconstructed)
            except ValueError:
                # Rank deficient (repair symbols had overlapping linear dependencies)
                # Keep collecting additional droplets
                pass

        return None

    def ingest_bytes(self, raw_bytes: bytes) -> Optional[Tuple[int, bytes]]:
        """
        Ingest raw binary packet bytes from the wire.
        Validates anti-pollution HMAC in O(1).
        """
        self.stats.bytes_received += len(raw_bytes)
        try:
            pkt = MediaDropletPacket.from_bytes(
                raw_bytes,
                secret_key=self.secret_key,
                verify_tag=self.verify_tag,
            )
            return self.ingest_packet(pkt)
        except AntiPollutionError:
            self.stats.packets_rejected_auth += 1
            return None
        except Exception as e:
            log.warning(f"Malformed packet dropped: {e}")
            return None

    def is_complete(self, manifest: MediaManifest) -> bool:
        """Check if all chunks in the manifest have been reconstructed."""
        return len(self.reconstructed_chunks) >= manifest.chunk_count

    def assemble(self, manifest: MediaManifest) -> bytes:
        """Reassemble full media payload from reconstructed chunks."""
        if not self.is_complete(manifest):
            missing = set(range(manifest.chunk_count)) - set(self.reconstructed_chunks.keys())
            raise ValueError(f"Cannot assemble media: missing chunks {sorted(missing)}")

        assembled = bytearray()
        for idx in range(manifest.chunk_count):
            chunk = self.reconstructed_chunks[idx]
            expected_hash = manifest.chunk_hashes[idx]
            if not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), expected_hash):
                raise ValueError(f"Integrity check failed on chunk {idx}")
            assembled.extend(chunk)

        return bytes(assembled)

    async def listen_udp(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        on_chunk: Optional[Callable[[int, bytes], None]] = None,
        stop_event: Optional[asyncio.Event] = None,
    ):
        """
        Asynchronously listen for incoming UDP media droplet datagrams.
        """
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind((host, port))

        try:
            while stop_event is None or not stop_event.is_set():
                try:
                    data = await loop.sock_recv(sock, 65535)
                    res = self.ingest_bytes(data)
                    if res is not None and on_chunk is not None:
                        chunk_idx, chunk_bytes = res
                        on_chunk(chunk_idx, chunk_bytes)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.warning(f"Error receiving datagram: {e}")
        finally:
            sock.close()
