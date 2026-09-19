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

from .afsk_modulator import crc16_ccitt


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

        self.goertzel_mark = GoertzelDetector(mark_freq, sample_rate, self.block_size)
        self.goertzel_space = GoertzelDetector(space_freq, sample_rate, self.block_size)

    def decode_wav(self, wav_bytes: bytes) -> list[bytes]:
        """Reads a WAV file buffer and extracts all valid packets."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as w:
            sr = w.getframerate()
            n_channels = w.getnchannels()
            _samp_width = w.getsampwidth()
            n_frames = w.getnframes()
            raw_frames = w.readframes(n_frames)

        if sr != self.sample_rate:
            # Adjust sample rate detectors if necessary
            self.sample_rate = sr
            self.samples_per_bit = sr / self.baud_rate
            self.block_size = round(self.samples_per_bit)
            self.goertzel_mark = GoertzelDetector(self.mark_freq, sr, self.block_size)
            self.goertzel_space = GoertzelDetector(self.space_freq, sr, self.block_size)

        # Unpack 16-bit mono or stereo samples (taking left channel if stereo)
        samples = []
        fmt = "<" + ("h" * (n_frames * n_channels))
        all_samples = struct.unpack(fmt, raw_frames)
        for i in range(0, len(all_samples), n_channels):
            samples.append(float(all_samples[i]))

        return self.demodulate_samples(samples)

    def demodulate_samples(self, samples: list[float]) -> list[bytes]:
        """
        Processes normalized floating-point samples through exact quadrature
        correlation, scans sub-symbol phase offsets, and extracts CRC-verified packets.
        """
        step = self.samples_per_bit
        n_samples = len(samples)
        step_int = max(1, round(step))
        dt = 1.0 / self.sample_rate
        two_pi = 2.0 * math.pi
        w_mark = two_pi * self.mark_freq
        w_space = two_pi * self.space_freq

        packets: list[bytes] = []

        # Search across sub-symbol sample phase offsets to lock clock
        for offset in range(step_int):
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

                if 0 < length <= 4096 and idx + length + 2 <= n_bytes:
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
