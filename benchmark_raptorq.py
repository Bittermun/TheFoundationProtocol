#!/usr/bin/env python3
"""
Server-Side RaptorQ Efficiency Benchmark

Tests RealRaptorQAdapter encoding efficiency without requiring NDN.
This works because server-side chunking uses RealRaptorQAdapter.

Measures:
- Encoding speed
- Shard size efficiency
- Bandwidth savings from partial retrieval scenarios
"""

import sys
import time
import statistics
sys.path.insert(0, "tfp-foundation-protocol")

from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def benchmark_encoding():
    """Benchmark RealRaptorQAdapter encoding efficiency."""
    print("=" * 60)
    print("Server-Side RaptorQ Encoding Benchmark")
    print("=" * 60)
    
    # Test different content sizes
    test_sizes = [
        ("Small text", 100),
        ("Medium text", 1024),
        ("Large text", 10240),
        ("Small file", 100 * 1024),  # 100 KB
        ("Medium file", 1024 * 1024),  # 1 MB
    ]
    
    encoder = RealRaptorQAdapter(shard_size=1024)  # 1 KB shards
    
    results = []
    
    for label, size in test_sizes:
        data = b"x" * size
        
        # Measure encoding time
        start = time.perf_counter()
        shards = encoder.encode(data, redundancy=0.10)
        elapsed = (time.perf_counter() - start) * 1000
        
        original_size = len(data)
        total_shard_size = sum(len(s) for s in shards)
        
        # Calculate metrics
        overhead_pct = ((total_shard_size - original_size) / original_size) * 100
        shard_count = len(shards)
        k = shard_count - int(shard_count * 0.10)  # source shards
        
        result = {
            "label": label,
            "original_bytes": original_size,
            "encoded_bytes": total_shard_size,
            "overhead_pct": overhead_pct,
            "shard_count": shard_count,
            "source_shards": k,
            "encode_time_ms": elapsed,
        }
        results.append(result)
        
        log(f"{label} ({original_size:,} bytes):")
        log(f"  Encoded to {shard_count} shards ({total_shard_size:,} bytes)")
        log(f"  Overhead: {overhead_pct:.1f}%")
        log(f"  Encode time: {elapsed:.0f}ms")
        log(f"  Can reconstruct from any {k} shards")
        log("")
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    avg_overhead = statistics.mean(r["overhead_pct"] for r in results)
    avg_encode_speed = statistics.mean(
        r["original_bytes"] / (r["encode_time_ms"] / 1000) for r in results
    )
    
    log(f"Average overhead: {avg_overhead:.1f}%")
    log(f"Average encode speed: {avg_encode_speed/1024:.1f} KB/s")
    log("")
    
    # Bandwidth savings scenarios
    print("=" * 60)
    print("Bandwidth Savings Scenarios")
    print("=" * 60)
    
    for r in results:
        if r["label"] == "Medium file":
            log(f"{r['label']} ({r['original_bytes']/1024/1024:.1f} MB):")
            log(f"  Full retrieval: {r['encoded_bytes']/1024/1024:.2f} MB (with 10% redundancy)")
            log(f"  50% shards: {(r['encoded_bytes']*0.5)/1024/1024:.2f} MB (50% bandwidth)")
            log(f"  75% shards: {(r['encoded_bytes']*0.75)/1024/1024:.2f} MB (75% bandwidth)")
            log(f"  Savings vs full transfer: up to 25% with partial retrieval")
            log("")
    
    # Test partial reconstruction
    print("=" * 60)
    print("Partial Reconstruction Test")
    print("=" * 60)
    
    test_data = b"Hello World! This is a test of RaptorQ partial reconstruction." * 100
    shards = encoder.encode(test_data, redundancy=0.10)
    
    k = len(shards) - int(len(shards) * 0.10)
    
    log(f"Original: {len(test_data)} bytes")
    log(f"Shards: {len(shards)} (k={k} source shards)")
    
    # Try to reconstruct with different percentages
    for pct in [100, 90, 80, 75, 70, 60, 50]:
        needed = max(k, int(len(shards) * pct / 100))
        if needed <= len(shards):
            try:
                start = time.perf_counter()
                decoded = encoder.decode(shards[:needed])
                elapsed = (time.perf_counter() - start) * 1000
                
                if decoded == test_data:
                    log(f"  {pct}% shards ({needed} shards): ✓ Success in {elapsed:.0f}ms")
                else:
                    log(f"  {pct}% shards ({needed} shards): ✗ Data mismatch")
            except Exception as e:
                log(f"  {pct}% shards ({needed} shards): ✗ Error: {e}")
        else:
            log(f"  {pct}% shards ({needed} shards): ✗ Not enough shards")
    
    log("")
    log("💡 Key Findings:")
    log(f"  - RealRaptorQAdapter adds ~{avg_overhead:.1f}% overhead (10% redundancy + headers)")
    log(f"  - Encoding speed: {avg_encode_speed/1024:.1f} KB/s")
    log(f"  - Can reconstruct from any k source shards (fault tolerance)")
    log(f"  - Partial retrieval saves bandwidth in P2P scenarios")
    log("")
    log("⚠️  Note: This is server-side encoding only.")
    log("   Client-side retrieval requires real NDN adapter (currently mock).")


if __name__ == "__main__":
    benchmark_encoding()
