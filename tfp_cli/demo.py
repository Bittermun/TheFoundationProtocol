# SPDX-License-Identifier: Apache-2.0
"""A predictable, loopback-only entry point for the local demo."""

import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def configure_demo(*, ephemeral: bool, data_dir: Path) -> None:
    """Keep demo data separate from existing nodes and disable external bridges."""
    if not ephemeral:
        data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        TFP_MODE="demo",
        TFP_DB_PATH=":memory:" if ephemeral else str(data_dir / "foundation.db"),
        TFP_DB_TYPE="sqlite",
        TFP_ENABLE_IPFS="0",
        TFP_ENABLE_NOSTR="0",
        TFP_NOSTR_PUBLISH_ENABLED="0",
        TFP_ENABLE_RAG="0",
        TFP_REAL_ADAPTERS="0",
        TFP_PEER_NODES="",
    )
    # Do not let a pre-existing node's optional paths leak into this demo.
    for key in ("TFP_BLOB_DIR", "TFP_DATABASE_URL", "TFP_REDIS_URL", "DATABASE_URL"):
        os.environ.pop(key, None)


def _open_when_ready(url: str, stopped: threading.Event) -> None:
    """Open only after this server has started responding."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not stopped.is_set():
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                if response.status == 200 and not stopped.is_set():
                    webbrowser.open(url)
                    return
        except (urllib.error.URLError, OSError):
            stopped.wait(0.25)


def run_demo(args) -> int:
    import uvicorn

    data_dir = Path(args.data_dir).expanduser().resolve()
    configure_demo(ephemeral=args.ephemeral, data_dir=data_dir)
    # Own the listening socket before opening a browser: never attach to another
    # service merely because it happens to answer /health on the same port.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
    except OSError as exc:
        listener.close()
        print(f"Could not start the demo on port {args.port}: {exc}")
        print("Choose another port, for example: tfp demo --port 8001")
        return 1
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    print(f"\nFoundation content commons\nOpen {url}", flush=True)
    print("Data: temporary (cleared on exit)" if args.ephemeral else f"Data: {data_dir}", flush=True)
    print("Local demo; external bridges are disabled. Press Ctrl+C to stop.\n", flush=True)
    stopped = threading.Event()
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, stopped), daemon=True).start()
    config = uvicorn.Config("tfp_demo.server:app", host="127.0.0.1", port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[listener])
    finally:
        stopped.set()
        listener.close()
    return 0 if server.started else 1
