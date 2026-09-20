# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Rateless Fountain Media Broadcaster for TFP v4.0.

Provides packet-level framing with anti-pollution authentication and
rateless droplet generation for lossy wireless and UDP channels.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import random
import socket
import struct
import sys
from typing import AsyncGenerator, Dict, Generator, Iterable, List, Optional, Tuple, Union

# Ensure tfp_core_v4 is importable
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDroplet,
    _sample_soliton_degree,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)
from .stream_packager import MediaManifest


PACKET_MAGIC = b"FD"
MANIFEST_MAGIC = b"FM"
PACKET_VERSION = 1
HEADER_FORMAT = ">2sBBIIHIHI16s"  # 40 bytes total
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MANIFEST_HEADER_FORMAT = ">2sBBI16s"  # 24 bytes total
MANIFEST_HEADER_SIZE = struct.calcsize(MANIFEST_HEADER_FORMAT)


def serialize_manifest_packet(manifest: MediaManifest, secret_key: bytes = b"") -> bytes:
    """Serialize a MediaManifest into an authenticated over-the-wire binary datagram."""
    raw_json = manifest.to_json().encode("utf-8")
    hdr_pre = struct.pack(">2sBBI", MANIFEST_MAGIC, PACKET_VERSION, 0, len(raw_json))
    tag = hmac.new(secret_key, hdr_pre + raw_json, hashlib.sha3_256).digest()[:16]
    full_hdr = struct.pack(MANIFEST_HEADER_FORMAT, MANIFEST_MAGIC, PACKET_VERSION, 0, len(raw_json), tag)
    return full_hdr + raw_json


def deserialize_manifest_packet(
    data: bytes,
    secret_key: bytes = b"",
    verify_tag: bool = True,
) -> MediaManifest:
    """Deserialize and cryptographically authenticate a wire MediaManifest datagram."""
    if len(data) < MANIFEST_HEADER_SIZE:
        raise ValueError(f"Manifest packet too short: {len(data)} < {MANIFEST_HEADER_SIZE}")
    magic, version, flags, length, tag = struct.unpack_from(MANIFEST_HEADER_FORMAT, data, 0)
    if magic != MANIFEST_MAGIC:
        raise ValueError(f"Invalid manifest magic: {magic}")
    raw_json = data[MANIFEST_HEADER_SIZE : MANIFEST_HEADER_SIZE + length]
    if len(raw_json) != length:
        raise ValueError(f"Truncated manifest payload: expected {length}, got {len(raw_json)}")
    if verify_tag and secret_key:
        hdr_pre = struct.pack(">2sBBI", magic, version, flags, length)
        expected_tag = hmac.new(secret_key, hdr_pre + raw_json, hashlib.sha3_256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            raise AntiPollutionError("Manifest authentication tag verification failed")
    d = json.loads(raw_json.decode("utf-8"))
    return MediaManifest.from_dict(d)


class MediaStreamError(Exception):
    """Base exception for media streaming errors."""
    pass


class AntiPollutionError(MediaStreamError):
    """Raised when droplet packet authentication fails (Byzantine attack detected)."""
    pass


@dataclass(frozen=True)
class MediaDropletPacket:
    """
    Framed over-the-wire media droplet packet with anti-pollution authentication.
    """

    session_id: int       # uint32: session/stream identifier
    chunk_index: int      # uint32: chunk index in media manifest
    k: int                # uint16: total source symbols for this chunk
    orig_len: int         # uint32: exact unpadded byte length of the chunk
    symbol_size: int      # uint16: symbol byte length
    seed: int             # uint32: fountain seed (0..k-1 systematic, >=k repair)
    payload: bytes        # raw symbol payload
    auth_tag: bytes = b"" # 16-byte HMAC-SHA3-256 anti-pollution tag

    def to_bytes(self, secret_key: bytes = b"") -> bytes:
        """
        Serialize to binary network format.
        Computes 16-byte HMAC-SHA3-256 over header and payload.
        """
        # Pre-pack header with placeholder tag
        header_pre = struct.pack(
            ">2sBBIIHIHI",
            PACKET_MAGIC,
            PACKET_VERSION,
            0,  # flags
            self.session_id,
            self.chunk_index,
            self.k,
            self.orig_len,
            self.symbol_size,
            self.seed,
        )

        # Compute truncated 16-byte HMAC
        tag = hmac.new(
            secret_key,
            header_pre + self.payload,
            hashlib.sha3_256,
        ).digest()[:16]

        # Pack full 40-byte header
        full_header = struct.pack(
            HEADER_FORMAT,
            PACKET_MAGIC,
            PACKET_VERSION,
            0,  # flags
            self.session_id,
            self.chunk_index,
            self.k,
            self.orig_len,
            self.symbol_size,
            self.seed,
            tag,
        )

        return full_header + self.payload

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        secret_key: Optional[bytes] = None,
        verify_tag: bool = True,
    ) -> MediaDropletPacket:
        """
        Deserialize from binary network format and verify anti-pollution tag in O(1).
        """
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} bytes < {HEADER_SIZE} header")

        (
            magic,
            version,
            flags,
            session_id,
            chunk_index,
            k,
            orig_len,
            symbol_size,
            seed,
            tag,
        ) = struct.unpack_from(HEADER_FORMAT, data, 0)

        if magic != PACKET_MAGIC:
            raise ValueError(f"Invalid packet magic: {magic!r}")
        if version != PACKET_VERSION:
            raise ValueError(f"Unsupported packet version: {version}")

        payload = data[HEADER_SIZE:]
        if len(payload) != symbol_size:
            raise ValueError(f"Payload size mismatch: expected {symbol_size}, got {len(payload)}")

        if verify_tag and secret_key is not None:
            header_pre = struct.pack(
                ">2sBBIIHIHI",
                magic,
                version,
                flags,
                session_id,
                chunk_index,
                k,
                orig_len,
                symbol_size,
                seed,
            )
            expected_tag = hmac.new(
                secret_key,
                header_pre + payload,
                hashlib.sha3_256,
            ).digest()[:16]

            if not hmac.compare_digest(tag, expected_tag):
                raise AntiPollutionError(
                    f"Byzantine packet rejected: HMAC mismatch for session={session_id} chunk={chunk_index} seed={seed}"
                )

        return cls(
            session_id=session_id,
            chunk_index=chunk_index,
            k=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            seed=seed,
            payload=payload,
            auth_tag=tag,
        )

    def to_droplet(self) -> FountainDroplet:
        """Reconstruct FountainDroplet representation for Gaussian elimination decoder."""
        k = self.k
        seed = self.seed
        if seed < k:
            degree = 1
            indices = [seed]
        else:
            rng = random.Random(seed)
            degree = _sample_soliton_degree(k, rng)
            indices = sorted(rng.sample(range(k), degree))

        return FountainDroplet(
            seed=seed,
            degree=degree,
            indices=indices,
            payload=self.payload,
        )


class FountainStreamer:
    """
    Produces authenticated rateless fountain droplet streams for media chunks.
    """

    def __init__(
        self,
        symbol_size: int = 512,
        secret_key: bytes = b"tfp-default-streaming-salt",
    ):
        self.symbol_size = symbol_size
        self.secret_key = secret_key
        self.codec = FountainCodec(symbol_size=symbol_size)

    def generate_packet(
        self,
        chunk_data: bytes,
        chunk_index: int,
        session_id: int,
        seed: int,
    ) -> MediaDropletPacket:
        """
        Generate a single deterministic droplet packet for any seed >= 0.
        Systematic symbols for seed < k, rateless repair symbols for seed >= k.
        """
        orig_len = len(chunk_data)
        k = math.ceil(orig_len / self.symbol_size)
        padded = chunk_data.ljust(k * self.symbol_size, b"\x00")

        if seed < k:
            payload = padded[seed * self.symbol_size : (seed + 1) * self.symbol_size]
        else:
            rng = random.Random(seed)
            degree = _sample_soliton_degree(k, rng)
            indices = sorted(rng.sample(range(k), degree))

            acc = 0
            for idx in indices:
                sym = padded[idx * self.symbol_size : (idx + 1) * self.symbol_size]
                acc ^= int.from_bytes(sym, "big")
            payload = acc.to_bytes(self.symbol_size, "big")

        return MediaDropletPacket(
            session_id=session_id,
            chunk_index=chunk_index,
            k=k,
            orig_len=orig_len,
            symbol_size=self.symbol_size,
            seed=seed,
            payload=payload,
        )

    def stream_chunk_rateless(
        self,
        chunk_data: bytes,
        chunk_index: int,
        session_id: int,
        start_seed: int = 0,
        max_droplets: Optional[int] = None,
    ) -> Generator[MediaDropletPacket, None, None]:
        """
        Rateless generator yielding consecutive droplet packets for a media chunk.
        """
        seed = start_seed
        count = 0
        while max_droplets is None or count < max_droplets:
            yield self.generate_packet(chunk_data, chunk_index, session_id, seed)
            seed += 1
            count += 1

    def package_chunk_packets(
        self,
        chunk_data: bytes,
        chunk_index: int,
        session_id: int,
        redundancy: float = 0.30,
    ) -> List[MediaDropletPacket]:
        """
        Encode a single media chunk into authenticated wire packets with repair redundancy.
        """
        droplets, k, orig_len = self.codec.encode(chunk_data, redundancy=redundancy)
        packets = []
        for d in droplets:
            pkt = MediaDropletPacket(
                session_id=session_id,
                chunk_index=chunk_index,
                k=k,
                orig_len=orig_len,
                symbol_size=self.symbol_size,
                seed=d.seed,
                payload=d.payload,
            )
            packets.append(pkt)
        return packets

    def stream_manifest(
        self,
        manifest: MediaManifest,
        chunks: List[bytes],
        redundancy: float = 0.30,
        session_id: Optional[int] = None,
    ) -> Generator[MediaDropletPacket, None, None]:
        """
        Generator producing continuous rateless packets for all chunks in a media manifest.
        """
        if session_id is None:
            # Derive deterministic 32-bit session ID from manifest ID
            session_id = int.from_bytes(bytes.fromhex(manifest.manifest_id)[:4], "big")

        for idx, chunk in enumerate(chunks):
            packets = self.package_chunk_packets(
                chunk_data=chunk,
                chunk_index=idx,
                session_id=session_id,
                redundancy=redundancy,
            )
            for pkt in packets:
                yield pkt

    def stream_manifest_wire_packets(
        self,
        manifest: MediaManifest,
        chunks: List[bytes],
        redundancy: float = 0.30,
        session_id: Optional[int] = None,
        repeat_manifest: int = 3,
    ) -> Generator[bytes, None, None]:
        """
        Yields raw wire datagram bytes for both the manifest and fountain droplets.
        Transmits the manifest first (repeated `repeat_manifest` times for loss tolerance),
        followed by all fountain droplet packets.
        """
        manifest_bytes = serialize_manifest_packet(manifest, secret_key=self.secret_key)
        for _ in range(repeat_manifest):
            yield manifest_bytes
        for pkt in self.stream_manifest(manifest, chunks, redundancy=redundancy, session_id=session_id):
            yield pkt.to_bytes(self.secret_key)

    async def broadcast_udp(
        self,
        packets: Iterable[Union[MediaDropletPacket, bytes]],
        host: str = "127.0.0.1",
        port: int = 9876,
        packet_interval: float = 0.0,
    ):
        """
        Asynchronously send packets or raw datagram bytes over UDP socket.
        """
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            for pkt in packets:
                raw = pkt if isinstance(pkt, bytes) else pkt.to_bytes(self.secret_key)
                await loop.sock_sendto(sock, raw, (host, port))
                if packet_interval > 0:
                    await asyncio.sleep(packet_interval)
        finally:
            sock.close()
