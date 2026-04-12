"""
tests/test_blob_store.py

Phase A — BlobStore unit tests.

Covers in-memory mode (blob_dir=None) and filesystem mode (blob_dir=Path).
All public BlobStore methods are exercised here; shard support is tested
separately for both storage modes.
"""

import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from pathlib import Path

from tfp_demo.server import BlobStore


# ---------------------------------------------------------------------------
# In-memory mode
# ---------------------------------------------------------------------------


class TestBlobStoreInMemory:
    def test_put_and_get_returns_same_bytes(self):
        bs = BlobStore(None)
        key = bs.put("abc123", b"hello bytes")
        assert bs.get(key) == b"hello bytes"

    def test_get_missing_returns_none(self):
        bs = BlobStore(None)
        assert bs.get("nothere") is None

    def test_exists_false_before_put(self):
        bs = BlobStore(None)
        assert not bs.exists("x")

    def test_exists_true_after_put(self):
        bs = BlobStore(None)
        key = bs.put("x", b"data")
        assert bs.exists(key)

    def test_put_overwrites_existing_key(self):
        bs = BlobStore(None)
        bs.put("k", b"v1")
        key = bs.put("k", b"v2")
        assert bs.get(key) == b"v2"

    def test_open_stream_yields_all_data(self):
        bs = BlobStore(None)
        data = b"a" * 1000
        key = bs.put("streamkey", data)
        chunks = list(bs.open_stream(key, chunk_size=100))
        assert b"".join(chunks) == data

    def test_open_stream_chunk_sizes_respected(self):
        bs = BlobStore(None)
        data = b"b" * 500
        key = bs.put("chunktest", data)
        chunks = list(bs.open_stream(key, chunk_size=200))
        # Expect ceil(500/200)=3 chunks; last may be smaller
        assert len(chunks) == 3
        assert chunks[0] == b"b" * 200
        assert chunks[1] == b"b" * 200
        assert chunks[2] == b"b" * 100

    def test_shard_put_and_get_roundtrip(self):
        bs = BlobStore(None)
        bs.put_shard("root123", 0, b"shard0")
        bs.put_shard("root123", 1, b"shard1")
        assert bs.get_shard("root123", 0) == b"shard0"
        assert bs.get_shard("root123", 1) == b"shard1"

    def test_get_shard_missing_returns_none(self):
        bs = BlobStore(None)
        assert bs.get_shard("nosuchroot", 0) is None

    def test_shard_count_zero_for_unknown(self):
        bs = BlobStore(None)
        assert bs.shard_count("nosuchroot") == 0

    def test_shard_count_correct(self):
        bs = BlobStore(None)
        for i in range(4):
            bs.put_shard("root", i, f"s{i}".encode())
        assert bs.shard_count("root") == 4

    def test_put_empty_bytes(self):
        bs = BlobStore(None)
        key = bs.put("empty", b"")
        assert bs.get(key) == b""


# ---------------------------------------------------------------------------
# Filesystem mode
# ---------------------------------------------------------------------------


class TestBlobStoreFilesystem:
    @pytest.fixture()
    def blob_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "blobs"
        d.mkdir()
        return d

    def test_put_creates_file(self, blob_dir):
        bs = BlobStore(blob_dir)
        bs.put("abc", b"hello")
        assert (blob_dir / "abc").exists()

    def test_get_reads_file(self, blob_dir):
        bs = BlobStore(blob_dir)
        key = bs.put("abc", b"hello")
        assert bs.get(key) == b"hello"

    def test_get_missing_returns_none(self, blob_dir):
        bs = BlobStore(blob_dir)
        assert bs.get(str(blob_dir / "nofile")) is None

    def test_exists(self, blob_dir):
        bs = BlobStore(blob_dir)
        assert not bs.exists(str(blob_dir / "missing"))
        key = bs.put("present", b"x")
        assert bs.exists(key)

    def test_open_stream_yields_all_data(self, blob_dir):
        bs = BlobStore(blob_dir)
        data = b"x" * 5000
        key = bs.put("bigfile", data)
        chunks = list(bs.open_stream(key, chunk_size=1000))
        assert b"".join(chunks) == data

    def test_shard_directories_created(self, blob_dir):
        bs = BlobStore(blob_dir)
        bs.put_shard("myhash", 0, b"sharddata")
        assert (blob_dir / "myhash.shards" / "shard_0000").exists()

    def test_shard_filesystem_roundtrip(self, blob_dir):
        bs = BlobStore(blob_dir)
        bs.put_shard("h", 3, b"three")
        assert bs.get_shard("h", 3) == b"three"

    def test_shard_count_filesystem(self, blob_dir):
        bs = BlobStore(blob_dir)
        for i in range(5):
            bs.put_shard("root", i, f"s{i}".encode())
        assert bs.shard_count("root") == 5

    def test_get_shard_missing_returns_none(self, blob_dir):
        bs = BlobStore(blob_dir)
        assert bs.get_shard("nope", 0) is None
