# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Physical Radio & LoRa Subsystem.

Verifies:
1. Hardware CRC16 checksum calculation and bit-error rejection.
2. MTU-constrained (<200 bytes) packet fragmentation and reassembly.
3. Out-of-order radio packet arrival handling.
4. KISS TNC protocol framing with FEND/FESC byte-stuffing and stream chunking.
"""

from pathlib import Path
import random
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.radio.framing import (
    RadioPacket,
    RadioFramePacker,
    RadioFrameReassembler,
    crc16_ccitt,
)
from tfp_client.lib.radio.kiss_interface import KISSInterface, FEND, FESC, TFEND, TFESC


def test_crc16_integrity_and_tampering():
    """Verify CRC16 calculation and bit-flip rejection."""
    data = b"FOUNDATION-RADIO-TEST-PACKET-12345"
    crc = crc16_ccitt(data)
    assert isinstance(crc, int)
    assert 0 <= crc <= 0xFFFF

    pkt = RadioPacket(
        msg_type=0x01,
        session_id=42,
        packet_seq=0,
        total_packets=1,
        payload=data,
    )
    raw = pkt.to_bytes()
    assert len(raw) == 8 + len(data) + 2

    # Valid parse
    parsed = RadioPacket.from_bytes(raw)
    assert parsed.payload == data
    assert parsed.session_id == 42

    # Bit-flip tampering (simulating RF noise)
    corrupt = bytearray(raw)
    corrupt[5] ^= 0x01  # flip 1 bit in header
    with pytest.raises(ValueError, match="Radio CRC16 mismatch"):
        RadioPacket.from_bytes(bytes(corrupt))


def test_radio_packetizer_fragment_reassemble():
    """Verify fragmentation and reassembly of 10KB payload into 200-byte radio packets."""
    payload = b"CRITICAL-EMERGENCY-MEDICAL-BULLETIN-" * 280  # ~10 KB
    packer = RadioFramePacker(max_packet_size=200)
    packets = packer.fragment(payload, msg_type=0x02, session_id=777)

    assert len(packets) > 50  # Over fifty 200-byte packets

    # Assert every single wire frame fits strictly within the 200-byte physical radio MTU
    for pkt in packets:
        raw_bytes = pkt.to_bytes()
        assert len(raw_bytes) <= 200

    # Ingest packets through reassembler
    reassembler = RadioFrameReassembler()
    result = None
    for pkt in packets:
        res = reassembler.ingest_bytes(pkt.to_bytes())
        if res is not None:
            result = res

    assert result is not None
    session_id, msg_type, reassembled = result
    assert session_id == 777
    assert msg_type == 0x02
    assert reassembled == payload


def test_radio_packetizer_out_of_order_arrival():
    """Verify packets arriving out-of-order over radio link still assemble properly."""
    payload = b"RADIO-DATA-SEGMENT-" * 64  # ~1.2 KB
    packer = RadioFramePacker(max_packet_size=150)
    packets = packer.fragment(payload, msg_type=0x01, session_id=99)

    # Scramble transmission order
    rng = random.Random(123)
    scrambled = list(packets)
    rng.shuffle(scrambled)

    reassembler = RadioFrameReassembler()
    result = None
    for pkt in scrambled:
        res = reassembler.ingest_bytes(pkt.to_bytes())
        if res is not None:
            result = res

    assert result is not None
    _, _, reassembled = result
    assert reassembled == payload


def test_kiss_framing_round_trip():
    """Verify standard KISS frame encoding, escaping, and stream parsing."""
    # Data deliberately containing FEND (0xC0) and FESC (0xDB) special characters
    tricky_data = bytes([0x01, 0x02, FEND, 0x03, FESC, 0x04, FEND, FESC, 0x05])

    kiss_frame = KISSInterface.encode_frame(tricky_data, port=1)
    assert kiss_frame.startswith(bytes([FEND]))
    assert kiss_frame.endswith(bytes([FEND]))

    # Ensure inner delimiters were escaped
    inner_payload = kiss_frame[2:-1]
    assert FEND not in inner_payload

    # Decode via streaming interface
    kiss = KISSInterface()
    packets = kiss.ingest_stream(kiss_frame)
    assert len(packets) == 1
    assert packets[0].port == 1
    assert packets[0].data == tricky_data

    # Test chunked stream arrival (e.g. UART split across 2 reads)
    kiss2 = KISSInterface()
    half = len(kiss_frame) // 2
    res1 = kiss2.ingest_stream(kiss_frame[:half])
    assert len(res1) == 0  # incomplete frame

    res2 = kiss2.ingest_stream(kiss_frame[half:])
    assert len(res2) == 1
    assert res2[0].data == tricky_data
