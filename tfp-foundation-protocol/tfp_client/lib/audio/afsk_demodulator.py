# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Audio Frequency Shift Keying (AFSK) Demodulator.

Implements robust dual-tone Goertzel discrimination and bit-slicing
to decode Bell 202 AFSK audio (1200 Hz / 2200 Hz) into verified
Foundation Protocol packets from analog radio recordings or microphone audio.
"""

import io
import math
import struct
import wave

from .afsk_modulator import MAX_AFSK_PAYLOAD_SIZE, crc16_ccitt


class GoertzelDetector:
    """Computes spectral energy at a target frequency using Goertzel's algorithm."""

    def __init__(self, target_freq: float, sample_rate: int, block_size: int):
        self.target_freq = target_freq
        self.sample_rate = sample_rate
        self.block_size = block_size
        k = int(0.5 + (block_size * target_freq / sample_rate))
        omega = (2.0 * math.pi * k) / block_size
        self.coeff = 2.0 * math.cos(omega)

    def compute_energy(self, samples: list[float]) -> float:
        s_prev = 0.0
        s_prev2 = 0.0
        for x in samples:
            s = x + self.coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        power = s_prev2 * s_prev2 + s_prev * s_prev - self.coeff * s_prev * s_prev2
        return max(0.0, power)


class AFSKDemodulator:
    """
    Demodulates 16-bit PCM audio samples into verified packet payloads.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        baud_rate: int = 1200,
        mark_freq: float = 1200.0,
        space_freq: float = 2200.0,
    ):
        self.sample_rate = sample_rate
        self.baud_rate = baud_rate
        self.mark_freq = mark_freq
        self.space_freq = space_freq
        self.samples_per_bit = sample_rate / baud_rate
        self.block_size = round(self.samples_per_bit)

    @classmethod
    def bell202_1200(cls, sample_rate: int = 16000) -> "AFSKDemodulator":
        """Standard Bell 202: 1200 baud, 1200 Hz mark / 2200 Hz space."""
        return cls(sample_rate=sample_rate, baud_rate=1200, mark_freq=1200.0, space_freq=2200.0)

    @classmethod
    def bell202_300(cls, sample_rate: int = 16000) -> "AFSKDemodulator":
        """Bell 202 Robust Acoustic Fallback: 300 baud, 1200 Hz mark / 2200 Hz space."""
        return cls(sample_rate=sample_rate, baud_rate=300, mark_freq=1200.0, space_freq=2200.0)

    @classmethod
    def bell103_300(cls, sample_rate: int = 16000) -> "AFSKDemodulator":
        """Standard Bell 103: 300 baud, 1270 Hz mark / 1070 Hz space."""
        return cls(sample_rate=sample_rate, baud_rate=300, mark_freq=1270.0, space_freq=1070.0)

    def decode_wav(self, wav_bytes: bytes, fallback_300: bool = False) -> list[bytes]:
        """Reads a WAV file buffer and extracts all valid packets, optionally falling back to 300 baud."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as w:
            sr = w.getframerate()
            n_channels = w.getnchannels()
            _samp_width = w.getsampwidth()
            n_frames = w.getnframes()
            raw_frames = w.readframes(n_frames)

        if sr != self.sample_rate:
            # Adjust sample rate configuration
            self.sample_rate = sr
            self.samples_per_bit = sr / self.baud_rate
            self.block_size = round(self.samples_per_bit)

        # Unpack 16-bit mono or stereo samples (taking left channel if stereo)
        samples = []
        fmt = "<" + ("h" * (n_frames * n_channels))
        all_samples = struct.unpack(fmt, raw_frames)
        for i in range(0, len(all_samples), n_channels):
            samples.append(float(all_samples[i]))

        packets = self.demodulate_samples(samples)
        if not packets and fallback_300 and self.baud_rate != 300:
            # Attempt acoustic fallback at 300 baud
            fallback_demod = AFSKDemodulator(
                sample_rate=self.sample_rate,
                baud_rate=300,
                mark_freq=self.mark_freq,
                space_freq=self.space_freq,
            )
            packets = fallback_demod.demodulate_samples(samples)

        return packets

    def demodulate_samples(self, samples: list[float]) -> list[bytes]:
        """
        Processes normalized floating-point samples through exact quadrature
        correlation, scans sub-symbol phase offsets, and extracts CRC-verified packets.
        Applies Automatic Gain Control (AGC) to tolerate quiet/attenuated acoustic recordings.
        """
        if not samples:
            return []

        # Automatic Gain Control (AGC): normalize peak amplitude to target ~16000.0 (half-scale)
        max_abs = max(abs(x) for x in samples)
        if max_abs > 20.0:  # Only normalize if signal exceeds noise floor
            scale = 16000.0 / max_abs
            samples = [x * scale for x in samples]

        n_samples = len(samples)
        dt = 1.0 / self.sample_rate
        two_pi = 2.0 * math.pi
        w_mark = two_pi * self.mark_freq
        w_space = two_pi * self.space_freq

        packets: list[bytes] = []

        # Search across nominal baud rate first, then clock drift factors (±1.5%, ±3%)
        drift_factors = [0.0, -0.015, 0.015, -0.03, 0.03]
        for drift in drift_factors:
            step = self.samples_per_bit * (1.0 + drift)
            step_int = max(1, round(step))
            stride = max(1, step_int // 16)
            for offset in range(0, step_int, stride):
                total_bits = int((n_samples - offset) // step)
                if total_bits < 32:
                    continue

                bits = []
                for i in range(total_bits):
                    start = offset + round(i * step)
                    end = offset + round((i + 1) * step)
                    chunk = samples[start:end]
                    if len(chunk) < 2:
                        continue

                    # Quadrature product correlation at mark and space frequencies
                    i_m = sum(x * math.cos(w_mark * (start + j) * dt) for j, x in enumerate(chunk))
                    q_m = sum(x * math.sin(w_mark * (start + j) * dt) for j, x in enumerate(chunk))
                    e_m = i_m * i_m + q_m * q_m

                    i_s = sum(x * math.cos(w_space * (start + j) * dt) for j, x in enumerate(chunk))
                    q_s = sum(x * math.sin(w_space * (start + j) * dt) for j, x in enumerate(chunk))
                    e_s = i_s * i_s + q_s * q_s

                    bits.append(1 if e_m >= e_s else 0)

                found = self._extract_packets_from_bits(bits)
                for pkt in found:
                    if pkt not in packets:
                        packets.append(pkt)
                if packets:
                    break
            if packets:
                break

        return packets

    def _extract_packets_from_bits(self, bits: list[int]) -> list[bytes]:
        """Reconstructs bytes from bitstream and parses packets."""
        packets: list[bytes] = []
        n_bits = len(bits)
        if n_bits < 40:
            return packets

        # Group into bytes at different phase offsets (0..7) to guarantee sync
        for offset in range(8):
            extracted = self._scan_bytes_at_offset(bits[offset:])
            for pkt in extracted:
                if pkt not in packets:
                    packets.append(pkt)

        return packets

    def _scan_bytes_at_offset(self, bits: list[int]) -> list[bytes]:
        raw_bytes = bytearray()
        n_full_bytes = len(bits) // 8
        for i in range(n_full_bytes):
            byte_val = 0
            for bit_idx in range(8):
                byte_val |= (bits[i * 8 + bit_idx] << bit_idx)
            raw_bytes.append(byte_val)

        packets = []
        idx = 0
        n_bytes = len(raw_bytes)

        while idx < n_bytes - 6:
            # Look for sync flag 0x7E
            if raw_bytes[idx] == 0x7E:
                # Advance past consecutive sync flags
                while idx < n_bytes and raw_bytes[idx] == 0x7E:
                    idx += 1

                if idx + 4 >= n_bytes:
                    break

                # Read 2-byte length
                length = (raw_bytes[idx] << 8) | raw_bytes[idx + 1]
                idx += 2

                if 0 < length <= MAX_AFSK_PAYLOAD_SIZE and idx + length + 2 <= n_bytes:
                    payload = bytes(raw_bytes[idx : idx + length])
                    idx += length
                    expected_crc = (raw_bytes[idx] << 8) | raw_bytes[idx + 1]
                    idx += 2

                    if crc16_ccitt(payload) == expected_crc:
                        packets.append(payload)
                else:
                    idx += 1
            else:
                idx += 1

        return packets
