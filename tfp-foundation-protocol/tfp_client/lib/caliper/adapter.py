# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
CaliperAdapter - Performance benchmarking for the TFP stack.

Measures throughput and latency of:
- RaptorQ encode/decode operations
- Credit ledger mint/spend operations
- Full end-to-end request→reconstruct flow

Usage:
    adapter = CaliperAdapter(iterations=100)
    result = adapter.benchmark_encode_decode(payload_size=4096)
    print(result.to_dict())

    suite = BenchmarkSuite(iterations=50)
    results = suite.run_all()
    print(suite.summary(results))
"""

import dataclasses
import hashlib
import json
import time
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class ThresholdViolation(Exception):
    """Raised by BenchmarkSuite when a result fails its threshold and
    ``raise_on_failure=True``."""


# ---------------------------------------------------------------------------
# BenchmarkResult dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BenchmarkResult:
    """Holds the outcome of a single benchmark run."""

    name: str
    ops_per_sec: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    throughput_bytes_per_sec: float
    passed: bool
    failure_reason: str = ""
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ops_per_sec": self.ops_per_sec,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "throughput_bytes_per_sec": self.throughput_bytes_per_sec,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: List[float], p: float) -> float:
    """Return the p-th percentile (0–100) from a *sorted* list."""
    if not sorted_values:
        return 0.0
    idx = (p / 100.0) * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _compute_percentiles(latencies_ms: List[float]):
    """Return (p50, p95, p99) from a list of latency measurements (ms)."""
    s = sorted(latencies_ms)
    return _percentile(s, 50), _percentile(s, 95), _percentile(s, 99)


# ---------------------------------------------------------------------------
# CaliperAdapter
# ---------------------------------------------------------------------------


class CaliperAdapter:
    """
    Benchmarks the TFP stack in-process.

    All benchmarks exercise real code paths (RaptorQ adapter, credit ledger,
    TFPClient) so results reflect actual performance, not synthetic stubs.

    Args:
        iterations: Number of repetitions for each benchmark.
        min_encode_throughput_bytes_per_sec: Pass threshold for encode/decode.
        min_credit_ops_per_sec: Pass threshold for credit ledger ops.
        max_p99_latency_ms: Max allowed p99 latency for any benchmark.
    """

    DEFAULT_MIN_ENCODE_THROUGHPUT = 5_000  # 5 KB/s (realistic for current implementation)
    DEFAULT_MIN_CREDIT_OPS = 100  # 100 tx/s
    DEFAULT_MAX_P99_MS = 200.0  # 200 ms

    def __init__(
        self,
        iterations: int = 50,
        min_encode_throughput_bytes_per_sec: float = DEFAULT_MIN_ENCODE_THROUGHPUT,
        min_credit_ops_per_sec: float = DEFAULT_MIN_CREDIT_OPS,
        max_p99_latency_ms: float = DEFAULT_MAX_P99_MS,
    ):
        self.iterations = iterations
        self.min_encode_throughput_bytes_per_sec = min_encode_throughput_bytes_per_sec
        self.min_credit_ops_per_sec = min_credit_ops_per_sec
        self.max_p99_latency_ms = max_p99_latency_ms

    # ------------------------------------------------------------------
    # Public benchmarks
    # ------------------------------------------------------------------

    def benchmark_encode_decode(self, payload_size: int = 4096) -> BenchmarkResult:
        """Benchmark RaptorQ encode + decode round-trip."""
        try:
            from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter

            adapter = RealRaptorQAdapter()
        except ImportError:
            return self._unavailable_result(
                "raptorq_encode_decode", "RealRaptorQAdapter unavailable"
            )

        unit = bytes(range(256))
        payload = (unit * (payload_size // 256 + 1))[:payload_size]

        latencies: List[float] = []
        total_bytes = 0
        t_start = time.perf_counter()

        for _ in range(self.iterations):
            t0 = time.perf_counter()
            shards = adapter.encode(payload, redundancy=0.1)
            adapter.decode(shards)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)
            total_bytes += payload_size

        total_elapsed = time.perf_counter() - t_start
        ops_per_sec = self.iterations / total_elapsed
        throughput = total_bytes / total_elapsed
        p50, p95, p99 = _compute_percentiles(latencies)

        passed = True
        failure_reason = ""
        if throughput < self.min_encode_throughput_bytes_per_sec:
            passed = False
            failure_reason = (
                f"throughput {throughput:.0f} B/s below threshold "
                f"{self.min_encode_throughput_bytes_per_sec:.0f} B/s"
            )
        elif p99 > self.max_p99_latency_ms:
            passed = False
            failure_reason = f"p99 latency {p99:.1f} ms exceeds threshold {self.max_p99_latency_ms:.1f} ms"

        return BenchmarkResult(
            name="raptorq_encode_decode",
            ops_per_sec=ops_per_sec,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            throughput_bytes_per_sec=throughput,
            passed=passed,
            failure_reason=failure_reason,
        )

    def benchmark_credit_ops(self) -> BenchmarkResult:
        """Benchmark CreditLedger mint + spend cycle."""
        try:
            from tfp_client.lib.credit.ledger import CreditLedger
        except ImportError:
            return self._unavailable_result(
                "credit_ledger_ops", "CreditLedger unavailable"
            )

        ledger = CreditLedger()
        latencies: List[float] = []
        t_start = time.perf_counter()

        for i in range(self.iterations):
            proof = hashlib.sha3_256(str(i).encode()).digest()
            t0 = time.perf_counter()
            receipt = ledger.mint(10, proof)
            ledger.spend(1, receipt)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)

        total_elapsed = time.perf_counter() - t_start
        ops_per_sec = self.iterations / total_elapsed
        p50, p95, p99 = _compute_percentiles(latencies)

        passed = True
        failure_reason = ""
        if ops_per_sec < self.min_credit_ops_per_sec:
            passed = False
            failure_reason = (
                f"credit ops {ops_per_sec:.1f}/s below threshold "
                f"{self.min_credit_ops_per_sec:.1f}/s"
            )
        elif p99 > self.max_p99_latency_ms:
            passed = False
            failure_reason = f"p99 latency {p99:.1f} ms exceeds threshold {self.max_p99_latency_ms:.1f} ms"

        return BenchmarkResult(
            name="credit_ledger_ops",
            ops_per_sec=ops_per_sec,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            throughput_bytes_per_sec=0.0,
            passed=passed,
            failure_reason=failure_reason,
        )

    def benchmark_end_to_end(self, payload_size: int = 512) -> BenchmarkResult:
        """Benchmark the full TFPClient request → reconstruct mock cycle."""
        try:
            from tfp_client.lib.core.tfp_engine import TFPClient
        except ImportError:
            return self._unavailable_result(
                "end_to_end_latency", "TFPClient unavailable"
            )

        client = TFPClient()
        payload = b"\xab" * payload_size
        root_hash = hashlib.sha3_256(payload).hexdigest()

        # Pre-earn credits so request_content doesn't fail
        for _ in range(self.iterations):
            client.submit_compute_task(root_hash)

        latencies: List[float] = []
        t_start = time.perf_counter()

        for _ in range(self.iterations):
            t0 = time.perf_counter()
            client.request_content(root_hash)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)

        total_elapsed = time.perf_counter() - t_start
        ops_per_sec = self.iterations / total_elapsed
        p50, p95, p99 = _compute_percentiles(latencies)

        passed = True
        failure_reason = ""
        if p99 > self.max_p99_latency_ms:
            passed = False
            failure_reason = f"e2e p99 latency {p99:.1f} ms exceeds threshold {self.max_p99_latency_ms:.1f} ms"

        return BenchmarkResult(
            name="end_to_end_latency",
            ops_per_sec=ops_per_sec,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            throughput_bytes_per_sec=payload_size * ops_per_sec,
            passed=passed,
            failure_reason=failure_reason,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unavailable_result(name: str, reason: str) -> BenchmarkResult:
        return BenchmarkResult(
            name=name,
            ops_per_sec=0.0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            throughput_bytes_per_sec=0.0,
            passed=False,
            failure_reason=reason,
        )


# ---------------------------------------------------------------------------
# BenchmarkSuite
# ---------------------------------------------------------------------------


class BenchmarkSuite:
    """
    Runs all CaliperAdapter benchmarks and reports a unified summary.

    Args:
        iterations: Iterations passed to each benchmark.
        raise_on_failure: If True, raises ThresholdViolation on first failure.
        min_encode_throughput_bytes_per_sec: Override encode threshold.
        min_credit_ops_per_sec: Override credit ops threshold.
        max_p99_latency_ms: Override p99 threshold.
    """

    def __init__(
        self,
        iterations: int = 50,
        raise_on_failure: bool = False,
        min_encode_throughput_bytes_per_sec: float = CaliperAdapter.DEFAULT_MIN_ENCODE_THROUGHPUT,
        min_credit_ops_per_sec: float = CaliperAdapter.DEFAULT_MIN_CREDIT_OPS,
        max_p99_latency_ms: float = CaliperAdapter.DEFAULT_MAX_P99_MS,
    ):
        self._adapter = CaliperAdapter(
            iterations=iterations,
            min_encode_throughput_bytes_per_sec=min_encode_throughput_bytes_per_sec,
            min_credit_ops_per_sec=min_credit_ops_per_sec,
            max_p99_latency_ms=max_p99_latency_ms,
        )
        self._raise_on_failure = raise_on_failure

    def run_all(self) -> List[BenchmarkResult]:
        """Run all benchmarks and return results."""
        benchmarks = [
            lambda: self._adapter.benchmark_encode_decode(payload_size=2048),
            lambda: self._adapter.benchmark_credit_ops(),
            lambda: self._adapter.benchmark_end_to_end(payload_size=512),
        ]
        results: List[BenchmarkResult] = []
        for fn in benchmarks:
            result = fn()
            results.append(result)
            if self._raise_on_failure and not result.passed:
                raise ThresholdViolation(
                    f"Benchmark '{result.name}' failed: {result.failure_reason}"
                )
        return results

    @staticmethod
    def summary(results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Return a human-readable summary dict."""
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        return {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "pass_rate": len(passed) / len(results) if results else 0.0,
            "failed_names": [r.name for r in failed],
        }

    @staticmethod
    def export_json(results: List[BenchmarkResult]) -> str:
        """Serialize results to a JSON string."""
        return json.dumps([r.to_dict() for r in results], indent=2)
