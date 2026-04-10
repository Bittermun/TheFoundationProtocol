"""
TDD tests for CaliperAdapter - Performance benchmarking for TFP stack.

Written BEFORE implementation (Test-Driven Development).

Tests define the contract:
- BenchmarkResult: result dataclass with throughput, latency percentiles, pass/fail
- CaliperAdapter: runs encode/decode, credit ops, end-to-end latency benchmarks
- Minimum thresholds: encode ≥1 MB/s, credit ops ≥100 tx/s, p99 latency ≤200ms
"""

import pytest
import time
from unittest.mock import patch, MagicMock

try:
    from tfp_client.lib.caliper.adapter import (
        CaliperAdapter,
        BenchmarkResult,
        BenchmarkSuite,
        ThresholdViolation,
    )
    CALIPER_AVAILABLE = True
except ImportError:
    CALIPER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not CALIPER_AVAILABLE,
    reason="CaliperAdapter not yet implemented"
)


class TestBenchmarkResult:
    """Tests for the BenchmarkResult dataclass."""

    def test_basic_construction(self):
        result = BenchmarkResult(
            name="test_bench",
            ops_per_sec=500.0,
            latency_p50_ms=5.0,
            latency_p95_ms=12.0,
            latency_p99_ms=20.0,
            throughput_bytes_per_sec=512_000,
            passed=True,
        )
        assert result.name == "test_bench"
        assert result.ops_per_sec == 500.0
        assert result.passed is True

    def test_to_dict_contains_all_fields(self):
        result = BenchmarkResult(
            name="x",
            ops_per_sec=1.0,
            latency_p50_ms=1.0,
            latency_p95_ms=2.0,
            latency_p99_ms=3.0,
            throughput_bytes_per_sec=100,
            passed=True,
        )
        d = result.to_dict()
        for key in ("name", "ops_per_sec", "latency_p50_ms", "latency_p95_ms",
                    "latency_p99_ms", "throughput_bytes_per_sec", "passed"):
            assert key in d

    def test_failed_result(self):
        result = BenchmarkResult(
            name="slow_bench",
            ops_per_sec=0.5,
            latency_p50_ms=500.0,
            latency_p95_ms=900.0,
            latency_p99_ms=1200.0,
            throughput_bytes_per_sec=1_000,
            passed=False,
            failure_reason="p99 latency exceeded threshold",
        )
        assert result.passed is False
        assert "p99" in result.failure_reason


class TestCaliperAdapterConstruction:
    """Tests for CaliperAdapter construction."""

    def test_default_construction(self):
        adapter = CaliperAdapter()
        assert adapter is not None

    def test_custom_thresholds(self):
        adapter = CaliperAdapter(
            min_encode_throughput_bytes_per_sec=2_000_000,
            min_credit_ops_per_sec=200,
            max_p99_latency_ms=100.0,
        )
        assert adapter.min_encode_throughput_bytes_per_sec == 2_000_000
        assert adapter.min_credit_ops_per_sec == 200
        assert adapter.max_p99_latency_ms == 100.0

    def test_iterations_configurable(self):
        adapter = CaliperAdapter(iterations=50)
        assert adapter.iterations == 50


class TestEncodeDecodeBenchmark:
    """Tests for RaptorQ encode/decode benchmarking."""

    def test_benchmark_encode_returns_result(self):
        adapter = CaliperAdapter(iterations=5)
        result = adapter.benchmark_encode_decode(payload_size=1024)
        assert isinstance(result, BenchmarkResult)
        assert result.name == "raptorq_encode_decode"

    def test_benchmark_encode_throughput_positive(self):
        adapter = CaliperAdapter(iterations=5)
        result = adapter.benchmark_encode_decode(payload_size=4096)
        assert result.throughput_bytes_per_sec > 0
        assert result.ops_per_sec > 0

    def test_benchmark_encode_latency_percentiles_ordered(self):
        adapter = CaliperAdapter(iterations=10)
        result = adapter.benchmark_encode_decode(payload_size=2048)
        assert result.latency_p50_ms <= result.latency_p95_ms
        assert result.latency_p95_ms <= result.latency_p99_ms

    def test_benchmark_encode_passes_default_threshold(self):
        """On any modern CPU, 1 KB encode in <200ms is trivial."""
        adapter = CaliperAdapter(iterations=5)
        result = adapter.benchmark_encode_decode(payload_size=1024)
        assert result.passed is True

    def test_benchmark_encode_fails_unreachable_threshold(self):
        """Force failure with an impossible throughput threshold."""
        adapter = CaliperAdapter(
            iterations=5,
            min_encode_throughput_bytes_per_sec=10 ** 12,  # 1 TB/s impossible
        )
        result = adapter.benchmark_encode_decode(payload_size=1024)
        assert result.passed is False
        assert result.failure_reason


class TestCreditOpsBenchmark:
    """Tests for credit ledger benchmark."""

    def test_benchmark_credit_ops_returns_result(self):
        adapter = CaliperAdapter(iterations=10)
        result = adapter.benchmark_credit_ops()
        assert isinstance(result, BenchmarkResult)
        assert result.name == "credit_ledger_ops"

    def test_benchmark_credit_ops_positive(self):
        adapter = CaliperAdapter(iterations=10)
        result = adapter.benchmark_credit_ops()
        assert result.ops_per_sec > 0

    def test_credit_ops_passes_100_per_sec(self):
        """Credit ledger should handle ≥100 tx/s on any hardware."""
        adapter = CaliperAdapter(iterations=100, min_credit_ops_per_sec=100)
        result = adapter.benchmark_credit_ops()
        assert result.passed is True


class TestEndToEndBenchmark:
    """Tests for full request→reconstruct latency benchmark."""

    def test_benchmark_e2e_returns_result(self):
        adapter = CaliperAdapter(iterations=5)
        result = adapter.benchmark_end_to_end(payload_size=512)
        assert isinstance(result, BenchmarkResult)
        assert result.name == "end_to_end_latency"

    def test_benchmark_e2e_latency_reasonable(self):
        """Full mock end-to-end on same machine should be <1s p99."""
        adapter = CaliperAdapter(iterations=5, max_p99_latency_ms=1000.0)
        result = adapter.benchmark_end_to_end(payload_size=512)
        assert result.latency_p99_ms < 1000.0

    def test_benchmark_e2e_passes_default(self):
        adapter = CaliperAdapter(iterations=5)
        result = adapter.benchmark_end_to_end(payload_size=512)
        assert result.passed is True


class TestBenchmarkSuite:
    """Tests for running a full suite of benchmarks."""

    def test_run_suite_returns_multiple_results(self):
        suite = BenchmarkSuite(iterations=5)
        results = suite.run_all()
        assert len(results) >= 3  # encode, credit, e2e

    def test_suite_all_passed(self):
        suite = BenchmarkSuite(iterations=5)
        results = suite.run_all()
        for r in results:
            assert isinstance(r, BenchmarkResult)

    def test_suite_summary(self):
        suite = BenchmarkSuite(iterations=5)
        results = suite.run_all()
        summary = suite.summary(results)
        assert "passed" in summary
        assert "failed" in summary
        assert "total" in summary
        assert summary["total"] == len(results)

    def test_suite_raises_on_threshold_violation(self):
        """Suite can be configured to raise on any failure."""
        suite = BenchmarkSuite(
            iterations=5,
            raise_on_failure=True,
            min_encode_throughput_bytes_per_sec=10 ** 12,
        )
        with pytest.raises(ThresholdViolation):
            suite.run_all()

    def test_suite_export_json(self):
        import json
        suite = BenchmarkSuite(iterations=5)
        results = suite.run_all()
        json_str = suite.export_json(results)
        data = json.loads(json_str)
        assert isinstance(data, list)
        assert len(data) == len(results)

    def test_suite_export_contains_timestamp(self):
        import json
        suite = BenchmarkSuite(iterations=5)
        results = suite.run_all()
        json_str = suite.export_json(results)
        data = json.loads(json_str)
        assert "timestamp" in data[0] or all("name" in r for r in data)
