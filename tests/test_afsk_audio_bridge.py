# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import pytest
import io
import wave
from tfp_client.lib.audio.afsk_modulator import AFSKModulator, crc16_ccitt
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator


def test_crc16_ccitt():
    data1 = b"123456789"
    # Standard CRC16-CCITT for "123456789" with 0xFFFF init is 0x29B1
    crc1 = crc16_ccitt(data1)
    assert crc1 == 0x29B1

    # Tampering test
    data2 = b"123456788"
    assert crc16_ccitt(data2) != crc1


def test_afsk_frame_packet_structure():
    mod = AFSKModulator(baud_rate=1200, preamble_flags=8)
    payload = b"HELLO_TFP"
    framed = mod.frame_packet(payload)

    # Starts with preamble flags (0x7E)
    assert framed[:8] == bytes([0x7E] * 8)
    # Length is 9 bytes
    length = (framed[8] << 8) | framed[9]
    assert length == 9
    # Payload matches
    assert framed[10:19] == payload
    # CRC16 is appended
    expected_crc = crc16_ccitt(payload)
    actual_crc = (framed[19] << 8) | framed[20]
    assert actual_crc == expected_crc


def test_afsk_modulation_and_demodulation_roundtrip():
    # Use 16000 Hz sample rate, 1200 baud
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

    test_payloads = [
        b"TFP_ALERT:BOIL_WATER",
        b"EMERGENCY_MEDICAL_MANUAL_ROOT_SHA3_256",
        b"{\"type\":\"radio_chunk\",\"seq\":1,\"data\":\"abc\"}",
    ]

    for payload in test_payloads:
        wav_bytes = modulator.synthesize_wav(payload, amplitude=0.8)
        assert len(wav_bytes) > 1000

        # Verify WAV header
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 16000

        # Demodulate
        decoded_packets = demodulator.decode_wav(wav_bytes)
        assert len(decoded_packets) >= 1
        assert payload in decoded_packets


def test_afsk_corrupted_noise_rejection():
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=8)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

    # Pure silence or random noise
    silence = bytes(8000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(silence)

    decoded = demodulator.decode_wav(buf.getvalue())
    assert decoded == []  # Rejects noise cleanly without crash or false positives


def test_afsk_attenuated_signal_with_agc():
    """Verify that AGC allows demodulation of quiet/attenuated audio (e.g. distant phone microphone)."""
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

    payload = b"QUIET_CLINIC_BEACON:DRUGS_OK"
    # Synthesize at very low amplitude: 0.05 (~24 dB attenuation below normal)
    quiet_wav = modulator.synthesize_wav(payload, amplitude=0.05)

    decoded = demodulator.decode_wav(quiet_wav)
    assert len(decoded) >= 1
    assert payload in decoded, "AGC must normalize and recover quiet audio packets"
