# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Developing-World Audio-First ("Audio-Pocket") Test Suite.

Verifies:
1. VoiceMemo binary packing, CRC16 verification, and WAV conversion.
2. Acoustic channel simulator: multipath reverberation, AWGN noise, and clipping.
3. Acoustic preamble chirp detection and AFSK demodulation through harsh room acoustics.
"""

import io
import math
import struct
import wave
import pytest

from tfp_client.lib.audio.voice_memo import VoiceMemo
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator


def test_voice_memo_roundtrip():
    """Verify VoiceMemo creates bit-exact wire representations and recovers correctly."""
    # Synthesize 1 second of 8000 Hz 16-bit mono sine wave (440 Hz concert pitch)
    sample_rate = 8000
    n_samples = sample_rate
    raw_pcm = bytearray()
    for i in range(n_samples):
        val = int(16000.0 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
        raw_pcm.extend(struct.pack("<h", val))

    memo = VoiceMemo(
        callsign="CLINIC07",
        sample_rate=sample_rate,
        pcm_data=bytes(raw_pcm),
        is_16bit=True,
    )

    wire_bytes = memo.to_bytes()
    assert len(wire_bytes) > len(raw_pcm)

    recovered = VoiceMemo.from_bytes(wire_bytes)
    assert recovered.callsign == "CLINIC07"
    assert recovered.sample_rate == 8000
    assert recovered.is_16bit is True
    assert recovered.pcm_data == bytes(raw_pcm)
    assert recovered.duration_ms == 1000


def test_voice_memo_corrupted_crc_rejection():
    """Verify tampered voice memo bytes fail CRC16 check."""
    memo = VoiceMemo(
        callsign="MED_EVAC",
        sample_rate=8000,
        pcm_data=b"\x00\x01\x02\x03" * 200,
    )
    wire_bytes = bytearray(memo.to_bytes())

    # Flip a bit in the payload
    wire_bytes[30] ^= 0x40

    with pytest.raises(ValueError, match="checksum mismatch"):
        VoiceMemo.from_bytes(bytes(wire_bytes))


def test_voice_memo_wav_conversion():
    """Verify VoiceMemo converts to and from playable WAV files."""
    pcm = bytes([0x12, 0x34] * 500)  # 500 16-bit samples
    memo = VoiceMemo(callsign="AMBULANCE", sample_rate=8000, pcm_data=pcm)

    wav_bytes = memo.to_wav()
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 8000
        assert w.getnframes() == 500

    from_wav_memo = VoiceMemo.from_wav(wav_bytes, callsign="AMBULANCE")
    assert from_wav_memo.pcm_data == pcm
    assert from_wav_memo.sample_rate == 8000


def test_acoustic_channel_simulation_impairments():
    """Verify channel simulator applies echo, noise, attenuation, and clipping."""
    sim = AcousticChannelSimulator(seed=123)

    # Clean 1000-sample signal
    clean_samples = [10000.0 * math.sin(0.1 * i) for i in range(1000)]

    # 1. Attenuation
    attenuated = sim.apply_attenuation(clean_samples, factor=0.25)
    assert max(abs(x) for x in attenuated) < max(abs(x) for x in clean_samples)

    # 2. Multipath echo
    echoed = sim.apply_multipath_reverberation(clean_samples, sample_rate=16000)
    assert len(echoed) == len(clean_samples)
    # Energy in tail should be higher due to delayed reflections
    assert sum(x * x for x in echoed[350:500]) > sum(x * x for x in clean_samples[350:500])

    # 3. AWGN Noise
    noisy = sim.apply_awgn_noise(clean_samples, snr_db=15.0)
    assert noisy != clean_samples

    # 4. Clipping
    clipped = sim.apply_clipping(clean_samples, max_amplitude=5000.0)
    assert max(abs(x) for x in clipped) <= 5000.0


def test_afsk_preamble_chirp_demodulation_through_multipath():
    """Verify AFSK demodulator recovers packet with preamble chirp through room echo and attenuation."""
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=999)

    payload = b"TRIAGE:PATIENT_402:STABLE:BLOOD_O2_96%"
    # Synthesize with acoustic chirp preamble
    wav_with_chirp = modulator.synthesize_wav(payload, amplitude=0.8, include_chirp=True)

    # Degrade through channel simulator (attenuation to 0.40, mild room echo, 30 dB SNR noise)
    impaired_wav = sim.impair_wav(
        wav_with_chirp,
        attenuation=0.40,
        snr_db=30.0,
        reverberation=True,
        clipping=False,
    )

    # Demodulate with AGC
    extracted = demodulator.decode_wav(impaired_wav)
    assert len(extracted) >= 1
    assert payload in extracted, "AFSK demodulator must recover packet despite chirp and room echo"
