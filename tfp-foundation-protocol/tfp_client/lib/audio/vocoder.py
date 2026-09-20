# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Ultra-Low-Bitrate Parametric Vocoder (1200 bps).

Compacts 8 kHz 16-bit mono speech audio (16,000 bytes/sec) down to 150 bytes/sec
(1,200 bps, 3 bytes per 20ms frame) using linear predictive and sub-band parametric
vocal-tract modeling.

Enables 10-second field voice notes to compress into ~1.5 KB binary payloads,
transmissible in under 12 seconds over analog walkie-talkies and Bell 202 audio chirps.
"""

import math
import struct
from typing import List, Tuple
import numpy as np

VOCODER_MAGIC = b"VC01"  # 4-byte header: "VC" + version 1
FRAME_MS = 20
SAMPLE_RATE = 8000
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 160 samples
BYTES_PER_FRAME = 3
PREEMPHASIS_COEFF = 0.95


class VocoderCodec:
    """
    Parametric Speech Compressor and Synthesizer operating at 1200 bps (50 fps * 24 bits).
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.frame_samples = int(sample_rate * FRAME_MS / 1000)

    def compress(self, pcm_bytes: bytes) -> bytes:
        """
        Compresses 16-bit mono PCM bytes into 1200 bps vocoder bitstream.
        """
        rem = len(pcm_bytes) % 2
        if rem != 0:
            pcm_bytes = pcm_bytes[: len(pcm_bytes) - rem]

        if len(pcm_bytes) < 2:
            return VOCODER_MAGIC

        # Convert to float numpy array
        raw_samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        n_samples = len(raw_samples)
        if n_samples == 0:
            return VOCODER_MAGIC

        # Normalize to [-1.0, 1.0]
        raw_samples = raw_samples / 32768.0

        # Pre-emphasis filter
        pe_samples = np.empty_like(raw_samples)
        pe_samples[0] = raw_samples[0]
        pe_samples[1:] = raw_samples[1:] - PREEMPHASIS_COEFF * raw_samples[:-1]

        n_frames = (n_samples + FRAME_SAMPLES - 1) // FRAME_SAMPLES
        out_bytes = bytearray(VOCODER_MAGIC)

        for f_idx in range(n_frames):
            start = f_idx * FRAME_SAMPLES
            end = min(start + FRAME_SAMPLES, n_samples)
            frame_raw = raw_samples[start:end]
            frame_pe = pe_samples[start:end]

            if len(frame_raw) < FRAME_SAMPLES:
                frame_raw = np.pad(frame_raw, (0, FRAME_SAMPLES - len(frame_raw)))
                frame_pe = np.pad(frame_pe, (0, FRAME_SAMPLES - len(frame_pe)))

            frame_packed = self._encode_frame(frame_raw, frame_pe)
            out_bytes.extend(frame_packed)

        return bytes(out_bytes)

    def decompress(self, vocoder_bytes: bytes) -> bytes:
        """
        Decompresses 1200 bps vocoder bitstream back into 16-bit mono PCM.
        """
        if len(vocoder_bytes) < len(VOCODER_MAGIC) or vocoder_bytes[: len(VOCODER_MAGIC)] != VOCODER_MAGIC:
            raise ValueError(f"Invalid vocoder magic: {vocoder_bytes[:4]!r}")

        payload = vocoder_bytes[len(VOCODER_MAGIC) :]
        n_frames = len(payload) // BYTES_PER_FRAME

        out_samples = []
        phase = 0.0
        prev_tail = np.zeros(16, dtype=np.float32)

        for f_idx in range(n_frames):
            frame_chunk = payload[f_idx * BYTES_PER_FRAME : (f_idx + 1) * BYTES_PER_FRAME]
            samples, phase = self._decode_frame(frame_chunk, phase)

            # Smooth overlap-add crossfade of 16 samples at frame boundary
            cross_len = min(len(samples), 16)
            if cross_len > 0 and len(out_samples) >= cross_len:
                fade_in = np.linspace(0.0, 1.0, cross_len, dtype=np.float32)
                fade_out = 1.0 - fade_in
                for i in range(cross_len):
                    samples[i] = fade_in[i] * samples[i] + fade_out[i] * prev_tail[i]

            prev_tail = samples[-16:].copy() if len(samples) >= 16 else np.zeros(16, dtype=np.float32)
            out_samples.extend(samples)

        out_array = np.array(out_samples, dtype=np.float32)
        # Clamping and conversion to 16-bit PCM
        clipped = np.clip(out_array, -32767.0, 32767.0).astype(np.int16)
        return clipped.tobytes()

    def _encode_frame(self, frame_raw: np.ndarray, frame_pe: np.ndarray) -> bytes:
        """Encodes a single 160-sample frame into 24 bits (3 bytes)."""
        # 1. Compute RMS energy (frame_raw is normalized to [-1.0, 1.0])
        rms = float(np.sqrt(np.mean(frame_raw**2)))
        if rms < 0.001:
            # Silence / noise floor (~-60 dBFS): return all zeros frame
            return b"\x00\x00\x00"

        # Log energy quantized to 5 bits (0..31)
        # Scale RMS back to int16 range for dB calculation to preserve existing quantization
        rms_int16 = rms * 32768.0
        db = 20.0 * math.log10(max(1.0, rms_int16))
        # Map 20 dB .. 90 dB into 1 .. 31
        energy_idx = int(np.clip(round((db - 20.0) / (70.0 / 30.0)) + 1, 1, 31))

        # 2. Voicing & Pitch detection using normalized autocorrelation
        # Lag range: 20 to 147 samples (54 Hz to 400 Hz)
        min_lag = 20
        max_lag = min(147, len(frame_pe) - 1)
        corr_len = len(frame_pe) - max_lag

        r_zero = np.sum(frame_pe[:corr_len] ** 2)
        best_lag = min_lag
        max_norm_corr = 0.0

        if r_zero > 1e-4:
            for lag in range(min_lag, max_lag + 1):
                seg_lag = frame_pe[lag : lag + corr_len]
                r_lag = np.sum(frame_pe[:corr_len] * seg_lag)
                e_lag = np.sum(seg_lag**2)
                denom = math.sqrt(r_zero * e_lag) + 1e-6
                norm_c = r_lag / denom
                if norm_c > max_norm_corr:
                    max_norm_corr = norm_c
                    best_lag = lag

        # Zero crossing rate
        zcr = np.mean(np.abs(np.diff(np.sign(frame_raw)))) / 2.0

        is_voiced = bool(max_norm_corr >= 0.36 and zcr < 0.38)
        pitch_val = int(np.clip(best_lag - min_lag, 0, 127))  # 7 bits

        # 3. Spectral envelope: 256-point FFT
        windowed = frame_pe * np.hanning(len(frame_pe))
        fft_mag = np.abs(np.fft.rfft(windowed, n=256))  # 129 bins, ~31.25 Hz each

        word24 = 0
        if is_voiced:
            # Voiced: 1 bit (Voiced=1), 5 bits (Energy), 7 bits (Pitch), 11 bits (Spectral Formants: 4 + 4 + 3)
            # Band 1: 300 - 900 Hz (bins 10..29)
            # Band 2: 900 - 2200 Hz (bins 29..70)
            # Band 3: 2200 - 3800 Hz (bins 70..122)
            b1 = float(np.mean(fft_mag[10:30])) if len(fft_mag) > 30 else 1.0
            b2 = float(np.mean(fft_mag[30:71])) if len(fft_mag) > 71 else 1.0
            b3 = float(np.mean(fft_mag[71:122])) if len(fft_mag) > 122 else 1.0

            total_b = b1 + b2 + b3 + 1e-6
            r1 = b1 / total_b
            r2 = b2 / total_b
            r3 = b3 / total_b

            # Quantize
            q1 = int(np.clip(round(r1 * 15.0), 0, 15))  # 4 bits
            q2 = int(np.clip(round(r2 * 15.0), 0, 15))  # 4 bits
            q3 = int(np.clip(round(r3 * 7.0), 0, 7))    # 3 bits

            word24 = (1 << 23) | (energy_idx << 18) | (pitch_val << 11) | (q1 << 7) | (q2 << 3) | q3
        else:
            # Unvoiced: 1 bit (Voiced=0), 5 bits (Energy), 18 bits (4 Subbands: 4 + 4 + 5 + 5)
            # Band 1: 0 - 1000 Hz (bins 0..32)
            # Band 2: 1000 - 2000 Hz (bins 32..64)
            # Band 3: 2000 - 3000 Hz (bins 64..96)
            # Band 4: 3000 - 4000 Hz (bins 96..128)
            u1 = float(np.mean(fft_mag[0:32]))
            u2 = float(np.mean(fft_mag[32:64]))
            u3 = float(np.mean(fft_mag[64:96]))
            u4 = float(np.mean(fft_mag[96:128]))

            total_u = u1 + u2 + u3 + u4 + 1e-6
            qu1 = int(np.clip(round((u1 / total_u) * 15.0), 0, 15))  # 4 bits
            qu2 = int(np.clip(round((u2 / total_u) * 15.0), 0, 15))  # 4 bits
            qu3 = int(np.clip(round((u3 / total_u) * 31.0), 0, 31))  # 5 bits
            qu4 = int(np.clip(round((u4 / total_u) * 31.0), 0, 31))  # 5 bits

            word24 = (0 << 23) | (energy_idx << 18) | (qu1 << 14) | (qu2 << 10) | (qu3 << 5) | qu4

        # Return 3 bytes (big-endian 24-bit word)
        return bytes([(word24 >> 16) & 0xFF, (word24 >> 8) & 0xFF, word24 & 0xFF])

    def _decode_frame(self, chunk: bytes, phase: float) -> Tuple[np.ndarray, float]:
        """Decodes 3 bytes back into a synthesized 160-sample frame."""
        if len(chunk) < 3:
            return np.zeros(self.frame_samples, dtype=np.float32), phase

        word24 = (chunk[0] << 16) | (chunk[1] << 8) | chunk[2]
        is_voiced = bool((word24 >> 23) & 1)
        energy_idx = (word24 >> 18) & 0x1F

        if energy_idx == 0:
            # Silence
            return np.zeros(self.frame_samples, dtype=np.float32), phase

        # Reconstruct target RMS energy
        db = 20.0 + (energy_idx - 1) * (70.0 / 30.0)
        target_rms = 10.0 ** (db / 20.0)

        n = self.frame_samples
        excitation = np.zeros(n, dtype=np.float32)

        if is_voiced:
            pitch_val = (word24 >> 11) & 0x7F
            pitch_lag = pitch_val + 20  # 20 to 147 samples
            q1 = (word24 >> 7) & 0x0F
            q2 = (word24 >> 3) & 0x0F
            q3 = word24 & 0x07

            # Glottal pulse train excitation with continuous phase
            for i in range(n):
                phase += 1.0 / pitch_lag
                if phase >= 1.0:
                    phase -= 1.0
                    excitation[i] = 1.0
                elif phase < 0.25:
                    # Shaped glottal pulse rise
                    excitation[i] = math.sin(phase * 4.0 * (math.pi / 2.0))

            # Spectral shaping in frequency domain
            fft_ex = np.fft.rfft(excitation, n=256)
            g1 = max(0.05, q1 / 15.0)
            g2 = max(0.05, q2 / 15.0)
            g3 = max(0.05, q3 / 7.0)

            # Formant shaping envelope across bins
            envelope = np.ones(129, dtype=np.float32) * 0.1
            envelope[10:30] = g1 * 2.0
            envelope[30:71] = g2 * 1.8
            envelope[71:122] = g3 * 1.5

            shaped_fft = fft_ex * envelope
            synth = np.fft.irfft(shaped_fft, n=256)[:n].astype(np.float32)
        else:
            # Unvoiced: pseudo-random noise shaped across 4 sub-bands
            qu1 = (word24 >> 14) & 0x0F
            qu2 = (word24 >> 10) & 0x0F
            qu3 = (word24 >> 5) & 0x1F
            qu4 = word24 & 0x1F

            noise = np.random.uniform(-1.0, 1.0, n).astype(np.float32)
            fft_noise = np.fft.rfft(noise, n=256)

            envelope = np.ones(129, dtype=np.float32)
            envelope[0:32] = max(0.05, qu1 / 15.0)
            envelope[32:64] = max(0.05, qu2 / 15.0)
            envelope[64:96] = max(0.05, qu3 / 31.0)
            envelope[96:128] = max(0.05, qu4 / 31.0)

            shaped_fft = fft_noise * envelope
            synth = np.fft.irfft(shaped_fft, n=256)[:n].astype(np.float32)

        # Scale to match target RMS
        synth_rms = float(np.sqrt(np.mean(synth**2)))
        if synth_rms > 1e-4:
            synth = synth * (target_rms / synth_rms)

        return synth, phase


def compress_speech(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convenience helper to compress raw 16-bit mono PCM into 1200 bps vocoder bitstream."""
    codec = VocoderCodec(sample_rate=sample_rate)
    return codec.compress(pcm_bytes)


def decompress_speech(vocoder_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convenience helper to decompress 1200 bps vocoder bitstream into raw 16-bit mono PCM."""
    codec = VocoderCodec(sample_rate=sample_rate)
    return codec.decompress(vocoder_bytes)
