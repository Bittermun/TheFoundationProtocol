# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
KISS TNC Protocol Interface for TFP v4.0.

Implements standard KISS framing with byte-stuffing for serial communication
with hardware LoRa modems, Direwolf software soundcard modems, and amateur radio TNCs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


# KISS Protocol Special Characters
FEND = 0xC0   # Frame End delimiter
FESC = 0xDB   # Frame Escape delimiter
TFEND = 0xDC  # Transposed Frame End
TFESC = 0xDD  # Transposed Frame Escape

# Commands
CMD_DATA_FRAME = 0x00
CMD_TX_DELAY = 0x01
CMD_PERSISTENCE = 0x02
CMD_SLOT_TIME = 0x03
CMD_TX_TAIL = 0x04
CMD_FULL_DUPLEX = 0x05


@dataclass(frozen=True)
class KISSPacket:
    """A single decoded KISS packet."""

    port: int
    command: int
    data: bytes


class KISSInterface:
    """
    Encodes and decodes standard KISS frames over byte streams.
    Handles byte-stuffing and stream chunking.
    """

    def __init__(self):
        self._rx_buffer = bytearray()

    @staticmethod
    def escape_bytes(data: bytes) -> bytes:
        """Apply KISS byte-stuffing escapes."""
        escaped = bytearray()
        for b in data:
            if b == FEND:
                escaped.extend([FESC, TFEND])
            elif b == FESC:
                escaped.extend([FESC, TFESC])
            else:
                escaped.append(b)
        return bytes(escaped)

    @staticmethod
    def unescape_bytes(data: bytes) -> bytes:
        """Remove KISS byte-stuffing escapes."""
        unescaped = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == FESC and i + 1 < n:
                next_b = data[i + 1]
                if next_b == TFEND:
                    unescaped.append(FEND)
                    i += 2
                    continue
                elif next_b == TFESC:
                    unescaped.append(FESC)
                    i += 2
                    continue
            unescaped.append(b)
            i += 1
        return bytes(unescaped)

    @classmethod
    def encode_frame(cls, data: bytes, port: int = 0, command: int = CMD_DATA_FRAME) -> bytes:
        """
        Wrap arbitrary payload into a standard KISS frame:
        [FEND | (port << 4 | command) | escaped_data | FEND]
        """
        cmd_byte = ((port & 0x0F) << 4) | (command & 0x0F)
        escaped_payload = cls.escape_bytes(data)
        return bytes([FEND, cmd_byte]) + escaped_payload + bytes([FEND])

    def ingest_stream(self, chunk: bytes) -> List[KISSPacket]:
        """
        Feed an incoming byte stream chunk (e.g. from UART / COM port).
        Returns all fully framed KISS packets discovered so far.
        """
        self._rx_buffer.extend(chunk)
        packets: List[KISSPacket] = []

        while True:
            # Find first FEND delimiter
            try:
                start = self._rx_buffer.index(FEND)
            except ValueError:
                # No FEND in buffer
                break

            # Find next FEND delimiter
            try:
                end = self._rx_buffer.index(FEND, start + 1)
            except ValueError:
                # Incomplete frame, wait for next stream chunk
                # Discard any noise prior to start
                if start > 0:
                    del self._rx_buffer[:start]
                break

            frame_raw = self._rx_buffer[start + 1 : end]
            # Consume up to the closing FEND
            del self._rx_buffer[: end + 1]

            if not frame_raw:
                # Consecutive FENDs (keepalive or reset)
                continue

            cmd_byte = frame_raw[0]
            port = (cmd_byte >> 4) & 0x0F
            cmd = cmd_byte & 0x0F

            payload = self.unescape_bytes(frame_raw[1:])
            packets.append(KISSPacket(port=port, command=cmd, data=payload))

        return packets
