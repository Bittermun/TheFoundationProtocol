# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and integration tests for Meshtastic LoRa Bridge and SLIP Framing.
"""

import asyncio

import pytest

from tfp_transport.meshtastic_bridge import (
    AirtimePacer,
    MeshtasticBroadcaster,
    MeshtasticFrameCodec,
    MeshtasticListener,
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


def test_airtime_calculation_and_pacing():
    """Verify LoRa airtime calculation and duty-cycle delay enforcement."""
    from tfp_transport.meshtastic_bridge import AirtimePacer

    # For SF7, BW 125 kHz, CR 4/5 (cr_index=1), 200B payload
    # Theoretical airtime is typically ~300ms to 450ms
    airtime_ms = AirtimePacer.compute_lora_airtime_ms(
        payload_len=200, sf=7, bw_khz=125.0, cr=1, preamble_len=8, has_crc=True
    )
    assert 300.0 < airtime_ms < 450.0

    # Test duty cycle delay:
    # 1% duty cycle (0.01) means for 400ms of airtime, must rest >= 39.6 seconds
    pacer = AirtimePacer(duty_cycle_fraction=0.01, sf=7, bw_khz=125.0, cr=1)
    delay_s = pacer.calculate_required_delay(airtime_ms=400.0)
    assert 39.0 <= delay_s <= 40.0

    # 100% duty cycle (1.0) means no delay
    unlimited_pacer = AirtimePacer(duty_cycle_fraction=1.0)
    assert unlimited_pacer.calculate_required_delay(airtime_ms=400.0) == 0.0


@pytest.mark.asyncio
async def test_lora_simulated_serial_stream_reconstruction():
    """Verify end-to-end fountain stream broadcast and reconstruction over serial frames."""
    source_data = b"CIVIL DEFENSE WATER PURIFICATION TRIAGE BULLETIN." * 8  # ~400 bytes
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def mock_write(frame: bytes):
        await queue.put(frame)

    pacer = AirtimePacer(duty_cycle_fraction=1.0)  # unlimited for test speed
    broadcaster = MeshtasticBroadcaster(
        write_fn=mock_write,
        symbol_size=64,
        pacer=pacer,
    )
    listener = MeshtasticListener()

    async def receiver_loop():
        while not listener.is_complete(session_id=101):
            frame = await queue.get()
            listener.ingest_frame(frame)
            queue.task_done()

    rx_task = asyncio.create_task(receiver_loop())
    await broadcaster.broadcast_bytes(source_data, session_id=101, redundancy=0.50)
    await asyncio.wait_for(rx_task, timeout=5.0)

    assert listener.is_complete(session_id=101)
    recovered = listener.assemble(session_id=101)
    assert recovered == source_data


