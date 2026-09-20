# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Acoustic Multipath Sweep & 300-Baud Fallback Test Suite.

Verifies:
1. Empirical cliff effect detection where severe multipath echo causes 1200-baud failure.
2. 300-baud (3.33ms symbol duration) acoustic survival through heavy room reflections.
3. Adaptive fallback decoding in AFSKDemodulator.
4. Bell 103 (1270 Hz / 1070 Hz @ 300 baud) modulation and demodulation.
"""

import pytest
from scripts.run_experiment import run_acoustic_multipath_sweep_experiment
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator


def test_multipath_sweep_cliff_and_fallback_recovery():
    """Verify acoustic multipath sweep identifies 1200-baud cliff and validates 300-baud recovery."""
    result = run_acoustic_multipath_sweep_experiment()

    assert result["success"] is True
    assert result["cliff_detected"] is True, "1200 baud should fail under severe concrete cavern reflections"
    assert result["fallback_rescued"] is True, "300-baud fallback mode should rescue packet recovery"

    profiles = {p["profile"]: p for p in result["profiles"]}
    assert "mild_clinic" in profiles
    assert "moderate_hallway" in profiles
    assert "severe_concrete_cavern" in profiles

    assert profiles["mild_clinic"]["baud_1200_pass"] is True
    assert profiles["mild_clinic"]["baud_300_pass"] is True

    assert profiles["severe_concrete_cavern"]["baud_1200_pass"] is False
    assert profiles["severe_concrete_cavern"]["baud_300_pass"] is True
    assert profiles["severe_concrete_cavern"]["rescued_by_fallback"] is True


def test_bell103_300_baud_roundtrip():
    """Verify Bell 103 standard (1270 Hz / 1070 Hz @ 300 baud) modulates and demodulates."""
    mod = AFSKModulator.bell103_300(sample_rate=16000, preamble_flags=8)
    dem = AFSKDemodulator.bell103_300(sample_rate=16000)
    sim = AcousticChannelSimulator(seed=101)

    payload = b"BELL103:EMERGENCY_BROADCAST:CHANNEL_7"
    tx_wav = mod.synthesize_wav(payload, amplitude=0.8, include_chirp=True)

    # Degrade with mild attenuation and AWGN noise
    rx_wav = sim.impair_wav(
        tx_wav,
        attenuation=0.6,
        snr_db=25.0,
        reverberation=False,
    )

    extracted = dem.decode_wav(rx_wav)
    assert len(extracted) >= 1
    assert payload in extracted


def test_afsk_demodulator_adaptive_fallback():
    """Verify 1200-baud demodulator automatically rescues 300-baud transmission when fallback_300=True."""
    mod300 = AFSKModulator.bell202_300(sample_rate=16000, preamble_flags=8)
    dem1200 = AFSKDemodulator.bell202_1200(sample_rate=16000)

    payload = b"AIRGAP:FALLBACK_PACKET_VERIFIED"
    tx_wav = mod300.synthesize_wav(payload, amplitude=0.8, include_chirp=True)

    # Standard 1200-baud decoding alone will not find the 300-baud packet
    without_fallback = dem1200.decode_wav(tx_wav, fallback_300=False)
    assert payload not in without_fallback

    # Adaptive decoding with fallback_300=True automatically detects and extracts it
    with_fallback = dem1200.decode_wav(tx_wav, fallback_300=True)
    assert payload in with_fallback
