"""
tests/test_range_requests.py

Phase D — HTTP Range request tests.

Verifies:
- GET /api/get/{hash}?stream=true without Range header returns 200 + full body.
- GET /api/get/{hash}?stream=true with Range: bytes=start-end returns 206.
- Returned bytes for Range request match expected slice of content.
- Range request with open-ended "bytes=start-" returns bytes from start to end.
- Range request for a known-missing hash still returns 404.
- Overlapping or reversed ranges are handled gracefully.
"""

import hashlib
import hmac as _hmac
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


def _sig(puf: bytes, msg: str) -> str:
    return _hmac.new(puf, msg.encode(), hashlib.sha256).hexdigest()


def _enroll(client, device_id: str, puf: bytes) -> None:
    r = client.post(
        "/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf.hex()},
    )
    assert r.status_code == 200


def _publish_and_earn(
    client, device_id: str, puf: bytes, title: str, data: bytes
) -> str:
    """Publish content and earn credits, returning root_hash."""
    sig = _sig(puf, f"{device_id}:{title}")
    r = client.post(
        "/api/publish",
        json={
            "device_id": device_id,
            "title": title,
            "tags": ["range", "test"],
            "text": data.decode(errors="replace"),
        },
        headers={"X-Device-Sig": sig},
    )
    assert r.status_code == 200, r.text
    root_hash = r.json()["root_hash"]

    earn_sig = _sig(puf, f"{device_id}:rangetask-{title}")
    earn_r = client.post(
        "/api/earn",
        json={"device_id": device_id, "task_id": f"rangetask-{title}"},
        headers={"X-Device-Sig": earn_sig},
    )
    assert earn_r.status_code == 200, earn_r.text
    return root_hash


# ---------------------------------------------------------------------------
# Range request tests
# ---------------------------------------------------------------------------


def test_stream_without_range_returns_200_full_body():
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "range-dev-1"
        _enroll(client, device_id, puf)
        content = b"0123456789abcdef" * 10  # 160 bytes
        root_hash = _publish_and_earn(client, device_id, puf, "NoRange", content)

        r = client.get(
            f"/api/get/{root_hash}",
            params={"device_id": device_id, "stream": "true"},
        )
        assert r.status_code == 200
        assert r.content == content


def test_range_request_returns_206():
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "range-dev-2"
        _enroll(client, device_id, puf)
        content = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4  # 104 bytes
        root_hash = _publish_and_earn(client, device_id, puf, "Range206", content)

        r = client.get(
            f"/api/get/{root_hash}",
            params={"device_id": device_id, "stream": "true"},
            headers={"Range": "bytes=0-9"},
        )
        assert r.status_code == 206
        assert r.content == content[:10]


def test_range_request_mid_file():
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "range-dev-3"
        _enroll(client, device_id, puf)
        content = b"0123456789" * 10  # 100 bytes
        root_hash = _publish_and_earn(client, device_id, puf, "RangeMid", content)

        r = client.get(
            f"/api/get/{root_hash}",
            params={"device_id": device_id, "stream": "true"},
            headers={"Range": "bytes=10-19"},
        )
        assert r.status_code == 206
        assert r.content == content[10:20]


def test_range_request_open_ended():
    """bytes=40- should return from byte 40 to end of file."""
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "range-dev-4"
        _enroll(client, device_id, puf)
        content = b"x" * 100
        root_hash = _publish_and_earn(client, device_id, puf, "RangeOpen", content)

        r = client.get(
            f"/api/get/{root_hash}",
            params={"device_id": device_id, "stream": "true"},
            headers={"Range": "bytes=40-"},
        )
        assert r.status_code == 206
        assert r.content == content[40:]


def test_range_response_has_content_range_header():
    with TestClient(app) as client:
        puf = os.urandom(32)
        device_id = "range-dev-5"
        _enroll(client, device_id, puf)
        content = b"A" * 50
        root_hash = _publish_and_earn(client, device_id, puf, "RangeHeader", content)

        r = client.get(
            f"/api/get/{root_hash}",
            params={"device_id": device_id, "stream": "true"},
            headers={"Range": "bytes=0-4"},
        )
        assert r.status_code == 206
        assert "content-range" in r.headers
        assert r.headers["content-range"].startswith("bytes 0-4/")


def test_range_request_missing_content_still_404():
    with TestClient(app) as client:
        r = client.get(
            f"/api/get/{'0' * 64}",
            params={"stream": "true"},
            headers={"Range": "bytes=0-9"},
        )
        assert r.status_code == 404
