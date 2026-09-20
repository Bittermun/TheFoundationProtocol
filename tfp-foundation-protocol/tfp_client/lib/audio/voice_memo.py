# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Voice Memo ("Audio-Pocket") Protocol & Container.

Packages ultra-low-bitrate 8 kHz acoustic voice messages into compact binary bundles
for transmission over walkie-talkies, VHF radio, APRS/Bell 202 acoustic tones,
and rateless fountain broadcast mesh networks.
"""

from dataclasses import dataclass
import io
import struct
import time
from typing import Optional, Tuple
import wave

from .afsk_modulator import crc16_ccitt
from .vocoder import VOCODER_MAGIC, compress_speech, decompress_speech

VOICE_MEMO_MAGIC = b"VM"
VOICE_MEMO_VERSION = 1
FLAG_16BIT = 0x01
FLAG_VOCODER = 0x02

# Header format: [MAGIC: 2s] [VERSION: B] [FLAGS: B] [SAMPLE_RATE: H] [DURATION_MS: H] [CALLSIGN: 8s] [TIMESTAMP: I] [PAYLOAD_LEN: I]
HEADER_FORMAT = ">2sBBHH8sII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class VoiceMemo:
    """
    Compact voice note container tailored for rural health workers,
    field responders, and air-gapped emergency mesh communication.
    """

    callsign: str
    sample_rate: int
    pcm_data: bytes
    is_16bit: bool = True
    timestamp: Optional[int] = None
    duration_ms: Optional[int] = None
    is_vocoder: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = int(time.time())

        if self.duration_ms is None:
            if self.is_vocoder:
                if len(self.pcm_data) >= 4:
                    n_frames = (len(self.pcm_data) - 4) // 3
                    self.duration_ms = max(0, n_frames * 20)
                else:
                    self.duration_ms = 0
            else:
                bytes_per_sample = 2 if self.is_16bit else 1
                denom = max(1, self.sample_rate * bytes_per_sample)
                calculated_duration = int((len(self.pcm_data) / denom) * 1000)
                self.duration_ms = calculated_duration

    def to_bytes(self) -> bytes:
        """
        Serializes VoiceMemo to authenticated binary network wire format with CRC16.
        """
        flags = 0
        if self.is_16bit:
            flags |= FLAG_16BIT
        if self.is_vocoder:
            flags |= FLAG_VOCODER

        callsign_bytes = self.callsign.encode("ascii", errors="replace")[:8].ljust(8, b" ")
        payload = self.pcm_data
        if self.is_vocoder and not payload.startswith(VOCODER_MAGIC):
            payload = compress_speech(payload, self.sample_rate)

        payload_len = len(payload)
        header = struct.pack(
            HEADER_FORMAT,
            VOICE_MEMO_MAGIC,
            VOICE_MEMO_VERSION,
            flags,
            self.sample_rate,
            min(65535, self.duration_ms or 0),
            callsign_bytes,
            self.timestamp,
            payload_len,
        )

        body = header + payload
        crc = crc16_ccitt(body)
        return body + struct.pack(">H", crc)

    @classmethod
    def from_bytes(cls, data: bytes, auto_decompress: bool = False) -> "VoiceMemo":
        """
        Deserializes binary wire format and verifies CRC16 checksum.
        """
        if len(data) < HEADER_SIZE + 2:
            raise ValueError(f"Data too short for VoiceMemo: {len(data)} < {HEADER_SIZE + 2}")

        # Check CRC16
        body = data[:-2]
        expected_crc = (data[-2] << 8) | data[-1]
        actual_crc = crc16_ccitt(body)
        if actual_crc != expected_crc:
            raise ValueError(f"VoiceMemo CRC16 checksum mismatch: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}")

        (
            magic,
            version,
            flags,
            sample_rate,
            duration_ms,
            callsign_bytes,
            timestamp,
            payload_len,
        ) = struct.unpack_from(HEADER_FORMAT, body, 0)

        if magic != VOICE_MEMO_MAGIC:
            raise ValueError(f"Invalid VoiceMemo magic: {magic!r}")
        if version != VOICE_MEMO_VERSION:
            raise ValueError(f"Unsupported VoiceMemo version: {version}")

        payload = body[HEADER_SIZE : HEADER_SIZE + payload_len]
        if len(payload) != payload_len:
            raise ValueError(f"VoiceMemo payload truncated: expected {payload_len}, got {len(payload)}")

        callsign = callsign_bytes.decode("ascii", errors="replace").strip()
        is_16bit = bool(flags & FLAG_16BIT)
        is_vocoder = bool(flags & FLAG_VOCODER)

        if is_vocoder and auto_decompress:
            decompressed = decompress_speech(payload, sample_rate)
            return cls(
                callsign=callsign,
                sample_rate=sample_rate,
                pcm_data=decompressed,
                is_16bit=True,
                timestamp=timestamp,
                duration_ms=duration_ms,
                is_vocoder=False,
            )

        return cls(
            callsign=callsign,
            sample_rate=sample_rate,
            pcm_data=payload,
            is_16bit=is_16bit,
            timestamp=timestamp,
            duration_ms=duration_ms,
            is_vocoder=is_vocoder,
        )

    def compress(self) -> "VoiceMemo":
        """Returns a new VoiceMemo compressed with the 1200 bps vocoder."""
        if self.is_vocoder:
            return self
        vocoder_bytes = compress_speech(self.pcm_data, self.sample_rate)
        return VoiceMemo(
            callsign=self.callsign,
            sample_rate=self.sample_rate,
            pcm_data=vocoder_bytes,
            is_16bit=True,
            timestamp=self.timestamp,
            duration_ms=self.duration_ms,
            is_vocoder=True,
        )

    def decompress(self) -> "VoiceMemo":
        """Returns a new VoiceMemo decompressed into 16-bit PCM."""
        if not self.is_vocoder:
            return self
        raw_pcm = decompress_speech(self.pcm_data, self.sample_rate)
        return VoiceMemo(
            callsign=self.callsign,
            sample_rate=self.sample_rate,
            pcm_data=raw_pcm,
            is_16bit=True,
            timestamp=self.timestamp,
            duration_ms=self.duration_ms,
            is_vocoder=False,
        )

    def to_wav(self) -> bytes:
        """Converts internal PCM samples to standard playable 16-bit mono WAV audio."""
        raw = self.pcm_data
        if self.is_vocoder:
            raw = decompress_speech(raw, self.sample_rate)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2 if self.is_16bit else 1)
            w.setframerate(self.sample_rate)
            w.writeframes(raw)
        return buf.getvalue()

    @classmethod
    def from_wav(cls, wav_bytes: bytes, callsign: str = "TFP_NODE", compress_vocoder: bool = False) -> "VoiceMemo":
        """Constructs a VoiceMemo from standard WAV bytes, optionally compressing via vocoder."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as w:
            sample_rate = w.getframerate()
            sampwidth = w.getsampwidth()
            n_frames = w.getnframes()
            raw_frames = w.readframes(n_frames)

        is_16bit = (sampwidth == 2)
        memo = cls(
            callsign=callsign,
            sample_rate=sample_rate,
            pcm_data=raw_frames,
            is_16bit=is_16bit,
        )
        if compress_vocoder:
            return memo.compress()
        return memo

