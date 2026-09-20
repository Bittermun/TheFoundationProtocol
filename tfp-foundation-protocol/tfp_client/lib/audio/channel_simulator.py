# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acoustic Airgap & Radio Multipath Channel Simulator.

Simulates harsh real-world audio physical propagation environments:
1. Multipath room reverberation / reflections (delayed attenuated echo).
2. Additive White Gaussian Noise (AWGN) at configurable SNR.
3. Microphone overdriving and non-linear saturation clipping.
4. Distance-based signal attenuation.
"""

import io
import math
import random
import struct
from typing import List, Tuple
import wave


class AcousticChannelSimulator:
    """
    Applies physical audio channel impairments to 16-bit PCM WAV audio.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def apply_multipath_reverberation(
        self,
        samples: List[float],
        sample_rate: int,
        reflections: List[Tuple[float, float]] = None,
    ) -> List[float]:
        """
        Simulates room acoustic echo.
        reflections: List of (delay_seconds, attenuation_factor)
        Default: 20ms at 0.35 amp, 45ms at 0.18 amp, 80ms at 0.08 amp.
        """
        if reflections is None:
            reflections = [
                (0.020, 0.35),
                (0.045, 0.18),
                (0.080, 0.08),
            ]

        n = len(samples)
        out = list(samples)

        for delay_s, gain in reflections:
            delay_samples = int(delay_s * sample_rate)
            if delay_samples < n:
                for i in range(delay_samples, n):
                    out[i] += gain * samples[i - delay_samples]

        return out

    def apply_awgn_noise(
        self,
        samples: List[float],
        snr_db: float = 20.0,
    ) -> List[float]:
        """
        Adds Additive White Gaussian Noise (AWGN) to achieve target SNR (dB).
        """
        if not samples:
            return []

        signal_power = sum(s * s for s in samples) / len(samples)
        if signal_power <= 0.0:
            return list(samples)

        # SNR = 10 * log10(P_signal / P_noise) => P_noise = P_signal / 10^(SNR/10)
        noise_power = signal_power / (10.0 ** (snr_db / 10.0))
        noise_std = math.sqrt(noise_power)

        out = []
        for s in samples:
            noise = self.rng.gauss(0.0, noise_std)
            out.append(s + noise)

        return out

    def apply_clipping(
        self,
        samples: List[float],
        max_amplitude: float = 30000.0,
    ) -> List[float]:
        """
        Simulates microphone overdrive / saturation clipping.
        """
        return [max(-max_amplitude, min(max_amplitude, s)) for s in samples]

    def apply_attenuation(
        self,
        samples: List[float],
        factor: float = 0.20,
    ) -> List[float]:
        """
        Simulates distance-based acoustic attenuation (-14 dB at 0.20 factor).
        """
        return [s * factor for s in samples]

    def impair_wav(
        self,
        wav_bytes: bytes,
        attenuation: float = 0.50,
        snr_db: float = 25.0,
        reverberation: bool = True,
        clipping: bool = False,
    ) -> bytes:
        """
        Reads input 16-bit PCM WAV, applies specified acoustic impairments,
        and returns the degraded WAV byte buffer.
        """
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as w:
            n_channels = w.getnchannels()
            samp_width = w.getsampwidth()
            sample_rate = w.getframerate()
            n_frames = w.getnframes()
            raw_frames = w.readframes(n_frames)

        if samp_width != 2:
            raise ValueError(f"Only 16-bit PCM WAV supported (got {samp_width * 8}-bit)")

        all_samples = struct.unpack(f"<{n_frames * n_channels}h", raw_frames)
        samples = [float(all_samples[i]) for i in range(0, len(all_samples), n_channels)]

        # 1. Attenuation
        if attenuation < 1.0:
            samples = self.apply_attenuation(samples, factor=attenuation)

        # 2. Multipath Room Echo
        if reverberation:
            samples = self.apply_multipath_reverberation(samples, sample_rate)

        # 3. Additive Noise
        if snr_db < 100.0:
            samples = self.apply_awgn_noise(samples, snr_db=snr_db)

        # 4. Clipping
        if clipping:
            samples = self.apply_clipping(samples, max_amplitude=20000.0)

        # Re-quantize to 16-bit integers
        out_frames = bytearray()
        for s in samples:
            clamped = int(max(-32768, min(32767, round(s))))
            out_frames.extend(struct.pack("<h", clamped))

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(out_frames)

        return out_buf.getvalue()
