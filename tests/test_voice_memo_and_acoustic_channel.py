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


def test_vocoder_compression_ratio_and_decompression():
    """Verify 1200 bps vocoder achieves > 95% data reduction on speech audio."""
    from tfp_client.lib.audio.vocoder import compress_speech, decompress_speech

    # Synthesize 5 seconds of 8000 Hz voiced harmonic audio (160 Hz fundamental + formants)
    sample_rate = 8000
    n_samples = sample_rate * 5
    raw_pcm = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        val = (
            8000.0 * math.sin(2.0 * math.pi * 160.0 * t)
            + 4000.0 * math.sin(2.0 * math.pi * 750.0 * t)
            + 2500.0 * math.sin(2.0 * math.pi * 1400.0 * t)
            + 1500.0 * math.sin(2.0 * math.pi * 2800.0 * t)
        )
        clamped = int(max(-32768, min(32767, val)))
        raw_pcm.extend(struct.pack("<h", clamped))

    raw_bytes = bytes(raw_pcm)
    assert len(raw_bytes) == 80000  # 5s * 8000 * 2 bytes = 80 KB

    compressed = compress_speech(raw_bytes, sample_rate=sample_rate)
    # 5s * 50 fps * 3 B/f + 4B header = 754 bytes
    assert len(compressed) <= 800
    compression_ratio = (len(raw_bytes) - len(compressed)) / len(raw_bytes)
    assert compression_ratio > 0.98, f"Expected > 98% compression, got {compression_ratio * 100:.2f}%"

    decompressed = decompress_speech(compressed, sample_rate=sample_rate)
    assert len(decompressed) == len(raw_bytes)

    # Signal fidelity: verify output contains audio energy, not silence
    import numpy as np
    in_samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float64)
    out_samples = np.frombuffer(decompressed, dtype=np.int16).astype(np.float64)
    in_rms = float(np.sqrt(np.mean(in_samples**2)))
    out_rms = float(np.sqrt(np.mean(out_samples**2)))
    assert out_rms > 0, "Vocoder output is total silence — compress/decompress produced zero energy"
    assert out_rms > in_rms * 0.01, (
        f"Vocoder output energy too low: input RMS={in_rms:.1f}, output RMS={out_rms:.1f}, "
        f"ratio={out_rms/in_rms:.4f} (expected >1%)"
    )
    non_zero = int(np.sum(np.abs(out_samples) > 0))
    assert non_zero > len(out_samples) * 0.5, (
        f"Too few non-zero samples: {non_zero}/{len(out_samples)}"
    )


def test_voice_memo_vocoder_roundtrip_and_wav_generation():
    """Verify VoiceMemo handles vocoder compression, deserialization, and WAV playback."""
    # Synthesize 2 seconds of audio
    sample_rate = 8000
    n_samples = sample_rate * 2
    raw_pcm = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        val = int(12000.0 * math.sin(2.0 * math.pi * 200.0 * t))
        raw_pcm.extend(struct.pack("<h", clamped := max(-32768, min(32767, val))))

    memo = VoiceMemo(
        callsign="DISPATCH",
        sample_rate=sample_rate,
        pcm_data=bytes(raw_pcm),
        is_vocoder=False,
    )
    assert len(memo.pcm_data) == 32000

    compressed_memo = memo.compress()
    assert compressed_memo.is_vocoder is True
    assert len(compressed_memo.pcm_data) <= 350  # ~304 bytes

    # Wire serialization
    wire = compressed_memo.to_bytes()
    assert len(wire) < 400

    # Deserialization without auto-decompress
    recovered_comp = VoiceMemo.from_bytes(wire)
    assert recovered_comp.is_vocoder is True
    assert recovered_comp.callsign == "DISPATCH"

    # Deserialization with auto-decompress
    recovered_decomp = VoiceMemo.from_bytes(wire, auto_decompress=True)
    assert recovered_decomp.is_vocoder is False
    assert len(recovered_decomp.pcm_data) == 32000

    # WAV generation from compressed memo auto-decompresses
    wav_bytes = compressed_memo.to_wav()
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 8000
        assert w.getnframes() == 16000


def test_vocoder_transmission_over_acoustic_channel():
    """Verify vocoder voice memo transmits through simulated room acoustics over Bell 202 tones."""
    sample_rate = 8000
    n_samples = sample_rate * 1  # 1-second audio snippet
    raw_pcm = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        val = int(10000.0 * math.sin(2.0 * math.pi * 240.0 * t))
        raw_pcm.extend(struct.pack("<h", max(-32768, min(32767, val))))

    memo = VoiceMemo(callsign="VILLAGE3", sample_rate=sample_rate, pcm_data=bytes(raw_pcm)).compress()
    wire_memo = memo.to_bytes()
    assert len(wire_memo) < 200  # 1s vocoder payload is ~154 bytes + header + CRC

    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=777)

    # Modulate into Bell 202 audio
    tx_wav = modulator.synthesize_wav(wire_memo, amplitude=0.8, include_chirp=True)

    # Impair with room reflections, attenuation, and noise
    rx_wav = sim.impair_wav(
        tx_wav,
        attenuation=0.50,
        snr_db=30.0,
        reverberation=True,
        clipping=False,
    )

    # Demodulate and reconstruct
    recovered_packets = demodulator.decode_wav(rx_wav)
    assert len(recovered_packets) >= 1
    assert wire_memo in recovered_packets

    rx_memo = VoiceMemo.from_bytes(wire_memo, auto_decompress=True)
    assert rx_memo.callsign == "VILLAGE3"
    assert rx_memo.sample_rate == 8000
    assert len(rx_memo.pcm_data) == 8000 * 2

