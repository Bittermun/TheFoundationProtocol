# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and integration tests for Meshtastic LoRa Bridge and SLIP Framing.
"""

import pytest

from tfp_transport.meshtastic_bridge import (
    MeshtasticFrameCodec,
    MeshtasticPacket,
)


def test_meshtastic_slip_roundtrip():
    """Verify raw SLIP framing escapes 0xC0 and 0xDB delimiters correctly."""
    raw = b"\x01\x02\xc0\x03\xdb\x04\xc0\xdb"
    packed = MeshtasticFrameCodec.slip_pack(raw)
    assert packed.startswith(b"\xc0")
    assert packed.endswith(b"\xc0")
    # Verify no raw unescaped 0xC0 or 0xDB inside the payload body
    body = packed[1:-1]
    assert b"\xc0" not in body
    assert b"\xdb\x04" not in body  # Must be escaped

    unpacked = MeshtasticFrameCodec.slip_unpack(packed)
    assert unpacked == raw


def test_meshtastic_frame_encode_decode_roundtrip():
    """Verify packing and unpacking of a TFP droplet into a Meshtastic frame."""
    droplet_payload = b"X" * 192
    session_id = 0x12345678
    seed = 42
    degree = 3
    flags = 0x01
    channel_index = 1
    hop_limit = 0

    frame = MeshtasticFrameCodec.encode(
        session_id=session_id,
        seed=seed,
        degree=degree,
        data=droplet_payload,
        flags=flags,
        channel_index=channel_index,
        hop_limit=hop_limit,
    )

    packet = MeshtasticFrameCodec.decode(frame)
    assert isinstance(packet, MeshtasticPacket)
    assert packet.session_id == session_id
    assert packet.seed == seed
    assert packet.degree == degree
    assert packet.flags == flags
    assert packet.channel_index == channel_index
    assert packet.hop_limit == hop_limit
    assert packet.data == droplet_payload


def test_meshtastic_frame_corrupt_or_truncated():
    """Verify malformed frames are rejected with ValueError."""
    # Truncated header (< 10 bytes payload)
    corrupt_frame = MeshtasticFrameCodec.slip_pack(b"\x01\x02\x03")
    with pytest.raises(ValueError, match="Frame too short"):
        MeshtasticFrameCodec.decode(corrupt_frame)
