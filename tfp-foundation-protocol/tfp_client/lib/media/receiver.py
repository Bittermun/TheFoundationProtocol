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
import struct
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
    MANIFEST_MAGIC,
    PACKET_MAGIC,
    PACKET_VERSION,
    deserialize_manifest_packet,
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

        # Droplet buffers: (session_id, chunk_index) -> {seed: FountainDroplet}
        self._droplet_buffers: Dict[Tuple[int, int], Dict[int, FountainDroplet]] = {}
        # Metadata storage: (session_id, chunk_index) -> (k, orig_len)
        self._chunk_meta: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # Reconstructed content: session_id -> {chunk_index: bytes}
        self.reconstructed_chunks_by_session: Dict[int, Dict[int, bytes]] = {}
        self.received_manifests: Dict[int, MediaManifest] = {}
        self.latest_manifest: Optional[MediaManifest] = None
        self._last_active_session: Optional[int] = None
        # Reception statistics
        self.stats = ReceiverStats()

    @property
    def reconstructed_chunks(self) -> Dict[int, bytes]:
        """
        Backwards-compatible view of reconstructed chunks for the most active / recent session.
        """
        if not self.reconstructed_chunks_by_session:
            return {}
        if self._last_active_session is not None and self._last_active_session in self.reconstructed_chunks_by_session:
            return self.reconstructed_chunks_by_session[self._last_active_session]
        latest_sess = max(self.reconstructed_chunks_by_session.keys())
        return self.reconstructed_chunks_by_session[latest_sess]

    @staticmethod
    def derive_session_id(manifest: MediaManifest) -> int:
        """Derive 32-bit uint32 session identifier deterministically from manifest."""
        try:
            return int.from_bytes(bytes.fromhex(manifest.manifest_id)[:4], "big")
        except Exception:
            return int.from_bytes(hashlib.sha256(manifest.manifest_id.encode()).digest()[:4], "big")

    def reset(self, session_id: Optional[int] = None):
        """
        Reset receiver state.
        If session_id is given, clears that specific session's buffers and chunks.
        If session_id is None, clears all sessions.
        """
        if session_id is None:
            self._droplet_buffers.clear()
            self._chunk_meta.clear()
            self.reconstructed_chunks_by_session.clear()
            self._last_active_session = None
        else:
            to_delete = [k for k in self._droplet_buffers if k[0] == session_id]
            for k in to_delete:
                self._droplet_buffers.pop(k, None)
                self._chunk_meta.pop(k, None)
            self.reconstructed_chunks_by_session.pop(session_id, None)
            if self._last_active_session == session_id:
                self._last_active_session = next(iter(self.reconstructed_chunks_by_session), None)

    def ingest_packet(self, pkt: MediaDropletPacket) -> Optional[Tuple[int, bytes]]:
        """
        Ingest a validated MediaDropletPacket into session-isolated buffers.
        Attempts Gaussian elimination once K distinct droplets are collected.

        Returns:
            (chunk_index, reconstructed_bytes) if this packet triggered reconstruction,
            or None if more droplets are needed or chunk is already complete.
        """
        self.stats.packets_received += 1
        session_id = pkt.session_id
        chunk_idx = pkt.chunk_index
        self._last_active_session = session_id

        if session_id not in self.reconstructed_chunks_by_session:
            self.reconstructed_chunks_by_session[session_id] = {}

        session_chunks = self.reconstructed_chunks_by_session[session_id]

        # O(1) Anti-pollution verification of droplet packet HMAC if configured
        if self.verify_tag and self.secret_key and pkt.auth_tag:
            header_pre = struct.pack(
                ">2sBBIIHIHI",
                PACKET_MAGIC,
                PACKET_VERSION,
                0,
                pkt.session_id,
                pkt.chunk_index,
                pkt.k,
                pkt.orig_len,
                pkt.symbol_size,
                pkt.seed,
            )
            expected_tag = hmac.new(
                self.secret_key,
                header_pre + pkt.payload,
                hashlib.sha3_256,
            ).digest()[:16]
            if not hmac.compare_digest(pkt.auth_tag, expected_tag):
                self.stats.packets_rejected_auth += 1
                return None

        # Already completed for this chunk in this session?
        if chunk_idx in session_chunks:
            self.stats.packets_duplicate += 1
            return None

        buf_key = (session_id, chunk_idx)
        if buf_key not in self._droplet_buffers:
            self._droplet_buffers[buf_key] = {}
            self._chunk_meta[buf_key] = (pkt.k, pkt.orig_len)

        buf = self._droplet_buffers[buf_key]
        if pkt.seed in buf:
            self.stats.packets_duplicate += 1
            return None

        droplet = pkt.to_droplet()
        buf[pkt.seed] = droplet
        self.stats.packets_accepted += 1

        k, orig_len = self._chunk_meta[buf_key]

        # Attempt reconstruction once we have at least k droplets
        if len(buf) >= k:
            try:
                droplet_list = list(buf.values())
                reconstructed = self.codec.decode(droplet_list, k, orig_len)

                # Defense-in-depth: Verify reconstructed chunk hash if manifest is known
                target_m = self.received_manifests.get(session_id)
                if target_m and chunk_idx < len(target_m.chunk_hashes):
                    expected_hash = target_m.chunk_hashes[chunk_idx]
                    actual_hash = hashlib.sha3_256(reconstructed).hexdigest()
                    if not hmac.compare_digest(actual_hash, expected_hash):
                        log.warning(
                            f"Reconstructed chunk {chunk_idx} failed integrity for session {session_id}"
                        )
                        return None

                session_chunks[chunk_idx] = reconstructed
                del self._droplet_buffers[buf_key]
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
        Handles both manifest announcements (FM) and media droplets (FD).
        Validates anti-pollution HMAC in O(1).
        """
        self.stats.bytes_received += len(raw_bytes)

        # Check for manifest announcement packet
        if raw_bytes.startswith(MANIFEST_MAGIC):
            try:
                manifest = deserialize_manifest_packet(
                    raw_bytes,
                    secret_key=self.secret_key,
                    verify_tag=self.verify_tag,
                )
                sess_id = self.derive_session_id(manifest)
                self.received_manifests[sess_id] = manifest
                self.latest_manifest = manifest
                self._last_active_session = sess_id
                return (-1, b"")
            except AntiPollutionError:
                self.stats.packets_rejected_auth += 1
                return None
            except Exception as e:
                log.warning(f"Malformed manifest packet dropped: {e}")
                return None

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

    def is_complete(self, manifest: Optional[MediaManifest] = None, session_id: Optional[int] = None) -> bool:
        """Check if all chunks in the manifest have been reconstructed for the target session."""
        target_manifest = manifest if manifest is not None else self.latest_manifest
        if target_manifest is None:
            return False

        if session_id is not None:
            chunks = self.reconstructed_chunks_by_session.get(session_id, {})
        else:
            derived = self.derive_session_id(target_manifest)
            if derived in self.reconstructed_chunks_by_session:
                chunks = self.reconstructed_chunks_by_session[derived]
            else:
                chunks = {}
                for sess, s_chunks in self.reconstructed_chunks_by_session.items():
                    if 0 in s_chunks and len(target_manifest.chunk_hashes) > 0:
                        first_hash = hashlib.sha3_256(s_chunks[0]).hexdigest()
                        if hmac.compare_digest(first_hash, target_manifest.chunk_hashes[0]):
                            chunks = s_chunks
                            break

        if len(chunks) < target_manifest.chunk_count:
            return False
        return all(idx in chunks for idx in range(target_manifest.chunk_count))

    def assemble(self, manifest: Optional[MediaManifest] = None, session_id: Optional[int] = None) -> bytes:
        """Reassemble full media payload from reconstructed chunks belonging strictly to this session."""
        target_manifest = manifest if manifest is not None else self.latest_manifest
        if target_manifest is None:
            raise ValueError("Cannot assemble media: no manifest provided and none received over wire")

        target_session = session_id
        if target_session is None:
            derived = self.derive_session_id(target_manifest)
            if derived in self.reconstructed_chunks_by_session:
                target_session = derived
            else:
                for sess, s_chunks in self.reconstructed_chunks_by_session.items():
                    if 0 in s_chunks and len(target_manifest.chunk_hashes) > 0:
                        first_hash = hashlib.sha3_256(s_chunks[0]).hexdigest()
                        if hmac.compare_digest(first_hash, target_manifest.chunk_hashes[0]):
                            target_session = sess
                            break
                if target_session is None:
                    target_session = derived

        if not self.is_complete(target_manifest, session_id=target_session):
            chunks = self.reconstructed_chunks_by_session.get(target_session, {})
            missing = set(range(target_manifest.chunk_count)) - set(chunks.keys())
            raise ValueError(f"Cannot assemble media for session {target_session}: missing chunks {sorted(missing)}")

        session_chunks = self.reconstructed_chunks_by_session[target_session]
        assembled = bytearray()
        for idx in range(target_manifest.chunk_count):
            chunk = session_chunks[idx]
            expected_hash = target_manifest.chunk_hashes[idx]
            if not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), expected_hash):
                raise ValueError(f"Integrity check failed on chunk {idx} in session {target_session}")
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
