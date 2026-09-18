# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Verification suite for Freivalds Asymmetric Work & Anti-Free-Rider Defense.

Tests:
1. Honest worker execution over finite field Z_p (Mersenne prime 2^31 - 1).
2. Zero-exposed-hash task specification: expected_output_hash is empty.
3. Byzantine tampering detection: single-element perturbations are caught.
4. Asymmetric computational complexity: verifier latency is significantly lower than worker latency.
5. Cross-platform determinism: fixed seed produces bit-exact verification outcomes.
"""

import json
import random
import time
import pytest

from tfp_client.lib.compute.task_executor import (
    TaskSpec,
    TaskType,
    generate_matrix_verify_task,
    execute_task,
    verify_result,
    freivalds_verify,
    _matmul_mod,
)


class TestFreivaldsAsymmetricWork:
    def test_zero_exposed_hash_specification(self):
        """Asymmetric tasks must not expose the expected output hash in the spec."""
        spec = generate_matrix_verify_task(
            task_id="task-asym-001",
            difficulty=3,
            seed=b"seed-001",
            asymmetric=True,
        )
        assert spec.expected_output_hash == ""
        assert spec.asymmetric_verify is True
        
        # Serialization round-trip preserves asymmetric_verify flag
        d = spec.to_dict()
        assert d["expected_output_hash"] == ""
        assert d["asymmetric_verify"] is True
        
        reconstructed = TaskSpec.from_dict(d)
        assert reconstructed.expected_output_hash == ""
        assert reconstructed.asymmetric_verify is True

    def test_honest_worker_execution_and_verification(self):
        """An honest worker executes matrix multiplication; verifier confirms correctness."""
        spec = generate_matrix_verify_task(
            task_id="task-honest-001",
            difficulty=4,
            seed=b"honest-seed",
            asymmetric=True,
        )
        result = execute_task(spec, timeout_s=10.0)
        assert result.verified_locally is True
        
        # Server verifies result using Freivalds algorithm without expected_output_hash
        assert verify_result(spec, result) is True

    def test_byzantine_single_element_tampering_rejected(self):
        """A Byzantine worker altering a single element in C is detected and rejected."""
        spec = generate_matrix_verify_task(
            task_id="task-byzantine-001",
            difficulty=4,
            seed=b"byzantine-seed",
            asymmetric=True,
        )
        result = execute_task(spec, timeout_s=10.0)
        
        # Tamper with one element in C
        C = json.loads(result.result_bytes)
        mod = json.loads(spec.input_data)["mod"]
        C[0][0] = (C[0][0] + 1) % mod
        
        tampered_result = result.__class__(
            task_id=result.task_id,
            task_type=result.task_type,
            output_hash=result.output_hash,
            result_bytes=json.dumps(C).encode(),
            execution_time_s=result.execution_time_s,
            verified_locally=result.verified_locally,
        )
        
        assert verify_result(spec, tampered_result) is False

    def test_trivial_matrices_rejected(self):
        """Submitting all-zeros or identity matrices fails verification."""
        spec = generate_matrix_verify_task(
            task_id="task-trivial-001",
            difficulty=3,
            seed=b"trivial-seed",
            asymmetric=True,
        )
        n = json.loads(spec.input_data)["n"]
        zeros = [[0] * n for _ in range(n)]
        
        fake_result = execute_task(spec, timeout_s=10.0)
        fake_result.result_bytes = json.dumps(zeros).encode()
        
        assert verify_result(spec, fake_result) is False

    def test_asymmetric_computational_advantage(self):
        """Verification time must be faster than worker multiplication time on moderate n."""
        n = 48
        mod = (1 << 31) - 1
        rng = random.Random(1337)
        A = [[rng.randint(0, 255) for _ in range(n)] for _ in range(n)]
        B = [[rng.randint(0, 255) for _ in range(n)] for _ in range(n)]
        
        # Worker compute: O(n^3)
        t0 = time.perf_counter()
        C = _matmul_mod(A, B, mod)
        worker_time = time.perf_counter() - t0
        
        # Verifier compute: O(k * n^2) with k=15 rounds
        t0 = time.perf_counter()
        verified = freivalds_verify(A, B, C, mod=mod, k=15, seed=b"verifier-seed")
        verifier_time = time.perf_counter() - t0
        
        assert verified is True
        # Verifier should be faster than full worker multiplication
        assert verifier_time < worker_time

    def test_cross_platform_integer_determinism(self):
        """Fixed seed and inputs produce identical verification outcomes."""
        mod = (1 << 31) - 1
        rng = random.Random(42)
        A = [[rng.randint(0, 1000) for _ in range(16)] for _ in range(16)]
        B = [[rng.randint(0, 1000) for _ in range(16)] for _ in range(16)]
        C = _matmul_mod(A, B, mod)
        
        # Run 5 times with same seed: result must be identical
        for _ in range(5):
            assert freivalds_verify(A, B, C, mod=mod, k=20, seed=b"deterministic-seed") is True
