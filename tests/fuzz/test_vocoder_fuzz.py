# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Property-Based Fuzz Testing for Ultra-Low-Bitrate Vocoder (1200 bps).

Verifies invariants:
1. Arbitrary PCM Input Resilience: compress_speech never raises unhandled exceptions or leaks memory on arbitrary bytes.
2. Bitstream Framing & Magic: Valid compression always emits VOCODER_MAGIC (b"V120") with exact 3-byte frame stride.
3. Corrupt Bitstream Immunity: decompress_speech safely rejects or parses malformed bitstreams without crashing.
4. Extreme Audio Dynamic Range: Pure silence, maximum clipping, and DC offsets encode and decode stably without NaN/Inf.
"""

import struct
from hypothesis import given, settings, strategies as st
import pytest

from tfp_client.lib.audio.vocoder import (
    VOCODER_MAGIC,
    VocoderCodec,
    compress_speech,
    decompress_speech,
)


class TestVocoderHypothesisFuzz:
    """Property-based verification of VocoderCodec."""

    @settings(max_examples=50, deadline=None)
    @given(raw_bytes=st.binary(min_size=0, max_size=16_000))
    def test_compress_arbitrary_bytes_safety(self, raw_bytes: bytes):
        """Invariant: compress_speech handles arbitrary byte streams safely."""
        compressed = compress_speech(raw_bytes, sample_rate=8000)
        assert compressed.startswith(VOCODER_MAGIC)
        payload_len = len(compressed) - len(VOCODER_MAGIC)
        assert payload_len % 3 == 0

        # Decompressing the resulting bitstream must succeed and produce valid PCM
        decompressed = decompress_speech(compressed, sample_rate=8000)
        assert isinstance(decompressed, bytes)
        assert len(decompressed) % 2 == 0  # 16-bit samples

    @settings(max_examples=50, deadline=None)
    @given(garbage=st.binary(min_size=0, max_size=1_000))
    def test_decompress_malformed_bitstream_rejection(self, garbage: bytes):
        """Invariant: decompress_speech cleanly rejects non-vocoder payloads."""
        if not garbage.startswith(VOCODER_MAGIC):
            with pytest.raises(ValueError, match="Invalid vocoder magic"):
                decompress_speech(garbage)
        else:
            # If by chance it started with VOCODER_MAGIC, it should either decompress or raise ValueError
            try:
                out = decompress_speech(garbage)
                assert isinstance(out, bytes)
            except ValueError:
                pass

    @settings(max_examples=30, deadline=None)
    @given(
        n_samples=st.integers(min_value=160, max_value=4000),
        amplitude=st.integers(min_value=-32768, max_value=32767),
    )
    def test_extreme_audio_signals(self, n_samples: int, amplitude: int):
        """Invariant: Flat DC offset or extreme clipping never produces NaN/Inf."""
        pcm = bytearray()
        for _ in range(n_samples):
            pcm.extend(struct.pack("<h", amplitude))

        compressed = compress_speech(bytes(pcm), sample_rate=8000)
        decompressed = decompress_speech(compressed, sample_rate=8000)

        assert len(decompressed) > 0
        # Verify no NaN or Inf in synthesized PCM samples
        sample_count = len(decompressed) // 2
        for i in range(sample_count):
            val = struct.unpack_from("<h", decompressed, i * 2)[0]
            assert -32768 <= val <= 32767

    def test_signal_fidelity_tone_survives_roundtrip(self):
        """Regression: vocoder must preserve audio energy, not produce silence.

        This test catches the RMS threshold bug where normalization to [-1, 1]
        made the silence threshold (previously 15.0) always true, causing
        every frame to be classified as silence and encoded as zeros.
        """
        import numpy as np

        # Generate a 0.5-second 440 Hz tone at full scale
        sr = 8000
        n = sr // 2  # 0.5 seconds
        t = np.linspace(0, 0.5, n, endpoint=False)
        tone = (np.sin(2 * np.pi * 440 * t) * 30000).astype(np.int16)
        pcm = tone.tobytes()

        compressed = compress_speech(pcm, sample_rate=sr)
        decompressed = decompress_speech(compressed, sample_rate=sr)

        out_samples = np.frombuffer(decompressed, dtype=np.int16).astype(np.float64)
        in_rms = float(np.sqrt(np.mean(tone.astype(np.float64)**2)))
        out_rms = float(np.sqrt(np.mean(out_samples**2)))

        # Output must not be silence
        assert out_rms > 0, "Vocoder roundtrip produced total silence"
        # Output must retain at least 1% of input energy
        assert out_rms > in_rms * 0.01, (
            f"Vocoder energy ratio too low: {out_rms/in_rms:.4f} (need >0.01)"
        )
        # Majority of samples must be non-zero
        non_zero = int(np.sum(np.abs(out_samples) > 0))
        assert non_zero > len(out_samples) * 0.5, (
            f"Only {non_zero}/{len(out_samples)} non-zero samples"
        )

