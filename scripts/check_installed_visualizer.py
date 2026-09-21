# SPDX-License-Identifier: Apache-2.0
"""Run with the wheel's Python using -I -B, from outside the source checkout.

Checks installed assets, real HTTP ingestion/search, and persistence across
server recreation. An audit hook rejects Python file writes to the environment;
this models a read-only installation, not an operating-system security sandbox.
"""

import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

import tfp_client
import tfp_demo

import tfp_core_v4
from tfp_core_v4.visualizer_server import (
    create_visualizer_server,
    get_static_assets_dir,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def reject_installation_writes(event, args):
    if event == "open":
        path, mode, flags = args
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        writing = writing or bool(mode and any(c in mode for c in "wax+"))
    elif event in {"os.mkdir", "os.remove", "os.rmdir"}:
        path, writing = args[0], True
    else:
        return
    if (
        writing and isinstance(path, (str, bytes, os.PathLike))
        and Path(os.fsdecode(path)).resolve().is_relative_to(Path(sys.prefix).resolve())
    ):
        raise PermissionError(f"Attempted write inside installed environment: {path}")


@contextmanager
def running_server():
    server, port = create_visualizer_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        check(not thread.is_alive(), "Server thread did not stop")


def request(base, path, payload=None, *, raw=False):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        check(response.status == 200, f"HTTP failure at {path}")
        body = response.read()
    return body if raw else json.loads(body)


def main():
    prefix = Path(sys.prefix).resolve()
    for module in (tfp_client, tfp_core_v4, tfp_demo):
        check(Path(module.__file__).resolve().is_relative_to(prefix), f"Source import: {module.__file__}")
    assets = get_static_assets_dir()
    check(assets.is_relative_to(prefix), f"Source assets: {assets}")
    sys.addaudithook(reject_installation_writes)

    with tempfile.TemporaryDirectory(prefix="tfp-installed-visualizer-") as directory:
        storage = Path(directory)
        os.environ["TFP_VISUALIZER_DATA_DIR"] = str(storage)
        with running_server() as base:
            for filename in ("visualizer.html", "legacy_visualizer_v1.html", "acoustic_receiver.html"):
                check(b"<!doctype html>" in request(base, "/" + filename, raw=True).lower(), filename)
            check(request(base, "/api/protocol-state")["status"] == "ok", "Telemetry unavailable")
            check(request(base, "/api/articles")["count"] >= 6, "Seed articles missing")
            result = request(base, "/api/ingest", {
                "format": "markdown",
                "text": "# Installed runtime persistence\n\n## Body\n\nA unique wheelprobequartz marker. Café 水.",
            })
            check(result["ok"], "Ingestion failed")
            root = result["bundle"]["merkle_root"]
            original = request(base, "/api/article?root=" + root, raw=True)
            check(b"wheelprobequartz" in original, "Ingested content missing")
        check((storage / "articles" / f"{root}.json").is_file(), "Article was not persisted in user storage")
        with running_server() as base:
            recovered = request(base, "/api/article?root=" + root, raw=True)
            check(recovered == original, "Persisted article changed after restart")
            results = request(base, "/api/search?q=wheelprobequartz")["results"]
            check(any(result["merkle_root"] == root for result in results), "Persisted body missing from search")
    print("PASS: installed visualizer assets, HTTP ingestion, restart and search; no installation writes")


if __name__ == "__main__":
    main()
