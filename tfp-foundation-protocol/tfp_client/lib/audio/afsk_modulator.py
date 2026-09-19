# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Audio Frequency Shift Keying (AFSK) Modulator.

Implements continuous-phase Bell 202 AFSK audio modulation (1200 Hz mark,
2200 Hz space, 1200/300 baud) for broadcasting Foundation Protocol packets
over standard analog FM radio transmitters, classroom PA speakers,
walkie-talkies, and acoustic air-gap audio to ordinary smartphones.
"""

import io
import math
import struct
import wave
from typing import List, Optional, Union


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """Standard CRC16-CCITT polynomial (0x1021)."""
    crc = initial
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


SYNC_FLAG = 0x7E     # HDLC Framing sync byte (01111110)


class AFSKModulator:
    """
    Continuous-Phase Audio Frequency Shift Keying (CPFSK) Modulator.
    Generates 16-bit PCM WAV audio for acoustic and FM radio transmission.
    """

    # Bell 202 Audio Standard Frequencies (Hz)
    MARK_FREQ = 1200.0   # Binary 1
    SPACE_FREQ = 2200.0  # Binary 0

    SYNC_FLAG = SYNC_FLAG

    def __init__(
        self,
        sample_rate: int = 16000,
        baud_rate: int = 1200,
        mark_freq: float = 1200.0,
        space_freq: float = 2200.0,
        preamble_flags: int = 16,
    ):
        self.sample_rate = sample_rate
        self.baud_rate = baud_rate
        self.mark_freq = mark_freq
        self.space_freq = space_freq
        self.preamble_flags = preamble_flags
        self.samples_per_bit = sample_rate / baud_rate

    def frame_packet(self, payload: bytes) -> bytes:
        """
        Frames binary payload with preamble, length header, and CRC16.
        Wire layout: [PREAMBLE FLAGS] [LENGTH: 2B] [PAYLOAD] [CRC16: 2B] [POSTAMBLE]
        """
        if len(payload) > 65535:
            raise ValueError(f"Payload size {len(payload)} exceeds 16-bit max (65535 bytes)")

        crc = crc16_ccitt(payload)
        length_bytes = struct.pack(">H", len(payload))
        crc_bytes = struct.pack(">H", crc)

        preamble = bytes([self.SYNC_FLAG] * self.preamble_flags)
        postamble = bytes([self.SYNC_FLAG] * 4)

        return preamble + length_bytes + payload + crc_bytes + postamble

    def modulate_bits(self, bits: List[int], amplitude: float = 0.8) -> bytes:
        """
        Synthesizes Continuous-Phase FSK 16-bit PCM mono audio samples.
        Preserves phase across bit boundaries to eliminate high-frequency clicks.
        Uses exact sample index endpoints to prevent cumulative clock drift.
        """
        phase = 0.0
        max_amp = int(32767 * max(0.1, min(1.0, amplitude)))
        two_pi = 2.0 * math.pi
        delta_t = 1.0 / self.sample_rate

        frames = bytearray()
        for bit_idx, bit in enumerate(bits):
            freq = self.mark_freq if bit == 1 else self.space_freq
            angular_freq = two_pi * freq
            start_sample = int(round(bit_idx * self.samples_per_bit))
            end_sample = int(round((bit_idx + 1) * self.samples_per_bit))
            n_samples = end_sample - start_sample

            for _ in range(n_samples):
                sample_val = int(max_amp * math.sin(phase))
                frames.extend(struct.pack("<h", sample_val))
                phase += angular_freq * delta_t
                if phase >= two_pi:
                    phase -= two_pi

        return bytes(frames)

    def modulate_bytes(self, data: bytes, amplitude: float = 0.8) -> bytes:
        """Converts bytes to LSB-first bit stream and modulates to PCM frames."""
        bits = []
        for byte in data:
            for i in range(8):
                # Standard LSB-first transmission
                bits.append((byte >> i) & 1)
        return self.modulate_bits(bits, amplitude=amplitude)

    def synthesize_wav(self, payload: bytes, amplitude: float = 0.8) -> bytes:
        """
        Convenience method: frames packet and encodes into a valid PCM WAV buffer.
        """
        framed_data = self.frame_packet(payload)
        pcm_samples = self.modulate_bytes(framed_data, amplitude=amplitude)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)        # Mono
            w.setsampwidth(2)        # 16-bit (2 bytes per sample)
            w.setframerate(self.sample_rate)
            w.writeframes(pcm_samples)

        return buf.getvalue()
