#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Download/Retrieval Benchmark

Measures download/retrieval performance for video/audio content with comprehensive metrics.
Tests streaming, non-streaming, HTTP Range requests, and concurrent downloads.

Usage:
    # Start testbed first:
    docker compose -f docker-compose.testbed.yml up

    # Run benchmark:
    python benchmark_download_retrieval.py

    # Run with custom iterations:
    python benchmark_download_retrieval.py --iterations 5 --output results.json

    # Run against custom node:
    python benchmark_download_retrieval.py --node http://localhost:9002 --iterations 3
"""

import argparse
import asyncio
import importlib.util
import httpx
import json
import hmac
import hashlib
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
from pathlib import Path

# Add tfp-foundation-protocol to path for imports
sys.path.insert(0, str(Path(__file__).parent / "tfp-foundation-protocol"))

# Check Prometheus exporter availability
PROMETHEUS_AVAILABLE = (
    importlib.util.find_spec("tfp_core.audit.prometheus_exporter") is not None
)

# Try to import psutil for resource monitoring
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class DownloadMetrics:
    """Metrics for a single download operation."""

    download_type: str  # 'streaming' or 'non-streaming'
    file_size_bytes: int
    range_request: bool
    concurrency: int
    total_time_ms: float
    throughput_mbps: float
    success: bool
    error: Optional[str] = None
    credits_spent: int = 0
    chunk_count: int = 0

    def calculate_throughput(self) -> float:
        """Calculate throughput in MB/s."""
        if self.total_time_ms > 0:
            return (self.file_size_bytes / (1024 * 1024)) / (self.total_time_ms / 1000)
        return 0.0


@dataclass
class BenchmarkResult:
    """Aggregated results for a test scenario."""

    scenario_name: str
    download_type: str
    file_size_bytes: int
    range_request: bool
    concurrency: int
    iterations: int
    success_count: int
    fail_count: int
    avg_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    min_time_ms: float
    max_time_ms: float
    avg_throughput_mbps: float
    avg_credits_spent: float


@dataclass
class ResourceMetrics:
    """System resource metrics during benchmark."""

    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_read_mb: float
    disk_write_mb: float
    network_sent_mb: float
    network_recv_mb: float


class DownloadBenchmarkClient:
    """Client for TFP download benchmark operations."""

    def __init__(self, base_url: str = "http://localhost:9001"):
        self.base_url = base_url.rstrip("/")
        self.device_id: Optional[str] = None
        self.puf_entropy: Optional[bytes] = None
        self._client = httpx.Client(
            timeout=30.0,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def close(self):
        """Explicitly close the httpx client."""
        if hasattr(self, "_client") and self._client is not None:
            try:
                self._client.close()
            except Exception:
                # Log but don't raise - close() should be safe to call
                pass
            finally:
                self._client = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False  # Don't suppress exceptions

    def __del__(self):
        """Cleanup httpx client on deletion (fallback)."""
        self.close()

    def enroll(self, device_id: str = "benchmark-download-001") -> bool:
        """Enroll a device for testing."""
        self.device_id = device_id
        try:
            # Generate PUF entropy
            self.puf_entropy = hashlib.sha256(device_id.encode()).digest()

            # Enroll
            payload = {
                "device_id": device_id,
                "puf_entropy": self.puf_entropy.hex(),
            }

            response = self._client.post(
                f"{self.base_url}/api/enroll",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = response.json()
            return result.get("enrolled", False)
        except Exception as e:
            print(f"Enroll failed: {e}")
            return False

    def earn_credits(self, task_count: int = 10) -> int:
        """Earn credits by completing tasks."""
        earned = 0
        for _ in range(task_count):
            try:
                payload = {
                    "device_id": self.device_id,
                    "puf_entropy": self.puf_entropy.hex(),
                }

                response = self._client.post(
                    f"{self.base_url}/api/earn",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                result = response.json()
                credits = result.get("credits", 0)
                earned += credits
            except Exception as e:
                print(f"Earn failed: {e}")
                break
        return earned

    def _sign(self, message: bytes) -> str:
        """Sign a message with HMAC-SHA3-256."""
        if not self.puf_entropy:
            return ""
        return hmac.new(self.puf_entropy, message, hashlib.sha3_256).hexdigest()

    def publish_content(
        self, data: bytes, title: str = "Benchmark Content", tags: List[str] = None
    ) -> str:
        """Publish content to download later."""
        if tags is None:
            tags = ["benchmark", "download-test"]

        try:
            sig = self._sign(data)

            # Use httpx's multipart support
            files = {"content": ("content.bin", data, "application/octet-stream")}
            data_dict = {
                "device_id": self.device_id,
                "title": title,
                "tags": json.dumps(tags),
            }

            response = self._client.post(
                f"{self.base_url}/api/publish",
                files=files,
                data=data_dict,
                headers={"X-Device-Sig": sig, "X-Device-Id": self.device_id},
            )
            result = response.json()
            return result.get("root_hash", "")
        except Exception as e:
            print(f"Publish failed: {e}")
            raise

    def download_content(
        self, root_hash: str, stream: bool = True, range_header: Optional[str] = None
    ) -> DownloadMetrics:
        """Download content and measure performance."""
        start = time.perf_counter()
        chunk_count = 0
        success = False
        error = None
        data = b""  # Initialize before try block to avoid NameError

        try:
            params = {"stream": str(stream).lower(), "device_id": self.device_id}
            headers = {}
            if range_header:
                headers["Range"] = range_header

            response = self._client.get(
                f"{self.base_url}/api/get/{root_hash}", params=params, headers=headers
            )

            # Check response status
            status = response.status_code
            if status not in (200, 206):
                raise Exception(f"Unexpected status: {status}")

            # Read data and count chunks
            data = response.content
            if data:
                chunk_count = len(data) // (64 * 1024)  # 64KB chunks
                if len(data) % (64 * 1024) != 0:
                    chunk_count += 1
            else:
                chunk_count = 0

            success = True

        except Exception as e:
            error = str(e)
            success = False

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Calculate throughput
        throughput = 0.0
        if success and elapsed_ms > 0:
            throughput = (len(data) / (1024 * 1024)) / (elapsed_ms / 1000)

        return DownloadMetrics(
            download_type="streaming" if stream else "non-streaming",
            file_size_bytes=len(data) if success else 0,
            range_request=range_header is not None,
            concurrency=1,
            total_time_ms=elapsed_ms,
            throughput_mbps=throughput,
            success=success,
            error=error,
            credits_spent=1
            if success
            else 0,  # Only spend credits on successful downloads
            chunk_count=chunk_count,
        )

    async def download_concurrent(
        self, root_hash: str, concurrency: int, stream: bool = True
    ) -> List[DownloadMetrics]:
        """Download content concurrently with error handling."""

        async def single_download():
            return await asyncio.to_thread(
                self.download_content, root_hash, stream=stream
            )

        tasks = [single_download() for _ in range(concurrency)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed metrics
        final_results = []
        for r in results:
            if isinstance(r, Exception):
                final_results.append(
                    DownloadMetrics(
                        download_type="streaming" if stream else "non-streaming",
                        file_size_bytes=0,
                        range_request=False,
                        concurrency=concurrency,
                        total_time_ms=0,
                        throughput_mbps=0,
                        success=False,
                        error=str(r),
                        credits_spent=0,
                        chunk_count=0,
                    )
                )
            else:
                final_results.append(r)
        return final_results

    def download_with_range(
        self, root_hash: str, range_start: int, range_end: int, stream: bool = True
    ) -> DownloadMetrics:
        """Download content with HTTP Range header."""
        range_header = f"bytes={range_start}-{range_end}"
        return self.download_content(
            root_hash, stream=stream, range_header=range_header
        )


def percentile(data: List[float], p: float) -> float:
    """Calculate percentile with interpolation for small samples."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def get_resource_metrics() -> ResourceMetrics:
    """Get current system resource metrics."""
    if not PSUTIL_AVAILABLE:
        return ResourceMetrics(
            cpu_percent=0.0,
            memory_percent=0.0,
            memory_mb=0.0,
            disk_read_mb=0.0,
            disk_write_mb=0.0,
            network_sent_mb=0.0,
            network_recv_mb=0.0,
        )

    process = psutil.Process()
    cpu_percent = process.cpu_percent(interval=0.1)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)
    memory_percent = process.memory_percent()

    io_counters = process.io_counters() if hasattr(process, "io_counters") else None
    disk_read_mb = io_counters.read_bytes / (1024 * 1024) if io_counters else 0
    disk_write_mb = io_counters.write_bytes / (1024 * 1024) if io_counters else 0

    net_io = psutil.net_io_counters()
    network_sent_mb = net_io.bytes_sent / (1024 * 1024)
    network_recv_mb = net_io.bytes_recv / (1024 * 1024)

    return ResourceMetrics(
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        memory_mb=memory_mb,
        disk_read_mb=disk_read_mb,
        disk_write_mb=disk_write_mb,
        network_sent_mb=network_sent_mb,
        network_recv_mb=network_recv_mb,
    )


def run_benchmark(
    client: DownloadBenchmarkClient,
    file_sizes: List[int],
    concurrency_levels: List[int],
    iterations: int,
    warmup_iterations: int = 5,
) -> List[BenchmarkResult]:
    """Run the download benchmark."""
    results = []

    print("\n=== Download Benchmark ===")
    print(f"Iterations: {iterations} (warmup: {warmup_iterations})")
    print(f"File sizes: {[f'{s / 1024:.0f}KB' for s in file_sizes]}")
    print(f"Concurrency levels: {concurrency_levels}")

    # Enroll and earn credits
    print("\nEnrolling device and earning credits...")
    if not client.enroll():
        print("Failed to enroll device")
        return results

    credits = client.earn_credits(50)
    print(f"Earned {credits} credits")
    if credits == 0:
        print("ERROR: Failed to earn credits, cannot proceed with benchmark")
        return results
    if credits < 50:
        print(
            f"WARNING: Only earned {credits} credits, may be insufficient for all tests"
        )

    for file_size in file_sizes:
        # Generate test data using os.urandom for better performance
        data = os.urandom(file_size)

        # Publish content
        print(f"\nPublishing {file_size / 1024:.0f}KB content...")
        root_hash = client.publish_content(
            data, title=f"Benchmark {file_size / 1024:.0f}KB"
        )
        if not root_hash:
            print(f"Failed to publish {file_size / 1024:.0f}KB content")
            continue
        print(f"Published: {root_hash[:16]}")

        # Wait for background processing with retry logic
        max_wait = 10.0
        start = time.time()
        content_ready = False
        while time.time() - start < max_wait:
            try:
                # Try to fetch metadata to check if content is ready
                test_download = client.download_content(root_hash, stream=False)
                if test_download.success:
                    content_ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not content_ready:
            print(f"WARNING: Content may not be ready after {max_wait}s")

        for concurrency in concurrency_levels:
            for stream_mode in [True, False]:
                if concurrency > 1 and not stream_mode:
                    continue  # Only test non-streaming with single download

                scenario_name = f"{file_size / 1024:.0f}KB_{'streaming' if stream_mode else 'non-streaming'}_concurrency{concurrency}"

                print(f"\n--- {scenario_name} ---")

                all_metrics = []

                # Warmup iterations
                if warmup_iterations > 0:
                    print(f"Warmup ({warmup_iterations} iterations)...")
                    if concurrency == 1:
                        for _ in range(warmup_iterations):
                            metrics = client.download_content(
                                root_hash, stream=stream_mode
                            )
                            all_metrics.append(metrics)
                    else:
                        # Run all warmup iterations in single async call
                        async def warmup_downloads():
                            tasks = [
                                client.download_concurrent(
                                    root_hash, concurrency, stream_mode
                                )
                                for _ in range(warmup_iterations)
                            ]
                            results = await asyncio.gather(*tasks)
                            return [item for sublist in results for item in sublist]

                        warmup_results = asyncio.run(warmup_downloads())
                        all_metrics.extend(warmup_results)

                # Benchmark iterations
                print(f"Benchmark ({iterations} iterations)...")
                if concurrency == 1:
                    for i in range(iterations):
                        metrics = client.download_content(root_hash, stream=stream_mode)
                        all_metrics.append(metrics)
                        success_count = sum(1 for m in all_metrics if m.success)
                        print(
                            f"  Iteration {i + 1}/{iterations}: Success {success_count}/{len(all_metrics)}"
                        )
                else:
                    # Run all benchmark iterations in single async call
                    async def benchmark_downloads():
                        tasks = [
                            client.download_concurrent(
                                root_hash, concurrency, stream_mode
                            )
                            for _ in range(iterations)
                        ]
                        results = await asyncio.gather(*tasks)
                        return [item for sublist in results for item in sublist]

                    benchmark_results = asyncio.run(benchmark_downloads())
                    all_metrics.extend(benchmark_results)

                    success_count = sum(1 for m in all_metrics if m.success)
                    print(
                        f"  Completed {iterations} iterations: Success {success_count}/{len(all_metrics)}"
                    )

                # Calculate aggregates
                successful_metrics = [m for m in all_metrics if m.success]
                if not successful_metrics:
                    print("  All iterations failed!")
                    continue

                times = [m.total_time_ms for m in successful_metrics]
                throughputs = [m.calculate_throughput() for m in successful_metrics]
                credits_spent = [m.credits_spent for m in successful_metrics]

                result = BenchmarkResult(
                    scenario_name=scenario_name,
                    download_type="streaming" if stream_mode else "non-streaming",
                    file_size_bytes=file_size,
                    range_request=False,
                    concurrency=concurrency,
                    iterations=iterations,
                    success_count=len(successful_metrics),
                    fail_count=len(all_metrics) - len(successful_metrics),
                    avg_time_ms=statistics.mean(times),
                    p50_time_ms=statistics.median(times),
                    p95_time_ms=percentile(times, 0.95),
                    p99_time_ms=percentile(times, 0.99),
                    min_time_ms=min(times),
                    max_time_ms=max(times),
                    avg_throughput_mbps=statistics.mean(throughputs),
                    avg_credits_spent=statistics.mean(credits_spent),
                )

                results.append(result)

                print(f"  Avg time: {result.avg_time_ms:.1f}ms")
                print(
                    f"  p50/p95/p99: {result.p50_time_ms:.1f}ms / {result.p95_time_ms:.1f}ms / {result.p99_time_ms:.1f}ms"
                )
                print(f"  Throughput: {result.avg_throughput_mbps:.2f} MB/s")
                print(f"  Success rate: {result.success_count}/{result.iterations}")

        # Range request tests for large files (1MB+)
        if file_size >= 1048576:  # 1MB
            range_scenarios = [
                ("first_25%", 0, file_size // 4),
                ("middle_50%", file_size // 4, file_size * 3 // 4),
                ("last_25%", file_size * 3 // 4, file_size - 1),
            ]

            for range_name, range_start, range_end in range_scenarios:
                scenario_name = f"{file_size / 1024:.0f}KB_streaming_range_{range_name}"

                print(f"\n--- {scenario_name} ---")

                all_metrics = []

                # Warmup iterations
                if warmup_iterations > 0:
                    print(f"Warmup ({warmup_iterations} iterations)...")
                    for _ in range(warmup_iterations):
                        metrics = client.download_with_range(
                            root_hash, range_start, range_end, stream=True
                        )
                        all_metrics.append(metrics)

                # Benchmark iterations
                print(f"Benchmark ({iterations} iterations)...")
                for i in range(iterations):
                    metrics = client.download_with_range(
                        root_hash, range_start, range_end, stream=True
                    )
                    all_metrics.append(metrics)

                    success_count = sum(1 for m in all_metrics if m.success)
                    print(
                        f"  Iteration {i + 1}/{iterations}: Success {success_count}/{len(all_metrics)}"
                    )

                # Calculate aggregates
                successful_metrics = [m for m in all_metrics if m.success]
                if not successful_metrics:
                    print("  All iterations failed!")
                    continue

                times = [m.total_time_ms for m in successful_metrics]
                throughputs = [m.calculate_throughput() for m in successful_metrics]
                credits_spent = [m.credits_spent for m in successful_metrics]

                result = BenchmarkResult(
                    scenario_name=scenario_name,
                    download_type="streaming",
                    file_size_bytes=range_end - range_start + 1,
                    range_request=True,
                    concurrency=1,
                    iterations=iterations,
                    success_count=len(successful_metrics),
                    fail_count=len(all_metrics) - len(successful_metrics),
                    avg_time_ms=statistics.mean(times),
                    p50_time_ms=statistics.median(times),
                    p95_time_ms=percentile(times, 0.95),
                    p99_time_ms=percentile(times, 0.99),
                    min_time_ms=min(times),
                    max_time_ms=max(times),
                    avg_throughput_mbps=statistics.mean(throughputs),
                    avg_credits_spent=statistics.mean(credits_spent),
                )

                results.append(result)

                print(f"  Avg time: {result.avg_time_ms:.1f}ms")
                print(
                    f"  p50/p95/p99: {result.p50_time_ms:.1f}ms / {result.p95_time_ms:.1f}ms / {result.p99_time_ms:.1f}ms"
                )
                print(f"  Throughput: {result.avg_throughput_mbps:.2f} MB/s")
                print(f"  Success rate: {result.success_count}/{result.iterations}")

    return results


def main():
    parser = argparse.ArgumentParser(description="TFP Download/Retrieval Benchmark")
    parser.add_argument(
        "--node", default="http://localhost:9001", help="Testbed node URL"
    )
    parser.add_argument(
        "--iterations", type=int, default=3, help="Number of iterations per scenario"
    )
    parser.add_argument("--warmup", type=int, default=5, help="Warmup iterations")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument(
        "--file-sizes",
        nargs="+",
        type=int,
        default=[102400, 524288, 1048576, 10485760],
        help="File sizes in bytes (default: 100KB, 512KB, 1MB, 10MB)",
    )
    parser.add_argument(
        "--concurrency",
        nargs="+",
        type=int,
        default=[1, 4, 8],
        help="Concurrency levels (default: 1, 4, 8)",
    )

    args = parser.parse_args()

    client = DownloadBenchmarkClient(base_url=args.node)

    # Get initial resource metrics
    initial_resources = get_resource_metrics()
    print(
        f"Initial resources: CPU {initial_resources.cpu_percent:.1f}%, Memory {initial_resources.memory_mb:.1f}MB"
    )

    # Run benchmark
    results = run_benchmark(
        client=client,
        file_sizes=args.file_sizes,
        concurrency_levels=args.concurrency,
        iterations=args.iterations,
        warmup_iterations=args.warmup,
    )

    # Get final resource metrics
    final_resources = get_resource_metrics()
    print(
        f"\nFinal resources: CPU {final_resources.cpu_percent:.1f}%, Memory {final_resources.memory_mb:.1f}MB"
    )

    # Print summary
    print("\n=== Benchmark Summary ===")
    for result in results:
        print(f"\n{result.scenario_name}:")
        print(f"  Avg throughput: {result.avg_throughput_mbps:.2f} MB/s")
        print(
            f"  p50/p95/p99 latency: {result.p50_time_ms:.1f}ms / {result.p95_time_ms:.1f}ms / {result.p99_time_ms:.1f}ms"
        )
        print(f"  Success rate: {result.success_count}/{result.iterations}")
        print(f"  Avg credits spent: {result.avg_credits_spent:.1f}")

    # Save results if requested
    if args.output:
        output_data = {
            "node": args.node,
            "iterations": args.iterations,
            "warmup_iterations": args.warmup,
            "file_sizes": args.file_sizes,
            "concurrency_levels": args.concurrency,
            "results": [asdict(r) for r in results],
            "resources": {
                "initial": asdict(initial_resources),
                "final": asdict(final_resources),
            },
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
