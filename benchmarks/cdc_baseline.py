# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Baseline Benchmarking for FastCDC Implementation

Establishes performance metrics for the new FastCDC implementation.
Measures throughput, chunk distribution, boundary stability, and memory usage.
"""

import json
import os
import random
import statistics
import sys
import time
import tracemalloc
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tfp_transport.cdc import CDCChunker, create_fastcdc_chunker


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    dataset_name: str
    data_size_bytes: int
    throughput_mbps: float
    chunk_count: int
    avg_chunk_size: float
    min_chunk_size: int
    max_chunk_size: int
    std_chunk_size: float
    boundary_stability: float  # % chunks surviving 5% edit
    memory_peak_mb: float
    duration_seconds: float


def generate_representative_datasets() -> Dict[str, bytes]:
    """
    Generate representative datasets matching TFP's content mix.
    
    Returns:
        Dict mapping dataset name to bytes
    """
    datasets = {}
    
    # 1. Educational text (Markdown documentation)
    text_content = b"# Educational Content\n\n" + b"This is educational content. " * 10000
    datasets["text_educational_100kb"] = text_content
    
    # 2. Health PDF simulation (binary with some structure)
    pdf_like = b"%PDF-1.4\n" + b"x" * 50000 + b"%%EOF"
    datasets["health_pdf_50kb"] = pdf_like
    
    # 3. Audio pattern (repeating segments)
    audio_pattern = b"WAV_HEADER" + b"\x00\x01\x02\x03" * 20000
    datasets["audio_pattern_80kb"] = audio_pattern
    
    # 4. Video-like data (I-frame simulation)
    video_like = b"FRAME_HEADER" + b"\xff" * 30000 + b"P_FRAME" + b"\xaa" * 30000
    datasets["video_like_60kb"] = video_like
    
    # 5. Mixed corpus (realistic mix)
    mixed = text_content[:30000] + pdf_like[:20000] + audio_pattern[:25000]
    datasets["mixed_corpus_75kb"] = mixed
    
    # 6. Large dataset (for memory testing)
    large_text = b"Large educational content. " * 500000
    datasets["large_text_10mb"] = large_text
    
    return datasets


def apply_random_edit(data: bytes, edit_ratio: float) -> bytes:
    """
    Apply random edits to data for boundary stability testing.
    
    Args:
        data: Original data
        edit_ratio: Fraction of bytes to modify (0.0-1.0)
    
    Returns:
        Modified data bytes
    """
    if edit_ratio <= 0:
        return data
    
    data_list = bytearray(data)
    num_edits = int(len(data) * edit_ratio)
    
    for _ in range(num_edits):
        idx = random.randint(0, len(data) - 1)
        data_list[idx] = random.randint(0, 255)
    
    return bytes(data_list)


def calculate_boundary_stability(chunks1: List[bytes], chunks2: List[bytes]) -> float:
    """
    Calculate boundary stability between two chunking results.
    
    Measures what percentage of chunks from the first chunking
    survive in the second chunking (by hash comparison).
    
    Args:
        chunks1: Chunks from original data
        chunks2: Chunks from modified data
    
    Returns:
        Stability ratio (0.0-1.0)
    """
    import hashlib
    
    hashes1 = [hashlib.sha256(c).hexdigest() for c in chunks1]
    hashes2 = [hashlib.sha256(c).hexdigest() for c in chunks2]
    
    # Count how many chunks from original survive in modified
    surviving = sum(1 for h in hashes1 if h in hashes2)
    
    return surviving / len(hashes1) if hashes1 else 0.0


def benchmark_fastcdc(
    data: bytes,
    dataset_name: str,
    min_chunk: int = 4096,
    max_chunk: int = 65536,
    avg_chunk: int = 16384,
) -> BenchmarkResult:
    """
    Benchmark FastCDC implementation.

    Args:
        data: Input data to chunk
        dataset_name: Name of dataset for reporting
        min_chunk: Minimum chunk size
        max_chunk: Maximum chunk size
        avg_chunk: Target average chunk size

    Returns:
        BenchmarkResult with metrics
    """
    chunker = create_fastcdc_chunker(
        min_chunk_kb=min_chunk // 1024,
        max_chunk_kb=max_chunk // 1024,
        avg_chunk_kb=avg_chunk // 1024,
    )
    
    # Start memory tracking
    tracemalloc.start()
    
    # Measure chunking performance
    start = time.perf_counter()
    chunks = list(chunker.chunk_data(data))
    duration = time.perf_counter() - start
    
    # Get memory peak
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Calculate chunk statistics
    chunk_sizes = [len(c) for c in chunks]
    
    # Measure boundary stability (5% random edit)
    modified = apply_random_edit(data, 0.05)
    chunks_mod = list(chunker.chunk_data(modified))
    stability = calculate_boundary_stability(chunks, chunks_mod)
    
    return BenchmarkResult(
        dataset_name=dataset_name,
        data_size_bytes=len(data),
        throughput_mbps=len(data) / (duration * 1e6) if duration > 0 else 0,
        chunk_count=len(chunks),
        avg_chunk_size=statistics.mean(chunk_sizes) if chunk_sizes else 0,
        min_chunk_size=min(chunk_sizes) if chunk_sizes else 0,
        max_chunk_size=max(chunk_sizes) if chunk_sizes else 0,
        std_chunk_size=statistics.stdev(chunk_sizes) if len(chunk_sizes) > 1 else 0,
        boundary_stability=stability,
        memory_peak_mb=peak / (1024 * 1024),
        duration_seconds=duration,
    )


def run_baseline_benchmarks() -> List[BenchmarkResult]:
    """
    Run baseline benchmarks on all representative datasets.

    Returns:
        List of BenchmarkResult objects
    """
    print("=== FastCDC Baseline Benchmarking ===")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print()

    datasets = generate_representative_datasets()
    results = []

    for name, data in datasets.items():
        print(f"Benchmarking: {name} ({len(data) / 1024:.1f} KB)...")

        try:
            result = benchmark_fastcdc(data, name)
            results.append(result)

            print(f"  Throughput: {result.throughput_mbps:.2f} MB/s")
            print(f"  Chunks: {result.chunk_count}")
            print(f"  Avg size: {result.avg_chunk_size / 1024:.1f} KB")
            print(f"  Boundary stability: {result.boundary_stability:.1%}")
            print(f"  Memory peak: {result.memory_peak_mb:.2f} MB")
            print()
        except Exception as e:
            print(f"  ERROR: {e}")
            print()

    return results


def save_baseline(results: List[BenchmarkResult], output_path: str):
    """
    Save baseline results to JSON file.
    
    Args:
        results: List of BenchmarkResult objects
        output_path: Path to save JSON file
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    
    data = {
        "timestamp": datetime.utcnow().isoformat(),
        "implementation": "FastCDC (Gear hash)",
        "results": [asdict(r) for r in results],
        "summary": {
            "avg_throughput_mbps": statistics.mean(r.throughput_mbps for r in results),
            "avg_boundary_stability": statistics.mean(r.boundary_stability for r in results),
            "total_data_size_mb": sum(r.data_size_bytes for r in results) / (1024 * 1024),
        }
    }
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"Baseline saved to: {output_path}")


def print_summary(results: List[BenchmarkResult]):
    """Print summary statistics across all benchmarks."""
    if not results:
        print("No results to summarize.")
        return
    
    print("\n=== Summary Statistics ===")
    print(f"Datasets tested: {len(results)}")
    print(f"Total data size: {sum(r.data_size_bytes for r in results) / (1024 * 1024):.2f} MB")
    print(f"Average throughput: {statistics.mean(r.throughput_mbps for r in results):.2f} MB/s")
    print(f"Average boundary stability: {statistics.mean(r.boundary_stability for r in results):.1%}")
    print(f"Average chunk count: {statistics.mean(r.chunk_count for r in results):.0f}")
    print()


if __name__ == "__main__":
    results = run_baseline_benchmarks()
    print_summary(results)
    
    # Save baseline
    baseline_path = os.path.join(
        os.path.dirname(__file__),
        "results",
        "cdc_baseline_fastcdc.json"
    )
    save_baseline(results, baseline_path)
