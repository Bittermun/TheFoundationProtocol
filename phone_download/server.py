# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from __future__ import annotations

import http.server
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Tuple

# Repo root
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from tfp_core_v4.cdc import ContentDefinedChunker  # noqa: E402
from tfp_core_v4.merkle import MerkleTree  # noqa: E402

log = logging.getLogger("tfp.image_share")


class SharedImageState:
    """Thread-safe state manager for the latest shared photo."""

    def __init__(self, storage_dir: Path | str | None = None):
        self._lock = threading.RLock()
        if storage_dir is None:
            storage_dir = Path(__file__).resolve().parent
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.filename: str | None = None
        self.content_type: str = "image/jpeg"
        self.size_bytes: int = 0
        self.chunk_count: int = 0
        self.merkle_root: str = ""
        self.timestamp: float = 0.0
        self.image_bytes: bytes = b""

        cached_meta = self.storage_dir / "latest_meta.json"
        cached_img = self.storage_dir / "shared_image.bin"
        if cached_meta.exists() and cached_img.exists():
            try:
                meta = json.loads(cached_meta.read_text(encoding="utf-8"))
                self.filename = meta.get("filename")
                self.content_type = meta.get("content_type", "image/jpeg")
                self.size_bytes = meta.get("size_bytes", 0)
                self.chunk_count = meta.get("chunk_count", 0)
                self.merkle_root = meta.get("merkle_root", "")
                self.timestamp = meta.get("timestamp", 0.0)
                self.image_bytes = cached_img.read_bytes()
            except Exception as e:
                log.warning(f"Failed to restore cached image: {e}")

    def set_image(self, filename: str, content_type: str, data: bytes) -> dict[str, Any]:
        """Ingest image data through FastCDC chunking and Merkle authentication."""
        chunker = ContentDefinedChunker(min_size=128, max_size=2048, target_size=512)
        chunks = chunker.chunk(data)
        tree = MerkleTree(chunks)
        root_hex = tree.root_hex

        with self._lock:
            self.filename = filename
            self.content_type = content_type or "image/jpeg"
            self.size_bytes = len(data)
            self.chunk_count = len(chunks)
            self.merkle_root = root_hex
            self.timestamp = time.time()
            self.image_bytes = data

            # Persist to storage_dir
            try:
                (self.storage_dir / "shared_image.bin").write_bytes(data)
                meta = self.get_metadata()
                (self.storage_dir / "latest_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            except OSError as exc:
                log.warning(f"Could not persist image cache: {exc}")

            return {
                "status": "ok",
                "filename": self.filename,
                "size_bytes": self.size_bytes,
                "chunk_count": self.chunk_count,
                "merkle_root": self.merkle_root,
                "timestamp": self.timestamp,
            }

    def get_metadata(self) -> dict[str, Any]:
        with self._lock:
            return {
                "has_image": bool(self.image_bytes),
                "filename": self.filename or "",
                "content_type": self.content_type,
                "size_bytes": self.size_bytes,
                "chunk_count": self.chunk_count,
                "merkle_root": self.merkle_root,
                "timestamp": self.timestamp,
            }

    def get_image_data(self) -> Tuple[bytes, str]:
        with self._lock:
            return self.image_bytes, self.content_type


GLOBAL_STATE = SharedImageState()


class ImageShareHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP Request handler supporting static files, image uploads, and live polling."""

    def __init__(self, *args, directory: str | None = None, **kwargs):
        if directory is None:
            directory = str(Path(__file__).resolve().parent)
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        url_path = self.path.split("?")[0]
        if url_path == "/api/latest-image":
            meta = GLOBAL_STATE.get_metadata()
            payload = json.dumps(meta).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)
            return

        if url_path == "/api/image-data":
            data, content_type = GLOBAL_STATE.get_image_data()
            if not data:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No image uploaded yet.")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
            return

        super().do_GET()

    def do_POST(self):
        url_path = self.path.split("?")[0]
        if url_path == "/api/upload-image":
            content_length = int(self.headers.get("Content-Length", 0))
            content_type = self.headers.get("Content-Type", "")

            if content_length <= 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Empty payload"}')
                return

            body = self.rfile.read(content_length)

            filename = "photo.jpg"
            image_bytes = b""
            detected_type = "image/jpeg"

            if "multipart/form-data" in content_type:
                boundary_marker = content_type.split("boundary=")[-1].strip()
                if boundary_marker.startswith('"') and boundary_marker.endswith('"'):
                    boundary_marker = boundary_marker[1:-1]
                boundary = ("--" + boundary_marker).encode("ascii")
                parts = body.split(boundary)
                for part in parts:
                    if b"Content-Disposition:" in part and b"filename=" in part:
                        headers_raw, _, part_data = part.partition(b"\r\n\r\n")
                        if part_data.endswith(b"\r\n"):
                            part_data = part_data[:-2]
                        
                        m = re.search(r'filename="([^"]+)"', headers_raw.decode("latin1", errors="ignore"))
                        if m:
                            filename = Path(m.group(1)).name
                        
                        ctype_match = re.search(r'Content-Type:\s*([^\r\n]+)', headers_raw.decode("latin1", errors="ignore"), re.IGNORECASE)
                        if ctype_match:
                            detected_type = ctype_match.group(1).strip()
                        
                        image_bytes = part_data
                        break
            else:
                image_bytes = body
                if "png" in content_type:
                    detected_type = "image/png"
                    filename = "photo.png"

            if not image_bytes:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Failed to extract image bytes"}')
                return

            res = GLOBAL_STATE.set_image(filename=filename, content_type=detected_type, data=image_bytes)
            resp_payload = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp_payload)
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server(port: int = 8888, host: str = "0.0.0.0"):
    server_address = (host, port)
    httpd = http.server.ThreadingHTTPServer(server_address, ImageShareHandler)
    print(f"[TFP] Symmetric Image Share Server running at http://{host}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[TFP] Server stopped.")


if __name__ == "__main__":
    port = 8888
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port=port)
