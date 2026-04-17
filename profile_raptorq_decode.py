#!/usr/bin/env python3
"""
Profile RaptorQ decoding performance to identify bottlenecks.
Tests decoding speed on various file sizes and redundancy levels.
"""

import time
import hashlib
import random
from pathlib import Path

# Add tfp-foundation-protocol to path
import sys
sys.path.insert(0, str(Path(__file__).parent / "tfp-foundation-protocol"))

from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter


def profile_decoding(data: bytes, redundancy: float = 0.05, loss_rate: float = 0.0) -> dict:
    """Profile a single decode operation with simulated packet loss."""
    adapter = RealRaptorQAdapter()
    
    # Encode first
    shards = adapter.encode(data, redundancy=redundancy)
    
    # Simulate packet loss by randomly dropping shards
    if loss_rate > 0:
        k = len(shards) - int(len(shards) * redundancy)  # Original source shards
        keep = int(k * (1 - loss_rate))  # Shards to keep after loss
        if keep < k:  # Only simulate loss if we have enough redundancy to recover
            random.shuffle(shards)
            shards = shards[:keep]
    
    start = time.perf_counter()
    decoded = adapter.decode(shards)
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    size_mb = len(data) / (1024 * 1024)
    throughput_mbps = size_mb / (elapsed_ms / 1000)
    
    return {
        "data_size_bytes": len(data),
        "data_size_mb": size_mb,
        "shard_count": len(shards),
        "redundancy": redundancy,
        "loss_rate": loss_rate,
        "elapsed_ms": elapsed_ms,
        "throughput_mbps": throughput_mbps,
        "success": decoded == data,
    }


def main():
    print("=" * 70)
    print("RaptorQ Decoding Performance Profiler")
    print("=" * 70)
    
    # Test data sizes: 100KB, 1MB, 10MB, 50MB, 100MB
    test_sizes = [
        (100 * 1024, "100KB"),
        (1024 * 1024, "1MB"),
        (10 * 1024 * 1024, "10MB"),
        (50 * 1024 * 1024, "50MB"),
        (100 * 1024 * 1024, "100MB"),
    ]
    
    # Test redundancy levels
    redundancies = [0.0, 0.05, 0.1]
    
    # Test with no loss (best case)
    loss_rates = [0.0]
    
    results = []
    
    for size_bytes, size_label in test_sizes:
        # Generate test data (pseudo-random but deterministic)
        data = hashlib.sha256(size_label.encode()).digest()
        data = data * (size_bytes // len(data) + 1)
        data = data[:size_bytes]
        
        print(f"\nTesting {size_label} ({size_bytes:,} bytes)...")
        
        for redundancy in redundancies:
            for loss_rate in loss_rates:
                print(f"  Redundancy {redundancy*100:.0f}% Loss {loss_rate*100:.0f}%...", end=" ", flush=True)
                
                try:
                    result = profile_decoding(data, redundancy, loss_rate)
                    results.append(result)
                    if result['success']:
                        print(f"{result['elapsed_ms']:.1f}ms ({result['throughput_mbps']:.2f} MB/s)")
                    else:
                        print(f"FAILED (decode mismatch)")
                except Exception as e:
                    print(f"ERROR: {e}")
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"{'Size':<10} {'Redundancy':<12} {'Time (ms)':<12} {'Throughput (MB/s)':<20}")
    print("-" * 70)
    
    for r in results:
        size_mb = r['data_size_mb']
        size_label = f"{size_mb:.1f}MB" if size_mb >= 1 else f"{size_mb*1024:.0f}KB"
        if r['success']:
            print(f"{size_label:<10} {r['redundancy']*100:>10.0f}% {r['elapsed_ms']:>10.1f} {r['throughput_mbps']:>18.2f}")
        else:
            print(f"{size_label:<10} {r['redundancy']*100:>10.0f} {'FAILED':>10}")
    
    # Calculate average throughput for 10MB+ files
    large_results = [r for r in results if r['data_size_bytes'] >= 10 * 1024 * 1024 and r['success']]
    if large_results:
        avg_throughput = sum(r['throughput_mbps'] for r in large_results) / len(large_results)
        print(f"\nAverage throughput for large files (>=10MB): {avg_throughput:.2f} MB/s")
    
    # Identify bottleneck
    print("\n" + "=" * 70)
    print("Analysis")
    print("=" * 70)
    
    if avg_throughput < 10:
        print("⚠️  DECODING IS A BOTTLENECK")
        print(f"   Current throughput: {avg_throughput:.2f} MB/s")
        print("   Recommendation: Parallelize decoding with ProcessPoolExecutor")
    else:
        print("✓ Decoding performance is acceptable")
        print(f"   Current throughput: {avg_throughput:.2f} MB/s")


if __name__ == "__main__":
    main()
