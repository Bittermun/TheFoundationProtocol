#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
30-Second TFP Demo

One command to see TFP in action:
    python demo_30sec.py

What it does:
1. Starts in-memory server
2. Enrolls a demo device
3. Publishes sample content
4. Retrieves the content
5. Shows timing metrics
"""

import subprocess
import sys
import time
import json
import urllib.request
import urllib.error


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def wait_for_server(url, timeout=30):
    """Wait for server to become ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.URLError:
            time.sleep(0.5)
    return False


def api_call(method, path, data=None, headers=None):
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def main():
    log("=" * 60)
    log("TFP 30-Second Demo")
    log("=" * 60)

    # Step 1: Start server in background
    log("Starting TFP demo server...")
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

    # Wait for server
    if not wait_for_server("http://localhost:8000/health"):
        log("ERROR: Server failed to start")
        server_proc.terminate()
        return 1
    log("✓ Server ready on http://localhost:8000")

    try:
        # Step 2: Enroll device
        log("Enrolling demo device...")
        device_id = "demo-device-001"
        puf_entropy = "a" * 64  # Demo entropy
        result = api_call(
            "POST",
            "/api/enroll",
            {"device_id": device_id, "puf_entropy_hex": puf_entropy},
        )
        if "error" in result:
            log(f"Enroll failed: {result['error']}")
            return 1
        log(f"✓ Device enrolled: {device_id}")

        # Step 3: Publish content
        log("Publishing sample content...")
        import hmac
        import hashlib

        message = f"{device_id}:Demo Content".encode()
        entropy_bytes = bytes.fromhex(puf_entropy)
        sig = hmac.new(entropy_bytes, message, hashlib.sha256).hexdigest()

        start = time.time()
        result = api_call(
            "POST",
            "/api/publish",
            {
                "device_id": device_id,
                "title": "Demo Content",
                "text": "This is a 30-second demo of TFP content publishing!",
                "tags": ["demo", "30sec"],
            },
            headers={"X-Device-Sig": sig},
        )
        publish_time = (time.time() - start) * 1000

        if "error" in result:
            log(f"Publish failed: {result['error']}")
            return 1

        content_hash = result.get("root_hash", "unknown")
        log(f"✓ Content published in {publish_time:.0f}ms")
        log(f"  Hash: {content_hash[:16]}...")

        # Step 4: Earn credits (required before retrieve)
        log("Earning demo credits...")
        task_id = "demo-task-001"
        earn_sig = hmac.new(
            entropy_bytes, f"{device_id}:{task_id}".encode(), hashlib.sha256
        ).hexdigest()
        result = api_call(
            "POST",
            "/api/earn",
            {"device_id": device_id, "task_id": task_id},
            headers={"X-Device-Sig": earn_sig},
        )
        if "error" in result:
            log(f"Earn failed: {result['error']}")
            log("Continuing anyway for demo...")
        else:
            log(f"✓ Credits earned: {result.get('credits_earned', 0)}")

        # Step 5: Retrieve content
        log("Retrieving content...")
        start = time.time()
        result = api_call("GET", f"/api/get/{content_hash}?device_id={device_id}")
        retrieve_time = (time.time() - start) * 1000

        if "error" in result:
            log(f"Retrieve failed: {result['error']}")
            return 1

        log(f"✓ Content retrieved in {retrieve_time:.0f}ms")
        log(f"  Title: {result.get('title', 'N/A')}")
        log(f"  Size: {len(result.get('text', ''))} chars")

        # Step 5: Check status
        status = api_call("GET", "/api/status")
        log("Node status:")
        log(f"  Version: {status.get('version', 'N/A')}")
        log(f"  Total supply: {status.get('total_supply', 0)} credits")
        log(f"  Enrolled devices: {status.get('total_enrolled', 0)}")

        # Summary
        log("=" * 60)
        log("Demo complete!")
        log("=" * 60)
        log(f"Publish time: {publish_time:.0f}ms")
        log(f"Retrieve time: {retrieve_time:.0f}ms")
        log(f"Total time: {publish_time + retrieve_time:.0f}ms")
        log("")
        log("Next steps:")
        log("  - Open http://localhost:8000 for PWA demo")
        log("  - Run: python -m tfp_cli.main join --device-id my-laptop")
        log("  - See README.md for more examples")

    finally:
        log("Shutting down server...")
        server_proc.terminate()
        server_proc.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main())
