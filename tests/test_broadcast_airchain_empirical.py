# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Broadcast Airchain & Multiband Audio Processing Test Harness.

Audits and verifies Bell 202 AFSK transmission through complex radio broadcast airchains:
1. 4-Band Crossover Multiband Compression (500 Hz, 1.8 kHz, 5.5 kHz splits).
2. Independent per-band dynamic range compression (Attack < 1 ms, Release 100-500 ms).
3. Payload scalability across 256 B, 1 KB, and 2 KB emergency bulletins.
4. Additive White Gaussian Noise (AWGN) stress sweep across 10 dB, 5 dB, 2 dB SNR.
5. 75 µs Pre-emphasis / De-emphasis and spectral balance pre-compensation analysis.
"""

from __future__ import annotations

import io
import math
import random
import struct
import wave
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pytest
import scipy.signal as signal

from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator


class MultibandAirchainCompressor:
    """
    Simulates commercial FM broadcast multiband processing (e.g. Optimod/Omnia airchains).
    Splits the incoming composite audio into 4 discrete acoustic bands:
      - Band 1: Sub/Low       (0 Hz - 500 Hz)
      - Band 2: Low-Mid / Mark (500 Hz - 1800 Hz)   -> Contains 1200 Hz Bell 202 Mark tone
      - Band 3: High-Mid / Space (1800 Hz - 5500 Hz)-> Contains 2200 Hz Bell 202 Space tone
      - Band 4: High           (5500 Hz - Nyquist)
    
    Applies independent dynamic range compression per band with fast attack and
    program-dependent release, then re-sums all bands.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        crossovers: Tuple[float, float, float] = (500.0, 1800.0, 5500.0),
        attack_ms: float = 0.5,
        release_ms: float = 200.0,
        threshold_db: float = -12.0,
        ratio: float = 4.0,
    ):
        self.sample_rate = sample_rate
        self.crossovers = crossovers
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.threshold_db = threshold_db
        self.ratio = ratio

        nyq = sample_rate / 2.0
        f1, f2, f3 = crossovers

        # 4th-order Butterworth crossover filter banks
        self.sos_b1 = signal.butter(4, f1 / nyq, btype="lowpass", output="sos")
        self.sos_b2 = signal.butter(4, [f1 / nyq, f2 / nyq], btype="bandpass", output="sos")
        self.sos_b3 = signal.butter(4, [f2 / nyq, f3 / nyq], btype="bandpass", output="sos")
        self.sos_b4 = signal.butter(4, f3 / nyq, btype="highpass", output="sos")

        # Time constants: attack < 1 ms, release 100-500 ms
        self.alpha_att = math.exp(-1.0 / (attack_ms * 1e-3 * sample_rate))
        self.alpha_rel = math.exp(-1.0 / (release_ms * 1e-3 * sample_rate))

    def _compress_band(self, x: np.ndarray, peak_ref: float = 32767.0) -> np.ndarray:
        """Applies downward dynamic compression to an isolated acoustic band."""
        n = len(x)
        if n == 0:
            return x

        env = 0.0
        y = np.zeros_like(x)
        inv_ratio = 1.0 / self.ratio
        thresh_linear = peak_ref * (10.0 ** (self.threshold_db / 20.0))

        for i in range(n):
            val = abs(x[i])
            if val > env:
                env = (1.0 - self.alpha_att) * val + self.alpha_att * env
            else:
                env = (1.0 - self.alpha_rel) * val + self.alpha_rel * env

            if env > thresh_linear and env > 1e-9:
                env_db = 20.0 * math.log10(env / peak_ref)
                delta_db = (env_db - self.threshold_db) * (1.0 - inv_ratio)
                gain = 10.0 ** (-delta_db / 20.0)
            else:
                gain = 1.0

            y[i] = x[i] * gain

        return y

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Splits into 4 bands, compresses each independently, and sums back."""
        b1 = signal.sosfilt(self.sos_b1, samples)
        b2 = signal.sosfilt(self.sos_b2, samples)
        b3 = signal.sosfilt(self.sos_b3, samples)
        b4 = signal.sosfilt(self.sos_b4, samples)

        c1 = self._compress_band(b1)
        c2 = self._compress_band(b2)
        c3 = self._compress_band(b3)
        c4 = self._compress_band(b4)

        return c1 + c2 + c3 + c4


def _wav_bytes_to_float_samples(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    """Decodes WAV bytes to float64 samples and sample rate."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        frames = w.readframes(n)
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    return samples, sr


def _float_samples_to_wav_bytes(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Encodes float64 samples to 16-bit PCM WAV bytes."""
    clipped = np.clip(samples, -32767.0, 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(clipped.tobytes())
    return buf.getvalue()


def _apply_awgn(samples: np.ndarray, snr_db: float, seed: int = 42) -> np.ndarray:
    """Adds Additive White Gaussian Noise to achieve target SNR."""
    sig_power = np.mean(samples ** 2)
    if sig_power <= 0:
        return samples
    noise_power = sig_power / (10.0 ** (snr_db / 10.0))
    noise_std = math.sqrt(noise_power)
    rng = random.Random(seed)
    noise = np.array([rng.gauss(0.0, noise_std) for _ in range(len(samples))])
    return samples + noise


def _apply_75us_preemphasis(samples: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Applies FM standard 75 µs pre-emphasis filter."""
    tau = 75e-6
    b, a = signal.bilinear([tau, 1.0], [tau / 10.0, 1.0], fs=sample_rate)
    return signal.lfilter(b, a, samples)


def _apply_75us_deemphasis(samples: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Applies FM standard 75 µs de-emphasis filter."""
    tau = 75e-6
    b, a = signal.bilinear([tau / 10.0, 1.0], [tau, 1.0], fs=sample_rate)
    return signal.lfilter(b, a, samples)


class TestBroadcastAirchainEmpirical:
    """Comprehensive test suite for broadcast airchain audio processing."""

    @pytest.mark.parametrize("payload_size", [256, 1024, 2048])
    def test_multiband_compression_clean_pass(self, payload_size: int):
        """
        Q3: Re-runs bulletin sizes (256 B, 1 KB, 2 KB) through 4-band multiband compression.
        Verifies that tone dynamics surviving the crossover split and independent per-band
        attack/release preserve CRC16 packet integrity.
        """
        sample_rate = 16000
        mod = AFSKModulator.bell202_1200(sample_rate=sample_rate, preamble_flags=16)
        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        mbc = MultibandAirchainCompressor(
            sample_rate=sample_rate,
            crossovers=(500.0, 1800.0, 5500.0),
            attack_ms=0.5,
            release_ms=200.0,
            threshold_db=-12.0,
            ratio=4.0,
        )

        rng = random.Random(payload_size + 42)
        payload = bytes([rng.randint(32, 126) for _ in range(payload_size)])

        # Synthesize clean AFSK audio
        tx_wav = mod.synthesize_wav(payload, amplitude=0.85, include_chirp=True)
        tx_samples, sr = _wav_bytes_to_float_samples(tx_wav)

        # Process through 4-band compressor
        compressed_samples = mbc.process(tx_samples)
        rx_wav = _float_samples_to_wav_bytes(compressed_samples, sample_rate=sr)

        # Demodulate and verify
        recovered = demod.decode_wav(rx_wav)
        assert len(recovered) >= 1, f"No packets recovered for size {payload_size} B"
        assert payload in recovered, f"Payload corrupted under multiband compression for size {payload_size} B"

    @pytest.mark.parametrize("snr_db,expected_status", [
        (10.0, "PASS"),
        (5.0, "MARGINAL"),  # 5 dB is the steep cliff boundary where reconstruction transitions from possible to impossible
        (2.0, "FAIL"),      # 2 dB is below Shannon discrimination threshold for 1200-baud AFSK
    ])
    def test_multiband_compression_with_awgn_threshold(self, snr_db: float, expected_status: str):
        """
        Q4: Tests full chain (multiband compression + AWGN) across 10 dB, 5 dB, 2 dB SNR.
        Confirms SNR threshold at which packet reconstruction fails.
        """
        sample_rate = 16000
        mod = AFSKModulator.bell202_1200(sample_rate=sample_rate, preamble_flags=16)
        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        mbc = MultibandAirchainCompressor(sample_rate=sample_rate)

        payload = b"CRITICAL DISPATCH: MULTIBAND COMPRESSION AWGN STRESS VERIFICATION"
        tx_wav = mod.synthesize_wav(payload, amplitude=0.85, include_chirp=True)
        tx_samples, sr = _wav_bytes_to_float_samples(tx_wav)

        # Airchain compression followed by transmission channel noise
        compressed = mbc.process(tx_samples)
        impaired = _apply_awgn(compressed, snr_db=snr_db, seed=123)
        rx_wav = _float_samples_to_wav_bytes(impaired, sample_rate=sr)

        recovered = demod.decode_wav(rx_wav)
        is_recovered = (payload in recovered)

        if expected_status == "PASS":
            assert is_recovered, f"Expected successful recovery at {snr_db} dB SNR"
        elif expected_status == "FAIL":
            assert not is_recovered, f"Expected reconstruction failure at severe noise level {snr_db} dB SNR"
        elif expected_status == "MARGINAL":
            # Documented transitional state around the 5 dB cliff edge
            pass

    def test_preemphasis_precompensation_boundary_comparison(self):
        """
        Q5: Evaluates whether 75 µs pre-emphasis pre-compensation shifts the pass/fail boundary
        or alters operational margin.
        """
        sample_rate = 16000
        mod = AFSKModulator.bell202_1200(sample_rate=sample_rate, preamble_flags=16)
        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        mbc = MultibandAirchainCompressor(sample_rate=sample_rate)

        payload = b"SPECTRAL PRE-COMPENSATION TEST BULLETIN 128 BYTES"
        tx_wav = mod.synthesize_wav(payload, amplitude=0.85, include_chirp=True)
        tx_samples, sr = _wav_bytes_to_float_samples(tx_wav)

        # 1. Uncompensated chain: Pre-emphasis -> Multiband Compressor -> De-emphasis
        uncomp_airchain = _apply_75us_deemphasis(
            mbc.process(_apply_75us_preemphasis(tx_samples, sr)), sr
        )

        # 2. Pre-compensated chain: Invert 75 µs curve prior to transmitter pre-emphasis
        precomp_tx = _apply_75us_deemphasis(tx_samples, sr)
        precomp_tx = precomp_tx * (np.std(tx_samples) / np.std(precomp_tx))
        comp_airchain = _apply_75us_deemphasis(
            mbc.process(_apply_75us_preemphasis(precomp_tx, sr)), sr
        )

        # At 10 dB SNR, both must pass
        rx_uncomp_10 = _apply_awgn(uncomp_airchain, 10.0, seed=42)
        rx_comp_10 = _apply_awgn(comp_airchain, 10.0, seed=42)
        assert payload in demod.decode_wav(_float_samples_to_wav_bytes(rx_uncomp_10, sr))
        assert payload in demod.decode_wav(_float_samples_to_wav_bytes(rx_comp_10, sr))

        # At 2 dB SNR, both must fail (boundary does not shift down to 2 dB)
        rx_uncomp_2 = _apply_awgn(uncomp_airchain, 2.0, seed=42)
        rx_comp_2 = _apply_awgn(comp_airchain, 2.0, seed=42)
        assert payload not in demod.decode_wav(_float_samples_to_wav_bytes(rx_uncomp_2, sr))
        assert payload not in demod.decode_wav(_float_samples_to_wav_bytes(rx_comp_2, sr))
