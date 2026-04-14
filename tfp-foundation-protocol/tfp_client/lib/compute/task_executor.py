# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Real Compute Task Executor

Implements three task types that devices actually execute, producing
verifiable proofs. Results can be independently re-executed by other
nodes for HABP consensus.

Task Types:
  HASH_PREIMAGE  – find nonce such that SHA3-256(input+nonce) has N leading zero bits
  MATRIX_VERIFY  – verify that C = A × B (mod p) for provided matrices
  CONTENT_VERIFY – verify integrity of a content shard (SHA3-256 round-trip)
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class TaskType(str, Enum):
    HASH_PREIMAGE = "hash_preimage"
    MATRIX_VERIFY = "matrix_verify"
    CONTENT_VERIFY = "content_verify"


@dataclass
class TaskSpec:
    """Serialisable description of a unit of work."""

    task_id: str
    task_type: TaskType
    difficulty: int  # 1–10 (maps to leading-zero bits / matrix size / shard count)
    input_data: bytes  # Encoded input (JSON for matrix, raw bytes for others)
    expected_output_hash: (
        str  # SHA3-256 hex of the correct result; used for verification
    )
    created_at: float = field(default_factory=time.time)
    deadline: float = field(default_factory=lambda: time.time() + 3600)
    credit_reward: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "difficulty": self.difficulty,
            "input_data_hex": self.input_data.hex(),
            "expected_output_hash": self.expected_output_hash,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "credit_reward": self.credit_reward,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskSpec":
        return cls(
            task_id=d["task_id"],
            task_type=TaskType(d["task_type"]),
            difficulty=d["difficulty"],
            input_data=bytes.fromhex(d["input_data_hex"]),
            expected_output_hash=d["expected_output_hash"],
            created_at=d.get("created_at", time.time()),
            deadline=d.get("deadline", time.time() + 3600),
            credit_reward=d.get("credit_reward", 10),
        )


@dataclass
class ExecutionResult:
    """Result of executing a task."""

    task_id: str
    task_type: TaskType
    output_hash: str  # SHA3-256 hex of result bytes
    result_bytes: bytes  # The actual result
    execution_time_s: float
    verified_locally: bool  # Whether result matches expected_output_hash
    nonce: Optional[int] = None  # Only for HASH_PREIMAGE tasks


class TaskExecutionError(Exception):
    """Raised when a task cannot be executed (e.g. timed out, malformed input)."""


# ---------------------------------------------------------------------------
# Task generation — server calls these to create well-formed tasks
# ---------------------------------------------------------------------------


def generate_hash_preimage_task(task_id: str, difficulty: int, seed: bytes) -> TaskSpec:
    """
    Create a hash-preimage task.

    The device must find a 4-byte little-endian nonce ``n`` such that
    SHA3-256(seed + n) has ``leading_zeros`` leading zero bits.

    difficulty 1 → 8 leading zero bits  (easy, ~256 attempts)
    difficulty 5 → 12 leading zero bits  (~4096 attempts)
    difficulty 10 → 20 leading zero bits  (~1M attempts)
    """
    leading_zeros = 4 + (difficulty - 1) * 2  # bits
    nonce, result_bytes = _solve_hash_preimage(seed, leading_zeros, max_iter=2_000_000)
    if nonce is None:
        raise TaskExecutionError(
            "Could not generate solvable task within iteration limit"
        )
    expected_hash = hashlib.sha3_256(result_bytes).hexdigest()
    spec_input = json.dumps(
        {
            "seed_hex": seed.hex(),
            "leading_zeros": leading_zeros,
        }
    ).encode()
    return TaskSpec(
        task_id=task_id,
        task_type=TaskType.HASH_PREIMAGE,
        difficulty=difficulty,
        input_data=spec_input,
        expected_output_hash=expected_hash,
        credit_reward=max(10, difficulty * 15),
    )


def generate_matrix_verify_task(task_id: str, difficulty: int, seed: bytes) -> TaskSpec:
    """
    Create a matrix-verification task.

    Generates random matrices A (n×k) and B (k×n) and pre-computes C = A × B
    (using integer arithmetic mod 2^31-1).  The device must verify the result.

    difficulty 1 → 4×4 matrices
    difficulty 5 → 12×12 matrices
    difficulty 10 → 24×24 matrices
    """
    n = 4 + (difficulty - 1) * 2
    mod = (1 << 31) - 1  # Mersenne prime
    import secrets as _secrets

    # Use cryptographically secure random for task generation
    rng = _secrets.SystemRandom()
    A = [[rng.randint(0, 255) for _ in range(n)] for _ in range(n)]
    B = [[rng.randint(0, 255) for _ in range(n)] for _ in range(n)]
    C = _matmul_mod(A, B, mod)
    result_bytes = json.dumps(C).encode()
    expected_hash = hashlib.sha3_256(result_bytes).hexdigest()
    spec_input = json.dumps(
        {
            "A": A,
            "B": B,
            "mod": mod,
            "n": n,
        }
    ).encode()
    return TaskSpec(
        task_id=task_id,
        task_type=TaskType.MATRIX_VERIFY,
        difficulty=difficulty,
        input_data=spec_input,
        expected_output_hash=expected_hash,
        credit_reward=max(10, difficulty * 20),
    )


def generate_content_verify_task(
    task_id: str, difficulty: int, content: bytes
) -> TaskSpec:
    """
    Create a content-integrity-verification task.

    The device must hash `difficulty` rounds of SHA3-256 over the content
    (iterated hashing), a lightweight proof-of-work that scales with difficulty
    while remaining verifiable by any node that has the content.
    """
    rounds = difficulty * 5
    result = _iterated_sha3(content, rounds)
    expected_hash = hashlib.sha3_256(result).hexdigest()
    spec_input = json.dumps(
        {
            "content_hex": content.hex(),
            "rounds": rounds,
        }
    ).encode()
    return TaskSpec(
        task_id=task_id,
        task_type=TaskType.CONTENT_VERIFY,
        difficulty=difficulty,
        input_data=spec_input,
        expected_output_hash=expected_hash,
        credit_reward=max(10, difficulty * 12),
    )


# ---------------------------------------------------------------------------
# Task execution — device calls this
# ---------------------------------------------------------------------------


def execute_task(spec: TaskSpec, timeout_s: float = 30.0) -> ExecutionResult:
    """
    Execute a task locally and return an ExecutionResult.

    This is the function a device calls.  The result can be independently
    verified by the server (or other devices) by calling verify_result().
    """
    start = time.monotonic()
    deadline = start + timeout_s

    if spec.task_type == TaskType.HASH_PREIMAGE:
        result, nonce = _execute_hash_preimage(spec, deadline)
    elif spec.task_type == TaskType.MATRIX_VERIFY:
        result, nonce = _execute_matrix_verify(spec, deadline), None
    elif spec.task_type == TaskType.CONTENT_VERIFY:
        result, nonce = _execute_content_verify(spec, deadline), None
    else:
        raise TaskExecutionError(f"Unknown task type: {spec.task_type}")

    elapsed = time.monotonic() - start
    output_hash = hashlib.sha3_256(result).hexdigest()
    verified = output_hash == spec.expected_output_hash

    return ExecutionResult(
        task_id=spec.task_id,
        task_type=spec.task_type,
        output_hash=output_hash,
        result_bytes=result,
        execution_time_s=elapsed,
        verified_locally=verified,
        nonce=nonce,
    )


def verify_result(spec: TaskSpec, result: ExecutionResult) -> bool:
    """
    Server-side verification: re-execute the task and check the output_hash.
    Returns True if the result is correct.
    """
    try:
        expected = execute_task(spec, timeout_s=60.0)
        return result.output_hash == expected.output_hash
    except TaskExecutionError:
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _solve_hash_preimage(
    seed: bytes, leading_zero_bits: int, max_iter: int
) -> Tuple[Optional[int], bytes]:
    """Find nonce such that SHA3-256(seed + nonce_4bytes) has leading_zero_bits zeros."""
    target_bytes = leading_zero_bits // 8
    target_bits = leading_zero_bits % 8
    for nonce in range(max_iter):
        nonce_bytes = struct.pack("<I", nonce)
        candidate = hashlib.sha3_256(seed + nonce_bytes).digest()
        # Check full bytes
        if candidate[:target_bytes] != b"\x00" * target_bytes:
            continue
        # Check remaining bits
        if target_bits > 0:
            mask = 0xFF >> target_bits
            if candidate[target_bytes] & ~mask != 0:
                continue
        return nonce, nonce_bytes
    return None, b""


def _execute_hash_preimage(spec: TaskSpec, deadline: float) -> Tuple[bytes, int]:
    params = json.loads(spec.input_data)
    seed = bytes.fromhex(params["seed_hex"])
    leading_zero_bits = params["leading_zeros"]
    target_bytes_count = leading_zero_bits // 8
    target_bits = leading_zero_bits % 8
    nonce = 0
    while time.monotonic() < deadline:
        nonce_bytes = struct.pack("<I", nonce)
        candidate = hashlib.sha3_256(seed + nonce_bytes).digest()
        if candidate[:target_bytes_count] == b"\x00" * target_bytes_count:
            if (
                target_bits == 0
                or (candidate[target_bytes_count] & ~(0xFF >> target_bits)) == 0
            ):
                return nonce_bytes, nonce
        nonce += 1
    raise TaskExecutionError("Hash preimage search timed out")


def _execute_matrix_verify(spec: TaskSpec, deadline: float) -> bytes:
    params = json.loads(spec.input_data)
    A, B, mod = params["A"], params["B"], params["mod"]
    if time.monotonic() > deadline:
        raise TaskExecutionError("Matrix verify timed out before starting")
    C = _matmul_mod(A, B, mod)
    return json.dumps(C).encode()


def _execute_content_verify(spec: TaskSpec, deadline: float) -> bytes:
    params = json.loads(spec.input_data)
    content = bytes.fromhex(params["content_hex"])
    rounds = params["rounds"]
    if time.monotonic() > deadline:
        raise TaskExecutionError("Content verify timed out before starting")
    return _iterated_sha3(content, rounds)


def _matmul_mod(A: list, B: list, mod: int) -> list:
    n = len(A)
    C = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = 0
            for k in range(n):
                s += A[i][k] * B[k][j]
            C[i][j] = s % mod
    return C


def _iterated_sha3(data: bytes, rounds: int) -> bytes:
    current = data
    for _ in range(rounds):
        current = hashlib.sha3_256(current).digest()
    return current
