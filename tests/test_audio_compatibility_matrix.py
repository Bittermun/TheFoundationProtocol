# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Audio Compatibility & Robustness Matrix Test Battery.

Executes physical and digital audio impairment scenarios against Bell 202 AFSK
broadcast signals using FFmpeg and AcousticChannelSimulator.

Covers:
1. Sample rate conversions:
   - 16,000 Hz -> 44,100 Hz (CD Audio)
   - 16,000 Hz -> 48,000 Hz (Broadcast / DAT / Studio standard)
   - 16,000 Hz -> 8,000 Hz (Narrowband telephony / VHF voice channel)
2. Timing offsets & leading silence:
   - 0 ms, 50 ms, 250 ms, 1,000 ms leading acoustic silence
3. Lossy compression codecs:
   - MP3 at 128 kbps (standard web/podcast distribution)
   - MP3 at 96 kbps (low-bandwidth distribution)
   - AAC at 96 kbps (modern mobile streaming)
   - AAC at 64 kbps (harsh mobile streaming)
4. Gain changes, non-linear distortion, and acoustic channel effects:
   - Gain +6 dB (boosted / potential overdrive)
   - Gain -12 dB (attenuated broadcast level)
   - Gain -24 dB (very low level, validates AGC recovery)
   - Non-linear microphone clipping / saturation
   - Preamble fade-in (50 ms linear ramp)
   - Short audio dropout (5 ms silence drop during preamble)
   - Multipath room reverberation + AWGN noise
5. Exact metrics recording:
   - Measures and logs exact payload recovery (bit-for-bit), audio airtime, and decode runtime.
"""

from pathlib import Path
import io
import shutil
import struct
import subprocess
import time
import wave
import pytest

from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator

# Test bulletin payload
TEST_PAYLOAD = (
    b'{"id":"BULLETIN-CHL-001","rev":1,'
    b'"title":"Cholera Alert & Sanitation Protocol",'
    b'"body":"BOIL ALL WATER FOR 60 SECONDS. DISTRIBUTE ORS TO CLINICS 3 AND 7."}'
)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """Executes ffmpeg with captured output and standard flags."""
    cmd = ["ffmpeg", "-y", "-v", "error"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


@pytest.fixture(scope="module")
def base_broadcast_wav(tmp_path_factory) -> tuple[bytes, float]:
    """Generates baseline 16 kHz Bell 202 AFSK audio for testing."""
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    wav_bytes = modulator.synthesize_wav(TEST_PAYLOAD)
    duration = len(wav_bytes) / (16000 * 2)
    return wav_bytes, duration


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg binary not available in PATH")
@pytest.mark.parametrize("target_sr", [44100, 48000, 8000])
def test_audio_matrix_sample_rate_conversions(base_broadcast_wav, tmp_path: Path, target_sr: int):
    """Verify audio modulation survives standard broadcast sample rate conversions."""
    wav_bytes, baseline_duration = base_broadcast_wav
    src_wav = tmp_path / "src.wav"
    converted_wav = tmp_path / f"converted_{target_sr}.wav"
    src_wav.write_bytes(wav_bytes)

    # Convert to target sample rate using FFmpeg high-quality resampler
    run_ffmpeg(["-i", str(src_wav), "-ar", str(target_sr), "-ac", "1", str(converted_wav)])

    # Demodulate with exact target sample rate
    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=target_sr, baud_rate=1200)
    packets = demod.decode_wav(converted_wav.read_bytes())
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, f"Failed at {target_sr} Hz: recovered {len(packets)} packets"
    assert packets[0] == TEST_PAYLOAD, f"Bit mismatch at {target_sr} Hz"
    print(f"\n[SAMPLE RATE {target_sr}Hz] Airtime: {baseline_duration:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg binary not available in PATH")
@pytest.mark.parametrize("delay_ms", [0, 50, 250, 1000])
def test_audio_matrix_timing_offsets_and_silence(base_broadcast_wav, tmp_path: Path, delay_ms: int):
    """Verify HDLC frame sync locks correctly across arbitrary leading silence."""
    wav_bytes, baseline_duration = base_broadcast_wav
    src_wav = tmp_path / "src.wav"
    delayed_wav = tmp_path / f"delay_{delay_ms}ms.wav"
    src_wav.write_bytes(wav_bytes)

    if delay_ms > 0:
        run_ffmpeg(["-i", str(src_wav), "-af", f"adelay={delay_ms}|{delay_ms}", str(delayed_wav)])
    else:
        delayed_wav.write_bytes(wav_bytes)

    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    packets = demod.decode_wav(delayed_wav.read_bytes())
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, f"Failed at delay {delay_ms}ms"
    assert packets[0] == TEST_PAYLOAD
    total_airtime = baseline_duration + (delay_ms / 1000.0)
    print(f"\n[TIMING OFFSET {delay_ms}ms] Total Airtime: {total_airtime:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg binary not available in PATH")
@pytest.mark.parametrize(
    "codec,bitrate,ext",
    [
        ("libmp3lame", "128k", "mp3"),
        ("libmp3lame", "96k", "mp3"),
        ("aac", "96k", "m4a"),
        ("aac", "64k", "m4a"),
    ],
)
def test_audio_matrix_lossy_compression(base_broadcast_wav, tmp_path: Path, codec: str, bitrate: str, ext: str):
    """Verify audio data survives perceptual lossy compression (MP3, AAC) common in radio archives."""
    wav_bytes, baseline_duration = base_broadcast_wav
    src_wav = tmp_path / "src.wav"
    encoded_file = tmp_path / f"encoded_{codec}_{bitrate}.{ext}"
    decoded_wav = tmp_path / f"decoded_{codec}_{bitrate}.wav"
    src_wav.write_bytes(wav_bytes)

    # Encode with lossy codec
    run_ffmpeg(["-i", str(src_wav), "-c:a", codec, "-b:a", bitrate, str(encoded_file)])
    # Decode back to 16 kHz mono PCM WAV
    run_ffmpeg(["-i", str(encoded_file), "-ar", "16000", "-ac", "1", str(decoded_wav)])

    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    packets = demod.decode_wav(decoded_wav.read_bytes())
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, f"Failed lossy test {codec} @ {bitrate}: recovered {len(packets)} packets"
    assert packets[0] == TEST_PAYLOAD, f"Bit mismatch after {codec} @ {bitrate}"
    print(f"\n[LOSSY {codec.upper()} @ {bitrate}] Airtime: {baseline_duration:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg binary not available in PATH")
@pytest.mark.parametrize("gain_db", [6, -12, -24])
def test_audio_matrix_gain_changes_and_agc(base_broadcast_wav, tmp_path: Path, gain_db: int):
    """Verify Automatic Gain Control (AGC) normalizes boosted (+6dB) or heavily attenuated (-24dB) signals."""
    wav_bytes, baseline_duration = base_broadcast_wav
    src_wav = tmp_path / "src.wav"
    gain_wav = tmp_path / f"gain_{gain_db}db.wav"
    src_wav.write_bytes(wav_bytes)

    run_ffmpeg(["-i", str(src_wav), "-af", f"volume={gain_db}dB", str(gain_wav)])

    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    packets = demod.decode_wav(gain_wav.read_bytes())
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, f"Failed gain test {gain_db} dB"
    assert packets[0] == TEST_PAYLOAD
    print(f"\n[GAIN {gain_db:+d}dB AGC] Airtime: {baseline_duration:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")


def test_audio_matrix_channel_simulator_distortions(base_broadcast_wav):
    """Verify survival under multipath room reverberation, AWGN noise, and microphone overdrive clipping."""
    wav_bytes, baseline_duration = base_broadcast_wav
    sim = AcousticChannelSimulator(seed=12345)

    # Apply 40% attenuation, 28 dB SNR AWGN noise, 3-tap room echo reverberation, and saturation clipping
    impaired_wav = sim.impair_wav(
        wav_bytes,
        attenuation=0.60,
        snr_db=28.0,
        reverberation=True,
        clipping=True,
    )

    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    packets = demod.decode_wav(impaired_wav)
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, f"Failed channel simulator test: recovered {len(packets)} packets"
    assert packets[0] == TEST_PAYLOAD
    print(f"\n[ACOUSTIC CHANNEL IMPAIRMENTS] Airtime: {baseline_duration:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")


def test_audio_matrix_preamble_fade_in_and_dropout(base_broadcast_wav):
    """Verify survival under realistic transmitter startup fade-in (50ms) and short preamble dropout (5ms)."""
    wav_bytes, baseline_duration = base_broadcast_wav

    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as w:
        sr = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)

    samples = list(struct.unpack(f"<{n_frames}h", raw))

    # 1. 50ms Linear Fade-In (simulates analog transmitter power-amp ramp up)
    fade_len = int(0.050 * sr)
    for i in range(min(fade_len, len(samples))):
        samples[i] = int(samples[i] * (i / fade_len))

    # 2. 5ms RF Dropout at 30ms (simulates momentary squelch / relay glitch)
    drop_start = int(0.030 * sr)
    drop_len = int(0.005 * sr)
    for i in range(drop_start, min(drop_start + drop_len, len(samples))):
        samples[i] = 0

    faded_raw = struct.pack(f"<{len(samples)}h", *samples)
    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(faded_raw)

    t0 = time.perf_counter()
    demod = AFSKDemodulator(sample_rate=sr, baud_rate=1200)
    packets = demod.decode_wav(out_buf.getvalue())
    decode_time_ms = (time.perf_counter() - t0) * 1000.0

    assert len(packets) == 1, "Failed preamble fade-in / dropout test"
    assert packets[0] == TEST_PAYLOAD
    print(f"\n[FADE-IN & SHORT DROPOUT] Airtime: {baseline_duration:.2f}s | Decode: {decode_time_ms:.1f}ms | 100% BIT-EXACT")
