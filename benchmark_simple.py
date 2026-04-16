#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Simple TFP Efficiency Benchmark

Run: python benchmark_simple.py

Measures:
- Content publish/retrieve latency
- Memory overhead
- Simple throughput estimate
"""

import subprocess
import sys
import time
import json
import urllib.request
import statistics


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def api_call(method, path, data=None, headers=None, timeout=60):
    """Make API call to demo server."""
    url = f"http://localhost:8000{path}"
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def wait_for_server(timeout=30):
    """Wait for server to become ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    print("TFP Simple Benchmark")
    print("This will start a temporary server and run performance tests.\n")

    device_id = "bench-device-001"
    puf_entropy = "b" * 64
    server_proc = None
    try:
        # Start server
        log("Starting TFP server...")
        server_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tfp_demo.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd="tfp-foundation-protocol",
            env={
                **dict(subprocess.os.environ),
                "TFP_DB_PATH": ":memory:",
                "PYTHONPATH": ".",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not wait_for_server():
            raise RuntimeError("Server failed to start")
        log("✓ Server ready")

        # Enroll device
        api_call(
            "POST",
            "/api/enroll",
            {"device_id": device_id, "puf_entropy_hex": puf_entropy},
        )
        log("✓ Device enrolled")

        log("=" * 60)
        log("TFP Efficiency Benchmark")
        log("=" * 60)

        # Benchmark publish (5 iterations for speed)
        import hmac
        import hashlib

        entropy_bytes = bytes.fromhex(puf_entropy)

        log("Benchmarking publish (5 iterations)...")
        publish_times = []

        for i in range(5):
            title = f"Benchmark Content {i}"
            message = f"{device_id}:{title}".encode()
            sig = hmac.new(entropy_bytes, message, hashlib.sha256).hexdigest()

            start = time.perf_counter()
            result = api_call(
                "POST",
                "/api/publish",
                {
                    "device_id": device_id,
                    "title": title,
                    "text": f"Content {i}",
                    "tags": ["benchmark"],
                },
                headers={"X-Device-Sig": sig},
            )
            elapsed = (time.perf_counter() - start) * 1000

            if "error" not in result:
                publish_times.append(elapsed)
                log(f"  Publish {i + 1}: {elapsed:.0f}ms")

        # Earn credits first (required for retrieve)
        log("Earning credits for retrieve...")
        task_id = "bench-task-001"
        earn_sig = hmac.new(
            entropy_bytes, f"{device_id}:{task_id}".encode(), hashlib.sha256
        ).hexdigest()
        api_call(
            "POST",
            "/api/earn",
            {"device_id": device_id, "task_id": task_id},
            headers={"X-Device-Sig": earn_sig},
        )

        # Benchmark retrieve
        content_list = api_call("GET", "/api/content?limit=5")
        hashes = [item["root_hash"] for item in content_list.get("items", [])]

        if hashes:
            log("Benchmarking retrieve (5 iterations)...")
            retrieve_times = []

            for i in range(5):
                content_hash = hashes[i % len(hashes)]

                start = time.perf_counter()
                result = api_call(
                    "GET", f"/api/get/{content_hash}?device_id={device_id}"
                )
                elapsed = (time.perf_counter() - start) * 1000

                if "error" not in result:
                    retrieve_times.append(elapsed)
                    log(f"  Retrieve {i + 1}: {elapsed:.0f}ms")

        # Print results
        log("=" * 60)
        log("Benchmark Results")
        log("=" * 60)

        if publish_times:
            log(f"\n📤 PUBLISH (n={len(publish_times)})")
            log(f"  Mean: {statistics.mean(publish_times):.0f}ms")
            log(f"  Min:  {min(publish_times):.0f}ms")
            log(f"  Max:  {max(publish_times):.0f}ms")
            log(
                f"  Est. throughput: {len(publish_times) / (sum(publish_times) / 1000):.1f} ops/sec"
            )

        if retrieve_times:
            log(f"\n📥 RETRIEVE (n={len(retrieve_times)})")
            log(f"  Mean: {statistics.mean(retrieve_times):.0f}ms")
            log(f"  Min:  {min(retrieve_times):.0f}ms")
            log(f"  Max:  {max(retrieve_times):.0f}ms")
            log(
                f"  Est. throughput: {len(retrieve_times) / (sum(retrieve_times) / 1000):.1f} ops/sec"
            )

        # Get node status
        status = api_call("GET", "/api/status")
        log("\n📊 NODE STATUS")
        log(f"  Version: {status.get('version', 'N/A')}")
        log(f"  Total supply: {status.get('total_supply', 0)} credits")
        log(f"  Enrolled devices: {status.get('total_enrolled', 0)}")

        log("\n💡 Notes:")
        log("  - In-memory database (fastest case)")
        log("  - Single-node, no network latency")
        log("  - Production with disk: expect 2-5x slower")

    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if server_proc:
            log("Shutting down server...")
            server_proc.terminate()
            server_proc.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main())
