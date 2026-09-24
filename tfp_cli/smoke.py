# SPDX-License-Identifier: Apache-2.0
"""Verify the installed demo through a real HTTP server, then stop it."""

import argparse
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


@contextmanager
def demo_server(data_dir=None):
    """Own a loopback server and reap it; a supplied directory enables restart checks."""
    storage = ["--ephemeral"] if data_dir is None else ["--data-dir", str(data_dir)]
    process = subprocess.Popen(
        [sys.executable, "-m", "tfp_cli.main", "demo", *storage, "--no-browser", "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    lines = queue.Queue()
    log = []

    def collect() -> None:
        for line in process.stdout:
            log.append(line.rstrip())
            lines.put(line)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 30
        base = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Demo exited during startup: " + "\n".join(log[-15:]))
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            match = re.fullmatch(r"Open (http://127\.0\.0\.1:\d+)\s*", line)
            if match:
                base = match[1]
                break
        _check(base is not None, "Demo did not report its listening address within 30 seconds")

        while time.monotonic() < deadline:
            _check(process.poll() is None, "Demo stopped before it was ready")
            try:
                with urllib.request.urlopen(base + "/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Demo did not become ready within 30 seconds")

        yield base
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdout.close()


def run_smoke() -> dict:
    started = time.monotonic()
    with demo_server() as base:
        def call(method, path, body=None, message=None):
            headers = {"Content-Type": "application/json"}
            if message:
                headers["X-Device-Sig"] = hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()
            request = urllib.request.Request(
                base + path, method=method, headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read().decode()}") from exc

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            _check(b"Content commons" in response.read(), "The demo interface is missing from the installation")
        with urllib.request.urlopen(base + "/assets/app.js", timeout=5) as response:
            _check(response.status == 200, "Demo scripts are missing from the installation")

        secret = os.urandom(32)
        device_id = "smoke-" + secret.hex()[:12]
        enrollment = {"device_id": device_id, "puf_entropy_hex": secret.hex()}
        _check(call("POST", "/api/enroll", enrollment)["enrolled"], "Enrollment failed")
        call("POST", "/api/earn", {"device_id": device_id, "task_id": "smoke-allowance"}, f"{device_id}:smoke-allowance")
        original = "A small note, shared through Foundation.\nExact bytes matter: café, 水, 🌱."
        title = "Foundation round-trip check"
        published = call("POST", "/api/publish", {"device_id": device_id, "title": title, "text": original, "tags": ["smoke"]}, f"{device_id}:{title}")
        root = published["root_hash"]
        _check(hmac.compare_digest(root, hashlib.sha3_256(original.encode()).hexdigest()), "Published fingerprint does not match original bytes")
        listed = call("GET", "/api/content?tag=smoke")
        _check(root in [item["root_hash"] for item in listed["items"]], "Published note is absent from tag search")
        retrieved = call("GET", f"/api/get/{root}?device_id={device_id}", message=f"{device_id}:{root}")
        _check(retrieved["text"] == original and hmac.compare_digest(retrieved["sha3"], root), "Retrieved bytes differ from the published note")
        balance = call("GET", f"/api/device/{device_id}")["credits_balance"]
        _check(balance == 9, f"Expected 9 credits after one read, got {balance}")
        call("POST", "/api/enroll", enrollment)
        _check(call("GET", f"/api/device/{device_id}")["credits_balance"] == 9, "Re-enrollment erased credits")
        return {"passed": True, "checks": ["installed interface", "device enrollment", "demo allowance", "publish", "tag discovery", "exact UTF-8 round trip", "one-credit debit", "idempotent re-enrollment"], "root_hash": root, "remaining_credits": balance, "elapsed_seconds": round(time.monotonic() - started, 2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result")
    args = parser.parse_args(argv)
    try:
        result = run_smoke()
    except Exception as exc:
        if args.json:
            print(json.dumps({"passed": False, "error": str(exc)}))
        else:
            print(f"Demo check failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        print(f"PASS: {len(result['checks'])} checks completed in {result['elapsed_seconds']}s.")
        print("Published text and retrieved text match exactly. One read spent one credit.")
        print("The temporary server has stopped. To explore in your browser: tfp demo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
