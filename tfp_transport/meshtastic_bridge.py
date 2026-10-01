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
import typing
from dataclasses import dataclass

from tfp_core_v4.fountain import FountainDecoder, FountainDroplet

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


FLAG_DATA = 0x00
FLAG_MANIFEST = 0x01


@dataclass
class _SessionState:
    orig_len: int
    k: int
    symbol_size: int
    droplets: dict[int, FountainDroplet]
    reconstructed: bytes | None
    decoder: FountainDecoder


class MeshtasticBroadcaster:
    """
    Broadcasts files as rateless fountain packets over Meshtastic LoRa channels.
    Interleaves periodic manifests for late-joining receivers and respects airtime pacing.
    """

    def __init__(
        self,
        write_fn: typing.Callable[[bytes], typing.Awaitable[None]],
        symbol_size: int = 192,
        pacer: AirtimePacer | None = None,
    ):
        self.write_fn = write_fn
        self.symbol_size = symbol_size
        self.pacer = pacer

    async def broadcast_bytes(
        self,
        data: bytes,
        session_id: int = 0,
        redundancy: float = 0.30,
        channel_index: int = 1,
        hop_limit: int = 0,
        interleave_interval: int = 10,
    ) -> int:
        from tfp_core_v4.fountain import FountainEncoder

        encoder = FountainEncoder(symbol_size=self.symbol_size)
        droplets, k, orig_len = encoder.encode(data, redundancy=redundancy)

        manifest_payload = struct.pack("!IIH", orig_len, k, self.symbol_size)
        manifest_frame = MeshtasticFrameCodec.encode(
            session_id=session_id,
            seed=0,
            degree=0,
            data=manifest_payload,
            flags=FLAG_MANIFEST,
            channel_index=channel_index,
            hop_limit=hop_limit,
        )

        # Transmit initial manifest
        await self.write_fn(manifest_frame)
        if self.pacer:
            await self.pacer.pace_packet(len(manifest_frame))

        sent_count = 1
        for i, d in enumerate(droplets):
            # Interleave manifest periodically for late-joining receivers
            if i > 0 and (i % interleave_interval == 0):
                await self.write_fn(manifest_frame)
                if self.pacer:
                    await self.pacer.pace_packet(len(manifest_frame))
                sent_count += 1

            frame = MeshtasticFrameCodec.encode(
                session_id=session_id,
                seed=d.seed,
                degree=d.degree,
                data=d.payload,
                flags=FLAG_DATA,
                channel_index=channel_index,
                hop_limit=hop_limit,
            )
            await self.write_fn(frame)
            if self.pacer:
                await self.pacer.pace_packet(len(frame))
            sent_count += 1

        return sent_count


class MeshtasticListener:
    """
    Receives and reconstructs rateless fountain packets over Meshtastic frames.
    Buffers packets until rank K is satisfied, then solves with Gaussian elimination.
    """

    def __init__(self):
        self._sessions: dict[int, _SessionState] = {}

    def ingest_frame(self, frame: bytes) -> bool:
        import random
        from tfp_core_v4.fountain import (
            FountainDecoder,
            FountainDroplet,
            _sample_soliton_degree,
        )

        packet = MeshtasticFrameCodec.decode(frame)
        session_id = packet.session_id

        if packet.flags & FLAG_MANIFEST:
            if len(packet.data) < 10:
                return False
            orig_len, k, symbol_size = struct.unpack("!IIH", packet.data[:10])
            if session_id not in self._sessions:
                self._sessions[session_id] = _SessionState(
                    orig_len=orig_len,
                    k=k,
                    symbol_size=symbol_size,
                    droplets={},
                    reconstructed=None,
                    decoder=FountainDecoder(symbol_size=symbol_size, pre_validate=False),
                )
            return True

        # Data droplet
        if session_id not in self._sessions:
            return False

        state = self._sessions[session_id]
        if state.reconstructed is not None:
            return True

        seed = packet.seed
        k = state.k
        if seed < k:
            indices = [seed]
            degree = 1
        else:
            rng = random.Random(seed)
            degree = _sample_soliton_degree(k, rng)
            indices = sorted(rng.sample(range(k), degree))

        droplet = FountainDroplet(
            seed=seed,
            degree=degree,
            indices=indices,
            payload=packet.data,
        )
        state.droplets[seed] = droplet

        if len(state.droplets) >= k:
            try:
                recovered = state.decoder.decode(
                    list(state.droplets.values()),
                    k=k,
                    orig_len=state.orig_len,
                )
                state.reconstructed = recovered
                return True
            except (ValueError, RuntimeError):
                pass
        return False

    def is_complete(self, session_id: int) -> bool:
        state = self._sessions.get(session_id)
        return bool(state and state.reconstructed is not None)

    def assemble(self, session_id: int) -> bytes:
        state = self._sessions.get(session_id)
        if not state or state.reconstructed is None:
            raise RuntimeError(f"Session {session_id} is incomplete")
        return state.reconstructed


async def open_meshtastic_stream(endpoint: str, baud: int = 115200):
    """
    Open asynchronous stream to Meshtastic device over serial (COM3 / /dev/ttyUSB0)
    or TCP (e.g. 192.168.1.50:4403).
    """
    if ":" in endpoint and not endpoint.upper().startswith("COM"):
        host, port_str = endpoint.split(":", 1)
        return await asyncio.open_connection(host, int(port_str))

    try:
        import serial_asyncio

        return await serial_asyncio.open_serial_connection(url=endpoint, baudrate=baud)
    except ImportError:
        raise RuntimeError(
            "pyserial-asyncio is required for physical serial ports: pip install pyserial-asyncio"
        )


async def run_lora_broadcast(
    data: bytes,
    port: str = "COM3",
    baud: int = 115200,
    redundancy: float = 0.30,
    duty_cycle: float = 0.01,
    symbol_size: int = 192,
    session_id: int = 101,
    channel_index: int = 1,
    hop_limit: int = 0,
) -> int:
    """Broadcast raw bytes over Meshtastic LoRa frames with airtime duty-cycle pacing."""
    reader, writer = await open_meshtastic_stream(port, baud=baud)

    async def write_fn(frame: bytes):
        writer.write(frame)
        await writer.drain()

    pacer = AirtimePacer(duty_cycle_fraction=duty_cycle)
    broadcaster = MeshtasticBroadcaster(
        write_fn=write_fn,
        symbol_size=symbol_size,
        pacer=pacer,
    )
    try:
        return await broadcaster.broadcast_bytes(
            data=data,
            session_id=session_id,
            redundancy=redundancy,
            channel_index=channel_index,
            hop_limit=hop_limit,
        )
    finally:
        writer.close()
        await writer.wait_closed()


async def run_lora_listen(
    out_path: str,
    port: str = "COM3",
    baud: int = 115200,
    session_id: int = 101,
    timeout: float = 60.0,
) -> bytes:
    """Listen on Meshtastic frames and reconstruct payload into out_path."""
    from pathlib import Path

    reader, writer = await open_meshtastic_stream(port, baud=baud)
    listener = MeshtasticListener()
    try:
        start_time = time.monotonic()
        buffer = bytearray()
        while time.monotonic() - start_time < timeout:
            chunk = await asyncio.wait_for(
                reader.read(512),
                timeout=max(0.1, timeout - (time.monotonic() - start_time)),
            )
            if not chunk:
                await asyncio.sleep(0.05)
                continue
            buffer.extend(chunk)
            while SLIP_END in buffer:
                idx = buffer.index(SLIP_END)
                next_idx = buffer.find(SLIP_END, idx + 1)
                if next_idx == -1:
                    break
                frame = bytes(buffer[idx : next_idx + 1])
                del buffer[: next_idx + 1]
                listener.ingest_frame(frame)
                if listener.is_complete(session_id):
                    recovered = listener.assemble(session_id)
                    Path(out_path).write_bytes(recovered)
                    return recovered
        raise TimeoutError(f"Timed out waiting for session {session_id} reconstruction.")
    finally:
        writer.close()
        await writer.wait_closed()



