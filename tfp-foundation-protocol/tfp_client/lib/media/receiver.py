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
import hashlib
import heapq
import hmac
import json
import logging
import os
import shutil
import socket
import stat
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

# Ensure tfp_core_v4 is importable
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.fountain import FountainCodec, FountainDroplet

from .fountain_streamer import (
    MANIFEST_MAGIC,
    PACKET_MAGIC,
    PACKET_VERSION,
    AntiPollutionError,
    MediaDropletPacket,
    MediaStreamError,
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
        max_sessions: int = 32,
        max_droplets_per_chunk: int = 512,
        max_chunks_per_session: int = 128,
        session_ttl_seconds: float = 600.0,
        checkpoint_dir: Path | str | None = None,
    ):
        for name, limit in (
            ("max_sessions", max_sessions),
            ("max_droplets_per_chunk", max_droplets_per_chunk),
            ("max_chunks_per_session", max_chunks_per_session),
        ):
            if type(limit) is not int or limit <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.symbol_size = symbol_size
        self.secret_key = secret_key
        self.verify_tag = verify_tag
        self.max_sessions = max_sessions
        self.max_droplets_per_chunk = max_droplets_per_chunk
        self.max_chunks_per_session = max_chunks_per_session
        self.session_ttl_seconds = session_ttl_seconds
        self.codec = FountainCodec(symbol_size=symbol_size)
        self.checkpoint_dir = Path(checkpoint_dir).resolve() if checkpoint_dir else None

        # Droplet buffers: (session_id, chunk_index) -> {seed: FountainDroplet}
        self._droplet_buffers: Dict[Tuple[int, int], Dict[int, FountainDroplet]] = {}
        # Metadata storage: (session_id, chunk_index) -> (k, orig_len)
        self._chunk_meta: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # Reconstructed content: session_id -> {chunk_index: bytes}
        self.reconstructed_chunks_by_session: Dict[int, Dict[int, bytes]] = {}
        self.received_manifests: Dict[int, MediaManifest] = {}
        self.latest_manifest: Optional[MediaManifest] = None
        self._last_active_session: Optional[int] = None
        self._session_timestamps: Dict[int, float] = {}
        # Reception statistics
        self.stats = ReceiverStats()

        if self.checkpoint_dir:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self._load_checkpoints()

    def _save_chunk_checkpoint(self, session_id: int, chunk_idx: int, chunk_data: bytes) -> None:
        """Persist a verified completed chunk to bounded checkpoint storage."""
        if not self.checkpoint_dir:
            return
        sdir = self.checkpoint_dir / f"session_{session_id}"
        sdir.mkdir(parents=True, exist_ok=True)
        c_hash = hashlib.sha3_256(chunk_data).hexdigest()
        cfile = sdir / f"chunk_{chunk_idx}_{c_hash}.dat"
        tmp_file = sdir / f".tmp_{chunk_idx}_{uuid.uuid4().hex[:6]}.dat"
        try:
            tmp_file.write_bytes(chunk_data)
            os.replace(tmp_file, cfile)
        except Exception as exc:
            log.warning(f"Failed to write chunk checkpoint: {exc}")
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)

    def _save_manifest_checkpoint(self, session_id: int, manifest: MediaManifest) -> None:
        """Persist authentic session manifest to bounded checkpoint storage."""
        if not self.checkpoint_dir:
            return
        sdir = self.checkpoint_dir / f"session_{session_id}"
        sdir.mkdir(parents=True, exist_ok=True)
        mfile = sdir / "manifest.json"
        tmp_file = sdir / f".tmp_m_{uuid.uuid4().hex[:6]}.json"
        try:
            record = {"version": 1, "symbol_size": self.symbol_size, "verify_tag": self.verify_tag,
                      "session_id": session_id, "manifest": manifest.to_dict()}
            record["auth_tag"] = hmac.new(self.secret_key, self._checkpoint_bytes(record), hashlib.sha3_256).hexdigest()
            tmp_file.write_bytes(self._checkpoint_bytes(record))
            os.replace(tmp_file, mfile)
        except Exception as exc:
            log.warning(f"Failed to write manifest checkpoint: {exc}")
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)

    @staticmethod
    def _checkpoint_bytes(record) -> bytes:
        return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _plain_checkpoint_path(path: Path) -> bool:
        info = path.lstat()
        return not (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400)

    def _remove_checkpoint_session(self, path: Path) -> None:
        """Remove only a plain session directory directly inside checkpoint storage."""
        try:
            if (path.parent == self.checkpoint_dir and path.name.startswith("session_")
                    and self._plain_checkpoint_path(path) and path.is_dir()):
                shutil.rmtree(path)
        except OSError as exc:
            log.warning("Could not remove checkpoint %s: %s", path, exc)

    def _load_checkpoints(self) -> None:
        """Restore only bounded, context-bound sessions. Unknown formats are ignored.

        A missing/corrupt/legacy manifest is not permission to restore speculative
        files. Bounds and file lengths are checked before chunk bytes are read.
        """
        if not self.checkpoint_dir:
            return
        now = time.time()
        retained = []
        for sdir in self.checkpoint_dir.iterdir():
            try:
                if (not sdir.name.startswith("session_") or not self._plain_checkpoint_path(sdir)
                        or not sdir.is_dir()):
                    continue
                session_id = int(sdir.name.removeprefix("session_"))
                timestamp = sdir.stat().st_mtime
                if not 0 <= session_id <= 0xFFFFFFFF or sdir.name != f"session_{session_id}":
                    continue
                m_file = sdir / "manifest.json"
                if not self._plain_checkpoint_path(m_file) or m_file.stat().st_size > 1_048_576:
                    continue
                with m_file.open("rb") as source:
                    raw = source.read(1_048_577)
                if len(raw) > 1_048_576:
                    continue
                record = json.loads(raw)
                tag = record.pop("auth_tag")
                expected_tag = hmac.new(self.secret_key, self._checkpoint_bytes(record), hashlib.sha3_256).hexdigest()
                if not hmac.compare_digest(tag, expected_tag):
                    continue
                if (record["version"] != 1 or record["symbol_size"] != self.symbol_size
                        or record["verify_tag"] != self.verify_tag):
                    continue
                manifest = MediaManifest.from_dict(record["manifest"])
                # Older context-bound records implicitly used the derived ID.
                saved_session = record.get("session_id", self.derive_session_id(manifest))
                if type(saved_session) is not int or saved_session != session_id:
                    continue
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                log.warning("Ignoring checkpoint without valid context in %s: %s", sdir, exc)
                continue

            # Validate ownership before deleting anything. Unknown, legacy and
            # differently authenticated checkpoints are deliberately preserved.
            if now - timestamp > self.session_ttl_seconds:
                self._remove_checkpoint_session(sdir)
                continue
            if not self._manifest_fits(manifest):
                continue
            candidate = (timestamp, session_id, sdir, manifest)
            if len(retained) < self.max_sessions:
                heapq.heappush(retained, candidate)
            else:
                discarded = heapq.heappushpop(retained, candidate)
                self._remove_checkpoint_session(discarded[2])

        # Restore oldest first so the default view ends on the newest session.
        for timestamp, session_id, sdir, manifest in sorted(retained):
            session_chunks: dict[int, bytes] = {}
            for cfile in sdir.glob("chunk_*_*.dat"):
                if len(session_chunks) >= self.max_chunks_per_session:
                    break
                try:
                    parts = cfile.stem.split("_")
                    if len(parts) != 3 or not self._plain_checkpoint_path(cfile):
                        continue
                    c_idx = int(parts[1])
                    if not 0 <= c_idx < manifest.chunk_count or c_idx in session_chunks:
                        continue
                    expected_hash = manifest.chunk_hashes[c_idx]
                    expected_size = manifest.chunk_sizes[c_idx]
                    if parts[2] != expected_hash or cfile.stat().st_size != expected_size:
                        continue
                    with cfile.open("rb") as source:
                        cdata = source.read(expected_size + 1)
                    if len(cdata) != expected_size or not hmac.compare_digest(hashlib.sha3_256(cdata).hexdigest(), expected_hash):
                        cfile.unlink(missing_ok=True)
                        continue
                    session_chunks[c_idx] = cdata
                except (OSError, ValueError, TypeError):
                    continue
            self.received_manifests[session_id] = manifest
            self.reconstructed_chunks_by_session[session_id] = session_chunks
            self._session_timestamps[session_id] = timestamp
            self._last_active_session = session_id
            self.latest_manifest = manifest
            self.stats.chunks_reconstructed += len(session_chunks)

    def _manifest_fits(self, manifest: MediaManifest) -> bool:
        try:
            MediaManifest.from_dict(manifest.to_dict())
            return (manifest.chunk_count <= self.max_chunks_per_session and all(
                size <= self.max_droplets_per_chunk * self.symbol_size for size in manifest.chunk_sizes
            ))
        except (ValueError, TypeError, KeyError):
            return False

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
        # Existing in-process stream callers also supply an explicit uint32 ID.
        if type(manifest.manifest_id) is int and 0 <= manifest.manifest_id <= 0xFFFFFFFF:
            return manifest.manifest_id
        if not isinstance(manifest.manifest_id, str):
            raise TypeError("Manifest ID must be a string or uint32 session ID")
        try:
            return int.from_bytes(bytes.fromhex(manifest.manifest_id)[:4], "big")
        except Exception:
            return int.from_bytes(hashlib.sha256(manifest.manifest_id.encode()).digest()[:4], "big")

    def _session_for_manifest(self, manifest: MediaManifest, session_id: Optional[int]) -> int:
        if session_id is not None:
            return session_id
        if self._last_active_session is not None and self.received_manifests.get(self._last_active_session) is manifest:
            return self._last_active_session
        for registered_id, registered_manifest in self.received_manifests.items():
            if registered_manifest is manifest:
                return registered_id
        return self.derive_session_id(manifest)

    def _evict_stale_or_excess_sessions(self, incoming_session: int) -> None:
        """Evicts sessions exceeding max_sessions (LRU) or older than session_ttl_seconds."""
        now = time.time()

        # 1. Clean up expired sessions (except incoming)
        expired = [
            sid for sid, ts in list(self._session_timestamps.items())
            if sid != incoming_session and (now - ts) > self.session_ttl_seconds
        ]
        for sid in expired:
            self.reset(sid)

        # 2. If at capacity when a new session arrives, evict LRU
        while True:
            known_sessions = (
                set(self._session_timestamps.keys())
                | set(self.reconstructed_chunks_by_session.keys())
                | set(self.received_manifests.keys())
            )
            if incoming_session in known_sessions or len(known_sessions) < self.max_sessions:
                break

            candidates = [
                (self._session_timestamps.get(sid, 0.0), sid)
                for sid in known_sessions
                if sid != incoming_session
            ]
            if not candidates:
                break
            candidates.sort()
            oldest_sid = candidates[0][1]
            self.reset(oldest_sid)

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
            self.received_manifests.clear()
            self.latest_manifest = None
            self._session_timestamps.clear()
            self._last_active_session = None
        else:
            to_delete_buf = [k for k in self._droplet_buffers if k[0] == session_id]
            for k in to_delete_buf:
                self._droplet_buffers.pop(k, None)
            to_delete_meta = [k for k in self._chunk_meta if k[0] == session_id]
            for k in to_delete_meta:
                self._chunk_meta.pop(k, None)
            self.reconstructed_chunks_by_session.pop(session_id, None)
            removed_manifest = self.received_manifests.pop(session_id, None)
            self._session_timestamps.pop(session_id, None)
            if removed_manifest is not None and self.latest_manifest is removed_manifest:
                self.latest_manifest = next(iter(self.received_manifests.values()), None)
            if self._last_active_session == session_id:
                self._last_active_session = next(iter(self._session_timestamps), None)

        if self.checkpoint_dir and self.checkpoint_dir.exists():
            if session_id is None:
                for sdir in self.checkpoint_dir.glob("session_*"):
                    self._remove_checkpoint_session(sdir)
            else:
                sdir = self.checkpoint_dir / f"session_{session_id}"
                if sdir.exists():
                    self._remove_checkpoint_session(sdir)

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

        # Reject incompatible dimensions before any session eviction or allocation.
        # The droplet cap also bounds the decoder's source-symbol matrix width.
        if (
            any(type(value) is not int for value in (
                session_id, chunk_idx, pkt.k, pkt.orig_len, pkt.symbol_size, pkt.seed,
            ))
            or not 0 <= session_id <= 0xFFFFFFFF
            or not 0 <= chunk_idx <= 0xFFFFFFFF
            or not 0 <= pkt.seed <= 0xFFFFFFFF
            or not 0 < pkt.k <= min(self.max_droplets_per_chunk, 0xFFFF)
            or not 0 < pkt.orig_len <= pkt.k * self.symbol_size
            or pkt.symbol_size != self.symbol_size
            or len(pkt.payload) != self.symbol_size
        ):
            return None

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

        # A manifest cannot relax the receiver's local resource limits.
        target_m = self.received_manifests.get(session_id)
        if target_m is not None and (
            chunk_idx >= target_m.chunk_count or pkt.orig_len != target_m.chunk_sizes[chunk_idx]
        ):
            return None

        buf_key = (session_id, chunk_idx)
        if buf_key in self._chunk_meta and self._chunk_meta[buf_key] != (pkt.k, pkt.orig_len):
            return None
        session_chunks = self.reconstructed_chunks_by_session.get(session_id, {})
        active_chunk_indices = set(session_chunks) | {
            c_idx for s_id, c_idx in self._chunk_meta if s_id == session_id
        }
        if chunk_idx not in active_chunk_indices and len(active_chunk_indices) >= self.max_chunks_per_session:
            return None

        self._evict_stale_or_excess_sessions(session_id)
        self._session_timestamps[session_id] = time.time()
        self._last_active_session = session_id
        session_chunks = self.reconstructed_chunks_by_session.setdefault(session_id, {})

        # Already completed for this chunk in this session?
        if chunk_idx in session_chunks:
            # If manifest is known, ensure existing chunk is actually valid
            if target_m is not None and chunk_idx < len(target_m.chunk_hashes):
                expected_hash = target_m.chunk_hashes[chunk_idx]
                if not hmac.compare_digest(hashlib.sha3_256(session_chunks[chunk_idx]).hexdigest(), expected_hash):
                    # Existing chunk was corrupted (e.g. decoded before manifest arrived) - purge it
                    session_chunks.pop(chunk_idx, None)
                else:
                    self.stats.packets_duplicate += 1
                    return None
            else:
                self.stats.packets_duplicate += 1
                return None

        if buf_key not in self._droplet_buffers:
            self._droplet_buffers[buf_key] = {}
            self._chunk_meta[buf_key] = (pkt.k, pkt.orig_len)

        buf = self._droplet_buffers[buf_key]
        if pkt.seed in buf:
            self.stats.packets_duplicate += 1
            return None

        if len(buf) >= self.max_droplets_per_chunk:
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
                        # Remove the offending droplet that caused corrupted decode
                        buf.pop(pkt.seed, None)
                        return None

                session_chunks[chunk_idx] = reconstructed
                del self._droplet_buffers[buf_key]
                self.stats.chunks_reconstructed += 1
                if self.checkpoint_dir:
                    self._save_chunk_checkpoint(session_id, chunk_idx, reconstructed)
                return (chunk_idx, reconstructed)
            except ValueError:
                # Rank deficient (repair symbols had overlapping linear dependencies)
                # Keep collecting additional droplets
                pass

        return None

    def ingest_manifest(self, manifest: MediaManifest, session_id: Optional[int] = None) -> Optional[int]:
        """
        Directly register an authentic MediaManifest for a session.
        Prunes any out-of-bounds or corrupted speculative chunks and buffers.
        Returns the explicit or derived session_id, or None for invalid IDs or oversized manifests.
        """
        if not self._manifest_fits(manifest):
            return None

        sess_id = self.derive_session_id(manifest) if session_id is None else session_id
        if type(sess_id) is not int or not 0 <= sess_id <= 0xFFFFFFFF:
            return None
        self._evict_stale_or_excess_sessions(sess_id)
        self._session_timestamps[sess_id] = time.time()
        self.received_manifests[sess_id] = manifest
        self.latest_manifest = manifest
        self._last_active_session = sess_id
        if self.checkpoint_dir:
            self._save_manifest_checkpoint(sess_id, manifest)

        # Prune metadata as well as buffers: completed speculative chunks
        # no longer have a droplet buffer but still have metadata.
        stale_keys = [
            key for key, (_, size) in self._chunk_meta.items()
            if key[0] == sess_id and (
                key[1] < 0 or key[1] >= manifest.chunk_count
                or size != manifest.chunk_sizes[key[1]]
            )
        ]
        for k in stale_keys:
            self._droplet_buffers.pop(k, None)
            self._chunk_meta.pop(k, None)

        session_reconstructed = self.reconstructed_chunks_by_session.get(sess_id, {})
        stale_chunks = [
            c_idx for c_idx, chunk in session_reconstructed.items()
            if c_idx < 0 or c_idx >= manifest.chunk_count
            or len(chunk) != manifest.chunk_sizes[c_idx]
            or not hmac.compare_digest(hashlib.sha3_256(chunk).hexdigest(), manifest.chunk_hashes[c_idx])
        ]
        for c_idx in stale_chunks:
            session_reconstructed.pop(c_idx, None)
            self._chunk_meta.pop((sess_id, c_idx), None)

        return sess_id

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
                res = self.ingest_manifest(manifest)
                if res is None:
                    return None
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

        target_session = self._session_for_manifest(target_manifest, session_id)
        if not self._manifest_fits(target_manifest):
            return False
        if target_session not in self.received_manifests:
            if self.ingest_manifest(target_manifest, session_id=target_session) is None:
                return False

        chunks = self.reconstructed_chunks_by_session.get(target_session, {})
        if len(chunks) < target_manifest.chunk_count:
            return False

        for idx in range(target_manifest.chunk_count):
            if idx not in chunks:
                return False
            expected_hash = target_manifest.chunk_hashes[idx]
            actual_hash = hashlib.sha3_256(chunks[idx]).hexdigest()
            if not hmac.compare_digest(actual_hash, expected_hash):
                # Corrupted speculative chunk! Purge it so the receiver can re-decode from droplets
                chunks.pop(idx, None)
                self._chunk_meta.pop((target_session, idx), None)
                return False

        return True

    def assemble(self, manifest: Optional[MediaManifest] = None, session_id: Optional[int] = None) -> bytes:
        """Reassemble full media payload from reconstructed chunks belonging strictly to this session."""
        target_manifest = manifest if manifest is not None else self.latest_manifest
        if target_manifest is None:
            raise ValueError("Cannot assemble media: no manifest provided and none received over wire")

        target_session = self._session_for_manifest(target_manifest, session_id)

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
