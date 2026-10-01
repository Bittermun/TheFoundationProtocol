# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Meshtastic LoRa Bridge & Wire Framing for The Foundation Protocol (TFP v4.0).

Encapsulates TFP FountainDroplets into standard Meshtastic Data packets via
asynchronous SLIP framing (RFC 1055) with zero-hop/secondary channel isolation
and strict RF duty-cycle compliance.
"""

from __future__ import annotations

import asyncio
import math
import struct
import time
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


class AirtimePacer:
    """
    Calculates LoRa packet airtime and enforces regional duty-cycle pacing.
    Complies with FCC Part 15 and ETSI EN 300 220 requirements.
    """

    def __init__(
        self,
        duty_cycle_fraction: float = 0.01,
        sf: int = 7,
        bw_khz: float = 125.0,
        cr: int = 1,
        preamble_len: int = 8,
        has_crc: bool = True,
    ):
        self.duty_cycle_fraction = max(0.0, min(1.0, float(duty_cycle_fraction)))
        self.sf = sf
        self.bw_khz = bw_khz
        self.cr = cr
        self.preamble_len = preamble_len
        self.has_crc = has_crc
        self._last_tx_end_time = 0.0

    @staticmethod
    def compute_lora_airtime_ms(
        payload_len: int,
        sf: int = 7,
        bw_khz: float = 125.0,
        cr: int = 1,
        preamble_len: int = 8,
        has_crc: bool = True,
        implicit_header: bool = False,
    ) -> float:
        """
        Compute theoretical on-air duration in milliseconds for SX126x/SX127x transceivers.
        """
        bw_hz = bw_khz * 1000.0
        t_sym_s = (2.0**sf) / bw_hz

        # Low data rate optimization enabled if symbol duration >= 16.38 ms
        de = 1 if t_sym_s >= 0.01638 else 0

        # Preamble duration
        t_preamble_s = (preamble_len + 4.25) * t_sym_s

        # Payload symbol calculation
        crc_term = 16 if has_crc else 0
        ih_term = 20 if implicit_header else 0
        numerator = 8 * payload_len - 4 * sf + 28 + crc_term - ih_term
        denominator = 4 * (sf - 2 * de)

        if numerator < 0:
            sym_blocks = 0
        else:
            sym_blocks = math.ceil(numerator / denominator)

        n_payload = 8 + max(sym_blocks * (cr + 4), 0)
        t_packet_s = t_preamble_s + (n_payload * t_sym_s)
        return t_packet_s * 1000.0

    def calculate_required_delay(self, airtime_ms: float) -> float:
        """
        Calculate required silent cooldown in seconds to comply with duty-cycle fraction.
        """
        if self.duty_cycle_fraction >= 1.0 or self.duty_cycle_fraction <= 0.0:
            return 0.0
        airtime_s = airtime_ms / 1000.0
        # Required total slot: airtime_s / duty_cycle
        # Delay = total slot - airtime_s = airtime_s * (1 - D) / D
        return airtime_s * (1.0 - self.duty_cycle_fraction) / self.duty_cycle_fraction

    async def pace_packet(self, payload_len: int) -> float:
        """
        Calculate airtime for payload, ensure required cooldown, and record TX finish.
        Uses non-blocking asyncio.sleep().
        """
        airtime_ms = self.compute_lora_airtime_ms(
            payload_len=payload_len,
            sf=self.sf,
            bw_khz=self.bw_khz,
            cr=self.cr,
            preamble_len=self.preamble_len,
            has_crc=self.has_crc,
        )
        delay_s = self.calculate_required_delay(airtime_ms)
        if delay_s > 0.0:
            await asyncio.sleep(delay_s)
        self._last_tx_end_time = time.monotonic()
        return airtime_ms

