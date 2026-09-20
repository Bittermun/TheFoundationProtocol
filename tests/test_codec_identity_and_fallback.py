# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Experiment 3: Codec Identity & Fallback Verification

Verifies:
1. Truthful identity reporting: is_accelerated accurately reflects whether
   the native C-ABI library (wirehair.dll / libwirehair.so) is actually loaded.
2. Honest fallback operation: AcceleratedFountainCodec operates with 100%
   mathematical correctness via pure-Python GF(2) Gaussian elimination when
   native acceleration is absent.
3. Erasure resilience in fallback mode: Dropping systematic droplets forces
   algebraic reconstruction from parity droplets without relying on publisher memory.
4. Sub-rank rejection: Attempting to decode with fewer than K independent droplets
   strictly raises ValueError/RuntimeError rather than returning partial/corrupted data.
"""

from pathlib import Path
import random
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.wirehair_bridge import (
    AcceleratedFountainCodec,
    wirehair_is_available,
    _find_wirehair_lib,
)
from tfp_core_v4.fountain import FountainDroplet


def test_codec_identity_probe_truthful():
    """Verify that is_accelerated truthfully reports native library presence."""
    lib_path = _find_wirehair_lib()
    avail = wirehair_is_available()

    if lib_path is None:
        assert avail is False, "wirehair_is_available must be False when library file is absent"
    
    # Instance with prefer_native=True
    codec_default = AcceleratedFountainCodec(symbol_size=256, prefer_native=True)
    assert codec_default.is_accelerated == avail, (
        f"Codec is_accelerated ({codec_default.is_accelerated}) must match wirehair_is_available ({avail})"
    )

    # Instance with prefer_native=False must always be False
    codec_forced_py = AcceleratedFountainCodec(symbol_size=256, prefer_native=False)
    assert codec_forced_py.is_accelerated is False, (
        "prefer_native=False must force pure-Python engine regardless of library availability"
    )


def test_fallback_codec_erasure_recovery():
    """Verify that fallback codec solves dropped systematic symbols via GF(2) Gaussian elimination."""
    payload = b"EMERGENCY-TRIAGE-PROTOCOL-KNOWLEDGE-BASE-BLOCK-VERIFICATION-DATA" * 30  # ~1920 bytes
    codec = AcceleratedFountainCodec(symbol_size=256, prefer_native=False)

    droplets, k, orig_len = codec.encode(payload, redundancy=1.0)
    assert k >= 7, f"Payload must split into multiple symbols (got k={k})"
    assert len(droplets) >= math_expected_total(k, 1.0)

    # Drop systematic droplets #1 and #3
    dropped_indices = {1, 3}
    surviving = [d for d in droplets if not (d.degree == 1 and d.indices[0] in dropped_indices)]

    # Take exactly k + 2 surviving droplets (mix of remaining systematic + repair)
    selected = surviving[: k + 4]
    assert len(selected) >= k

    # Ensure none of the selected droplets are the dropped systematic droplets
    for d in selected:
        if d.degree == 1:
            assert d.indices[0] not in dropped_indices

    # Decode must reconstruct payload bit-exact using repair equations
    decoded = codec.decode(selected, k=k, orig_len=orig_len)
    assert decoded == payload, "Fallback engine must reconstruct original bytes from repair droplets"


def test_fallback_codec_sub_rank_rejection():
    """Verify that decoding with insufficient droplets strictly raises ValueError or RuntimeError."""
    payload = b"CRITICAL_MEDICAL_INVENTORY_REPORT" * 20
    codec = AcceleratedFountainCodec(symbol_size=128, prefer_native=False)

    droplets, k, orig_len = codec.encode(payload, redundancy=0.50)
    assert k > 2

    # Provide strictly fewer than k droplets
    sub_rank_droplets = droplets[: k - 1]
    assert len(sub_rank_droplets) < k

    with pytest.raises((ValueError, RuntimeError)):
        codec.decode(sub_rank_droplets, k=k, orig_len=orig_len)


def test_fallback_droplet_structure_and_soliton_invariants():
    """Verify that emitted droplets adhere to Soliton degree distribution and valid symbol indices."""
    payload = b"SOLITON-DEGREE-DISTRIBUTION-CHECK" * 15
    codec = AcceleratedFountainCodec(symbol_size=128, prefer_native=False)

    droplets, k, orig_len = codec.encode(payload, redundancy=0.80)

    for idx, d in enumerate(droplets):
        assert isinstance(d, FountainDroplet)
        assert len(d.payload) == codec.symbol_size
        assert d.degree == len(d.indices), f"Droplet {idx} degree {d.degree} != len(indices) {len(d.indices)}"
        assert all(0 <= i < k for i in d.indices), f"Droplet indices {d.indices} out of range [0, {k-1}]"
        assert d.indices == sorted(d.indices), "Droplet indices must be strictly sorted"

    # Verify systematic prefix: first k droplets must have degree 1
    for i in range(k):
        assert droplets[i].degree == 1
        assert droplets[i].indices == [i]


def test_fallback_corrupted_droplet_fails():
    """Verify that tampered droplet payloads are strictly rejected by cryptographic integrity verification."""
    import hashlib
    payload = b"AUTHENTIC_VITAL_SIGNS_MONITORING_STREAM" * 10
    root_hash = hashlib.sha3_256(payload).hexdigest()
    codec = AcceleratedFountainCodec(symbol_size=128, prefer_native=False, root_hash=root_hash)

    droplets, k, orig_len = codec.encode(payload, redundancy=0.50)

    # Corrupt payload of droplet 0
    corrupt_droplet = FountainDroplet(
        seed=droplets[0].seed,
        degree=droplets[0].degree,
        indices=droplets[0].indices,
        payload=bytes([b ^ 0xFF for b in droplets[0].payload]),
    )
    tampered_droplets = [corrupt_droplet] + droplets[1:k]

    # When decoded with cryptographic root_hash configured, it MUST strictly raise ValueError
    with pytest.raises(ValueError, match="Integrity check failed"):
        codec.decode(tampered_droplets, k=k, orig_len=orig_len, root_hash=root_hash)


def test_operational_engine_telemetry():
    """Verify that last_engine_used accurately reports operational reality."""
    payload = b"TEST_TELEMETRY_ENGINE_TRACKING" * 10
    codec = AcceleratedFountainCodec(symbol_size=128, prefer_native=False)
    assert codec.last_engine_used == "none"

    codec.encode(payload, redundancy=0.20)
    assert codec.last_engine_used == "python_pure"

    droplets, k, orig_len = codec.encode(payload)
    codec.decode(droplets[:k], k=k, orig_len=orig_len)
    assert codec.last_engine_used == "python_pure"


def math_expected_total(k: int, redundancy: float) -> int:
    import math
    return max(k, math.ceil(k * (1.0 + redundancy)))
