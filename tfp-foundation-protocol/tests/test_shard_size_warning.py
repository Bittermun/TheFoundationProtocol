"""
tests/test_shard_size_warning.py

Tests for the TFP_SHARD_SIZE_KB < 64 KB operational guard.

Verifies:
- Starting the server with TFP_SHARD_SIZE_KB < 64 (and TFP_ENABLE_CHUNKING=1)
  emits a WARNING-level log message.
- Starting with TFP_SHARD_SIZE_KB >= 64 does NOT emit the warning.
- Starting with TFP_SHARD_SIZE_KB=0 (codec default) does NOT emit the warning.
- Starting with TFP_ENABLE_CHUNKING=0 does NOT emit the warning even if
  TFP_SHARD_SIZE_KB < 64.
"""

import logging
import os

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from fastapi.testclient import TestClient

from tfp_demo.server import app


def test_small_shard_size_warning_emitted(monkeypatch, caplog):
    """TFP_SHARD_SIZE_KB=32 with TFP_ENABLE_CHUNKING=1 must emit a WARNING."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "32")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert any(
        "TFP_SHARD_SIZE_KB=32" in r.message and r.levelno >= logging.WARNING
        for r in caplog.records
    )


def test_small_shard_size_warning_value_1(monkeypatch, caplog):
    """TFP_SHARD_SIZE_KB=1 (very small) must emit a WARNING."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "1")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert any("TFP_SHARD_SIZE_KB" in r.message for r in caplog.records)


def test_shard_size_64_no_warning(monkeypatch, caplog):
    """TFP_SHARD_SIZE_KB=64 (lower boundary) must NOT emit the guard warning."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "64")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    # No warning should mention the shard size guard
    assert not any(
        "below 64 KB" in r.message for r in caplog.records
    )


def test_shard_size_256_no_warning(monkeypatch, caplog):
    """TFP_SHARD_SIZE_KB=256 must NOT emit the guard warning."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "256")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert not any("below 64 KB" in r.message for r in caplog.records)


def test_shard_size_0_no_warning(monkeypatch, caplog):
    """TFP_SHARD_SIZE_KB=0 (codec default) must NOT emit the guard warning."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "0")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "1")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    assert not any("below 64 KB" in r.message for r in caplog.records)


def test_small_shard_size_chunking_disabled_no_warning(monkeypatch, caplog):
    """TFP_ENABLE_CHUNKING=0 suppresses the guard warning even with small shard size."""
    monkeypatch.setenv("TFP_SHARD_SIZE_KB", "16")
    monkeypatch.setenv("TFP_ENABLE_CHUNKING", "0")
    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass
    # Guard should not fire when chunking is disabled
    assert not any("below 64 KB" in r.message for r in caplog.records)
