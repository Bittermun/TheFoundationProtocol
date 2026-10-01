# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Meshtastic LoRa Bridge & Wire Framing for The Foundation Protocol (TFP v4.0).

Encapsulates TFP FountainDroplets into standard Meshtastic Data packets via
asynchronous SLIP framing (RFC 1055) with zero-hop/secondary channel isolation
and strict RF duty-cycle compliance.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# SLIP (Serial Line Internet Protocol) Protocol Constants (RFC 1055)
SLIP_END = 0xC0
SLIP_ESC = 0xDB
SLIP_ESC_END = 0xDC
SLIP_ESC_ESC = 0xDD

# Header wire format:
# [SessionID: uint32 (4B)]
# [Seed: uint16 (2B)]
# [Degree: uint8 (1B)]
# [Flags: uint8 (1B)]
# [ChannelIndex: uint8 (1B)]
# [HopLimit: uint8 (1B)]
# Followed by raw droplet symbol bytes.
HEADER_STRUCT = struct.Struct("!IHBBBB")
HEADER_SIZE = HEADER_STRUCT.size  # 10 bytes


@dataclass(frozen=True)
class MeshtasticPacket:
    """Decoded Meshtastic TFP packet."""

    session_id: int
    seed: int
    degree: int
    flags: int
    channel_index: int
    hop_limit: int
    data: bytes


class MeshtasticFrameCodec:
    """SLIP and binary header codec for Meshtastic LoRa packets."""

    @staticmethod
    def slip_pack(payload: bytes) -> bytes:
        """
        Encapsulate binary payload with SLIP framing (RFC 1055).
        Escapes 0xC0 -> 0xDB 0xDC, 0xDB -> 0xDB 0xDD.
        """
        out = bytearray([SLIP_END])
        for b in payload:
            if b == SLIP_END:
                out.extend((SLIP_ESC, SLIP_ESC_END))
            elif b == SLIP_ESC:
                out.extend((SLIP_ESC, SLIP_ESC_ESC))
            else:
                out.append(b)
        out.append(SLIP_END)
        return bytes(out)

    @staticmethod
    def slip_unpack(raw: bytes) -> bytes:
        """
        Unpack SLIP-framed packet, stripping delimiters and unescaping bytes.
        """
        # Strip leading and trailing SLIP_END delimiters
        start = 0
        end = len(raw)
        while start < end and raw[start] == SLIP_END:
            start += 1
        while end > start and raw[end - 1] == SLIP_END:
            end -= 1

        body = raw[start:end]
        out = bytearray()
        i = 0
        n = len(body)
        while i < n:
            b = body[i]
            if b == SLIP_ESC:
                i += 1
                if i >= n:
                    raise ValueError("Dangling SLIP escape character")
                esc_b = body[i]
                if esc_b == SLIP_ESC_END:
                    out.append(SLIP_END)
                elif esc_b == SLIP_ESC_ESC:
                    out.append(SLIP_ESC)
                else:
                    raise ValueError(f"Invalid SLIP escape sequence: 0xDB 0x{esc_b:02X}")
            elif b == SLIP_END:
                raise ValueError("Unexpected unescaped SLIP_END inside body")
            else:
                out.append(b)
            i += 1
        return bytes(out)

    @classmethod
    def encode(
        cls,
        session_id: int,
        seed: int,
        degree: int,
        data: bytes,
        flags: int = 0,
        channel_index: int = 1,
        hop_limit: int = 0,
    ) -> bytes:
        """
        Serialize packet metadata and data into a SLIP-framed wire frame.
        """
        header = HEADER_STRUCT.pack(
            session_id & 0xFFFFFFFF,
            seed & 0xFFFF,
            degree & 0xFF,
            flags & 0xFF,
            channel_index & 0xFF,
            hop_limit & 0xFF,
        )
        return cls.slip_pack(header + data)

    @classmethod
    def decode(cls, frame: bytes) -> MeshtasticPacket:
        """
        Decode a SLIP-framed wire frame into a MeshtasticPacket.
        """
        raw = cls.slip_unpack(frame)
        if len(raw) < HEADER_SIZE:
            raise ValueError(f"Frame too short: {len(raw)} bytes (expected at least {HEADER_SIZE})")

        session_id, seed, degree, flags, channel_index, hop_limit = HEADER_STRUCT.unpack_from(raw, 0)
        data = raw[HEADER_SIZE:]
        return MeshtasticPacket(
            session_id=session_id,
            seed=seed,
            degree=degree,
            flags=flags,
            channel_index=channel_index,
            hop_limit=hop_limit,
            data=data,
        )
