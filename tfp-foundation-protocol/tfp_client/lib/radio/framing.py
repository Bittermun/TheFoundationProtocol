# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Radio Framing & Ultra-Compact Packetizer for TFP v4.0.

Segments payloads into MTU-constrained (<240 bytes) radio frames equipped with
hardware-friendly CRC16 error detection for LoRa and AX.25 packet radio links.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Dict, List, Optional, Set, Tuple


RADIO_MAGIC = 0xF0
RADIO_HEADER_FORMAT = ">BBHHH"  # 8 bytes: magic (1B), msg_type (1B), session_id (2B), packet_seq (2B), total_packets (2B)
RADIO_HEADER_SIZE = struct.calcsize(RADIO_HEADER_FORMAT)
RADIO_TRAILER_SIZE = 2  # CRC16 (2B)
RADIO_OVERHEAD = RADIO_HEADER_SIZE + RADIO_TRAILER_SIZE  # 10 bytes


def crc16_ccitt(data: bytes) -> int:
    """Compute standard CRC16-CCITT checksum (poly 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class RadioPacket:
    """A single MTU-bounded physical radio frame."""

    msg_type: int        # 1B: 0x01 Manifest, 0x02 Shard, 0x03 Droplet, 0x04 Emergency
    session_id: int      # 2B: uint16 session identifier
    packet_seq: int      # 2B: uint16 0-indexed segment sequence number
    total_packets: int   # 2B: uint16 total segments in this transmission
    payload: bytes       # 1..MTU bytes

    def to_bytes(self) -> bytes:
        """Serialize frame to binary wire format with appended CRC16."""
        header = struct.pack(
            RADIO_HEADER_FORMAT,
            RADIO_MAGIC,
            self.msg_type,
            self.session_id,
            self.packet_seq,
            self.total_packets,
        )
        body = header + self.payload
        crc = crc16_ccitt(body)
        trailer = struct.pack(">H", crc)
        return body + trailer

    @classmethod
    def from_bytes(cls, data: bytes, verify_crc: bool = True) -> RadioPacket:
        """Deserialize frame and verify CRC16."""
        if len(data) < RADIO_OVERHEAD:
            raise ValueError(f"Radio frame too short: {len(data)} < {RADIO_OVERHEAD}")

        body = data[:-RADIO_TRAILER_SIZE]
        crc_received = struct.unpack(">H", data[-RADIO_TRAILER_SIZE:])[0]

        if verify_crc:
            crc_calc = crc16_ccitt(body)
            if crc_calc != crc_received:
                raise ValueError(f"Radio CRC16 mismatch: calc {hex(crc_calc)} != got {hex(crc_received)}")

        magic, msg_type, session_id, packet_seq, total_packets = struct.unpack_from(
            RADIO_HEADER_FORMAT, body, 0
        )
        if magic != RADIO_MAGIC:
            raise ValueError(f"Invalid radio magic byte: {hex(magic)}")

        payload = body[RADIO_HEADER_SIZE:]
        return cls(
            msg_type=msg_type,
            session_id=session_id,
            packet_seq=packet_seq,
            total_packets=total_packets,
            payload=payload,
        )


class RadioFramePacker:
    """Fragments arbitrary binary payloads into MTU-bounded radio packets."""

    def __init__(self, max_packet_size: int = 200):
        if max_packet_size <= RADIO_OVERHEAD:
            raise ValueError(f"MTU {max_packet_size} must be > overhead {RADIO_OVERHEAD}")
        self.max_packet_size = max_packet_size
        self.max_payload_size = max_packet_size - RADIO_OVERHEAD

    def fragment(self, data: bytes, msg_type: int = 0x01, session_id: int = 1) -> List[RadioPacket]:
        """Split data into consecutive radio packets."""
        if not data:
            return []

        chunks = [
            data[i : i + self.max_payload_size]
            for i in range(0, len(data), self.max_payload_size)
        ]
        total_packets = len(chunks)
        if total_packets > 65535:
            raise ValueError(f"Payload too large for 16-bit radio sequence: {total_packets} packets")

        packets = []
        for seq, chunk in enumerate(chunks):
            pkt = RadioPacket(
                msg_type=msg_type,
                session_id=session_id & 0xFFFF,
                packet_seq=seq,
                total_packets=total_packets,
                payload=chunk,
            )
            packets.append(pkt)

        return packets


class RadioFrameReassembler:
    """Reassembles fragmented radio frames per session ID with CRC validation."""

    def __init__(self):
        self._sessions: Dict[int, Dict[int, bytes]] = {}
        self._session_totals: Dict[int, int] = {}
        self.stats_crc_errors = 0
        self.stats_packets_accepted = 0

    def ingest_bytes(self, raw_bytes: bytes) -> Optional[Tuple[int, int, bytes]]:
        """
        Parse raw radio frame bytes. Returns (session_id, msg_type, reassembled_data)
        when a full message is completed, else None.
        """
        try:
            pkt = RadioPacket.from_bytes(raw_bytes, verify_crc=True)
            self.stats_packets_accepted += 1
            return self.ingest_packet(pkt)
        except ValueError:
            self.stats_crc_errors += 1
            return None

    def ingest_packet(self, pkt: RadioPacket) -> Optional[Tuple[int, int, bytes]]:
        """Ingest a validated RadioPacket."""
        sid = pkt.session_id
        if sid not in self._sessions:
            self._sessions[sid] = {}
            self._session_totals[sid] = pkt.total_packets

        self._sessions[sid][pkt.packet_seq] = pkt.payload

        total = self._session_totals[sid]
        if len(self._sessions[sid]) == total:
            # All packets arrived! Reassemble in order
            parts = [self._sessions[sid][i] for i in range(total)]
            del self._sessions[sid]
            del self._session_totals[sid]
            return (sid, pkt.msg_type, b"".join(parts))

        return None
