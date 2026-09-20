# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Trustworthy Acoustic Physical Channel Verification.

Verifies:
1. Silence Rejection: Pure silence produces exactly 0 packets (no hallucinated frames).
2. Ambient Noise Rejection: Gaussian white noise produces exactly 0 packets.
3. Corrupted Audio Rejection: Bitstream corruption triggers CRC16 drop with 0 false-positives.
4. Genuine Novel Bulletin Delivery: Real emergency text bulletin modulated to Bell 202 AFSK,
   passed through multipath room acoustics and noise, is recovered 100% bit-exact and persisted.
"""

from __future__ import annotations

import io
import math
import random
import struct
import wave
from pathlib import Path

import pytest

from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator, MAX_AFSK_PAYLOAD_SIZE
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator
from tfp_core_v4.node import TFPNode


def _synthesize_wav(samples: list[int], sample_rate: int = 16000) -> bytes:
    """Helper to pack int16 samples into a WAV byte stream."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        raw_pcm = struct.pack(f"<{len(samples)}h", *samples)
        w.writeframes(raw_pcm)
    return buf.getvalue()


class TestAcousticPhysicalChannelVerification:
    """Comprehensive acoustic physical layer verification suite."""

    def test_pure_silence_produces_zero_packets(self):
        """Silence must never produce hallucinated packets."""
        sample_rate = 16000
        # 2 seconds of pure zero samples
        silence_samples = [0] * (sample_rate * 2)
        wav_bytes = _synthesize_wav(silence_samples, sample_rate=sample_rate)

        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        packets = demod.decode_wav(wav_bytes)
        assert packets == [], f"Expected 0 packets on silence, got {len(packets)}"

    def test_ambient_white_noise_produces_zero_packets(self):
        """Gaussian ambient acoustic noise must never trigger false CRC matches."""
        sample_rate = 16000
        rng = random.Random(42)
        # 2.5 seconds of high-amplitude white noise
        noise_samples = [
            int(max(-32767, min(32767, rng.gauss(0, 4000))))
            for _ in range(int(sample_rate * 2.5))
        ]
        wav_bytes = _synthesize_wav(noise_samples, sample_rate=sample_rate)

        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        packets = demod.decode_wav(wav_bytes)
        assert packets == [], f"Expected 0 packets on white noise, got {len(packets)}"

    def test_corrupted_transmission_rejected_by_crc(self):
        """Audio transmission with corrupted bits must be rejected by CRC16."""
        sample_rate = 16000
        mod = AFSKModulator(sample_rate=sample_rate, baud_rate=1200)
        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)

        payload = b"CRITICAL DISPATCH: FIELD CLINIC REAGENT SHORTAGE"
        clean_wav = mod.synthesize_wav(payload, amplitude=0.8, include_chirp=True)

        # Unpack, corrupt samples in the middle of the payload, and re-pack
        buf = io.BytesIO(clean_wav)
        with wave.open(buf, "rb") as w:
            n_frames = w.getnframes()
            frames = struct.unpack(f"<{n_frames}h", w.readframes(n_frames))

        corrupted_frames = list(frames)
        # Inject broadband burst noise across 15% of frames in the payload
        corrupt_rng = random.Random(999)
        corrupt_start = int(n_frames * 0.40)
        corrupt_len = int(n_frames * 0.15)
        for i in range(corrupt_start, corrupt_start + corrupt_len):
            corrupted_frames[i] = corrupt_rng.randint(-30000, 30000)

        corrupted_wav = _synthesize_wav(corrupted_frames, sample_rate=sample_rate)
        recovered = demod.decode_wav(corrupted_wav)
        assert payload not in recovered, "Corrupted audio frame was mistakenly accepted!"

    def test_novel_text_bulletin_delivery_through_room_acoustics(self, tmp_path: Path):
        """
        End-to-end verification of novel text bulletin delivery:
        1. Modulate unknown emergency bulletin to Bell 202 AFSK audio.
        2. Impair audio through real room multipath reflections (echo) and background noise.
        3. Demodulate audio on the receiving node.
        4. Confirm bit-exact bulletin recovery.
        5. Persist recovered bulletin into TFPNode SQLite database.
        """
        sample_rate = 16000
        mod = AFSKModulator(sample_rate=sample_rate, baud_rate=1200, preamble_flags=24)
        demod = AFSKDemodulator.bell202_1200(sample_rate=sample_rate)
        sim = AcousticChannelSimulator(seed=12345)

        bulletin_text = (
            "EMERGENCY DISASTER ADVISORY #881: "
            "Clean water distribution point opened at Sector 4 Coordinates 14.33N 121.05E. "
            "Oral rehydration salts available at medical tent."
        )
        bulletin_bytes = bulletin_text.encode("utf-8")
        assert len(bulletin_bytes) <= MAX_AFSK_PAYLOAD_SIZE

        # 1. Modulate
        tx_wav = mod.synthesize_wav(bulletin_bytes, amplitude=0.85, include_chirp=True)

        # 2. Acoustic channel simulation: multipath room reflections + 30 dB SNR noise
        rx_wav = sim.impair_wav(
            tx_wav,
            attenuation=0.60,
            snr_db=30.0,
            reverberation=True,
            clipping=False,
        )

        # 3. Demodulate
        packets = demod.decode_wav(rx_wav)
        assert len(packets) >= 1, "Demodulator failed to recover any packets from acoustic audio"
        assert bulletin_bytes in packets, "Recovered packets do not contain the target bulletin"

        # 4. Check bit-exact string recovery
        matching_packet = next(p for p in packets if p == bulletin_bytes)
        recovered_text = matching_packet.decode("utf-8")
        assert recovered_text == bulletin_text

        # 5. Persist recovered bulletin into TFPNode SQLite store
        db_path = tmp_path / "acoustic_node.db"
        node = TFPNode(db_path=db_path)
        recipe = node.publish(matching_packet, metadata={"source": "acoustic_radio_broadcast"})

        assert db_path.exists()
        # Verify in a fresh TFPNode instance
        fresh_node = TFPNode(db_path=db_path)
        stored_bytes = fresh_node.fetch(recipe.root_hash)
        assert stored_bytes == bulletin_bytes
        assert stored_bytes.decode("utf-8") == bulletin_text
