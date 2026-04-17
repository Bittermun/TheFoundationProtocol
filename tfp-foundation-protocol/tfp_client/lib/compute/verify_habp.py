# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hardware-Agnostic Benchmark Proof (HABP) Verification

Verifies compute task results via redundant execution consensus or
TEE attestation fallback. Returns verification status and credit weight.
"""

import hashlib
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class ExecutionProof:
    """Proof of execution from a device."""

    device_id: str
    task_id: str
    output_hash: str  # SHA3-256 of result
    execution_time: float  # Seconds taken
    hardware_signature: str  # Device-specific signature
    tee_attestation: Optional[str] = None  # TEE quote if available
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConsensusResult:
    """Result of consensus verification."""

    verified: bool
    confidence: float  # 0.0-1.0
    matching_devices: List[str]
    conflicting_devices: List[str]
    credit_weight: float  # Multiplier for credit reward
    method: str  # "consensus" or "tee"


class HABPVerifier:
    """
    Hardware-Agnostic Benchmark Proof verifier.

    Supports two verification modes:
    1. Redundant Execution Consensus (3/5 match)
    2. TEE Attestation fallback
    """

    def __init__(self, consensus_threshold: int = 3, redundancy_factor: int = 5):
        self._consensus_threshold = consensus_threshold
        self._redundancy_factor = redundancy_factor
        self._proofs: Dict[str, List[ExecutionProof]] = defaultdict(list)
        self._verified_tasks: Dict[str, ConsensusResult] = {}
        self._trusted_tees: Set[str] = set()  # Known good TEE identifiers
        self._task_timestamps: Dict[
            str, float
        ] = {}  # Track when tasks were added for cleanup
        self._lock = threading.Lock()  # Lock to prevent race conditions during cleanup

    def submit_proof(self, proof: ExecutionProof) -> bool:
        """Submit an execution proof for verification."""
        with self._lock:
            self._proofs[proof.task_id].append(proof)
            # Track timestamp for cleanup
            if proof.task_id not in self._task_timestamps:
                self._task_timestamps[proof.task_id] = proof.timestamp
        return True

    def verify_consensus(self, task_id: str) -> Optional[ConsensusResult]:
        """
        Verify task via redundant execution consensus.

        Requires consensus_threshold matching outputs out of
        redundancy_factor total executions.
        """
        with self._lock:
            if task_id not in self._proofs:
                return None

            proofs = self._proofs[task_id]
            if len(proofs) < self._consensus_threshold:
                return None  # Not enough proofs yet

            # Group by output hash
            hash_groups: Dict[str, List[ExecutionProof]] = defaultdict(list)
            for proof in proofs:
                hash_groups[proof.output_hash].append(proof)

            # Find largest matching group
            largest_group = max(hash_groups.values(), key=len)

            if len(largest_group) >= self._consensus_threshold:
                matching = [p.device_id for p in largest_group]
                conflicting = [
                    p.device_id
                    for p in proofs
                    if p.output_hash != largest_group[0].output_hash
                ]

                confidence = len(largest_group) / len(proofs)
                credit_weight = confidence * (
                    1.0 + (len(largest_group) - self._consensus_threshold) * 0.1
                )
                credit_weight = min(2.0, credit_weight)  # Cap at 2x

                result = ConsensusResult(
                    verified=True,
                    confidence=confidence,
                    matching_devices=matching,
                    conflicting_devices=list(set(conflicting)),
                    credit_weight=credit_weight,
                    method="consensus",
                )

                self._verified_tasks[task_id] = result
                return result

            # No consensus reached
            all_devices = [p.device_id for p in proofs]
            result = ConsensusResult(
                verified=False,
                confidence=0.0,
                matching_devices=[],
                conflicting_devices=all_devices,
                credit_weight=0.0,
                method="consensus",
            )

            self._verified_tasks[task_id] = result
            return result

    def verify_tee(
        self, proof: ExecutionProof, expected_output_hash: str
    ) -> Optional[ConsensusResult]:
        """
        Verify task via TEE attestation.

        If the device has a valid TEE quote that matches the expected
        output, verification is immediate.
        """
        if not proof.tee_attestation:
            return None

        # In production: verify TEE quote signature against manufacturer keys
        # Here we simulate with a simple check
        is_valid_tee = self._verify_tee_quote(proof.tee_attestation, proof.device_id)

        if not is_valid_tee:
            return None

        if proof.output_hash != expected_output_hash:
            result = ConsensusResult(
                verified=False,
                confidence=1.0,
                matching_devices=[],
                conflicting_devices=[proof.device_id],
                credit_weight=0.0,
                method="tee",
            )
        else:
            result = ConsensusResult(
                verified=True,
                confidence=1.0,
                matching_devices=[proof.device_id],
                conflicting_devices=[],
                credit_weight=1.0,  # No TEE bonus - eliminates forgery vector
                method="tee",
            )

        with self._lock:
            self._verified_tasks[proof.task_id] = result
        return result

    def _verify_tee_quote(self, quote: str, device_id: str) -> bool:
        """
        Verify TEE attestation quote.

        In production: cryptographically verify against Intel/AMD/ARM keys.
        """
        # Simulated: check if quote starts with device_id and contains "VALID"
        return quote.startswith(device_id[:8]) and "VALID" in quote

    def register_trusted_tee(self, tee_id: str) -> None:
        """Register a known-good TEE identifier."""
        self._trusted_tees.add(tee_id)

    def get_verification_result(self, task_id: str) -> Optional[ConsensusResult]:
        """Get verification result for a task."""
        with self._lock:
            return self._verified_tasks.get(task_id)

    def get_proof_count(self, task_id: str) -> int:
        """Get number of proofs submitted for a task."""
        with self._lock:
            return len(self._proofs.get(task_id, []))

    def clear_task(self, task_id: str) -> None:
        """Clear proofs and results for a task."""
        with self._lock:
            if task_id in self._proofs:
                del self._proofs[task_id]
            if task_id in self._verified_tasks:
                del self._verified_tasks[task_id]
            if task_id in self._task_timestamps:
                del self._task_timestamps[task_id]

    def cleanup_stale_tasks(self, completed_task_ids: List[str]) -> int:
        """
        Clean up in-memory state for completed/failed tasks to prevent memory leaks.

        Args:
            completed_task_ids: List of task IDs that have been completed or failed

        Returns:
            Number of tasks cleaned up
        """
        cleaned = 0
        with self._lock:
            for task_id in completed_task_ids:
                if task_id in self._proofs or task_id in self._verified_tasks:
                    if task_id in self._proofs:
                        del self._proofs[task_id]
                    if task_id in self._verified_tasks:
                        del self._verified_tasks[task_id]
                    if task_id in self._task_timestamps:
                        del self._task_timestamps[task_id]
                    cleaned += 1
        return cleaned

    def get_all_task_ids(self) -> List[str]:
        """Get all task IDs currently stored in the verifier."""
        with self._lock:
            return list(set(self._proofs.keys()) | set(self._verified_tasks.keys()))


def generate_execution_proof(
    device_id: str,
    task_id: str,
    output_data: bytes,
    execution_time: float,
    has_tee: bool = False,
) -> ExecutionProof:
    """Generate an execution proof for a completed task."""
    output_hash = hashlib.sha3_256(output_data).hexdigest()

    # Simulate hardware signature (in production: sign with device private key)
    hw_sig_data = f"{device_id}:{task_id}:{output_hash}:{time.time()}".encode()
    hardware_signature = hashlib.sha3_256(hw_sig_data).hexdigest()[:32]

    tee_attestation = None
    if has_tee:
        # Simulate TEE quote
        tee_attestation = f"{device_id[:8]}-VALID-TEE-QUOTE-{output_hash[:16]}"

    return ExecutionProof(
        device_id=device_id,
        task_id=task_id,
        output_hash=output_hash,
        execution_time=execution_time,
        hardware_signature=hardware_signature,
        tee_attestation=tee_attestation,
    )
