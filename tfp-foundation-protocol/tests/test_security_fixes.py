# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_security_fixes.py

Tests for security hardening fixes applied in Phase 1:
1. Supply gossip validation (MAX_SUPPLY check + plausible value check)
2. EarnLog exception handling (narrowed to IntegrityError)
"""

import json
import os
import sqlite3
import threading

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest

from tfp_client.lib.bridges.nostr_bridge import NostrEvent
from tfp_client.lib.credit.ledger import MAX_SUPPLY
from tfp_demo.server import EarnLog, TaskStore


def test_supply_gossip_rejects_negative_values():
    """Gossip with negative total_minted should be rejected."""
    import tfp_demo.server as srv

    srv._gossiped_supply_total = 0

    event = NostrEvent.create(
        privkey=b"\xaa" * 32,
        kind=30081,
        content=json.dumps({"total_minted": -100}),
        tags=[],
    ).to_dict()

    srv._handle_supply_gossip_event(event)
    assert srv._gossiped_supply_total == 0


def test_supply_gossip_rejects_values_exceeding_max_supply():
    """Gossip with total_minted > MAX_SUPPLY should be rejected."""
    import tfp_demo.server as srv

    srv._gossiped_supply_total = 0

    event = NostrEvent.create(
        privkey=b"\xaa" * 32,
        kind=30081,
        content=json.dumps({"total_minted": MAX_SUPPLY + 1}),
        tags=[],
    ).to_dict()

    srv._handle_supply_gossip_event(event)
    assert srv._gossiped_supply_total == 0


def test_supply_gossip_rejects_implausibly_high_values():
    """Gossip with values far beyond local total + buffer should be rejected."""
    import tfp_demo.server as srv

    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)
    store.increment_total_minted(1000)

    original_task_store = srv._task_store
    srv._task_store = store
    srv._gossiped_supply_total = 1000

    event = NostrEvent.create(
        privkey=b"\xaa" * 32,
        kind=30081,
        content=json.dumps({"total_minted": 20000}),
        tags=[],
    ).to_dict()

    srv._handle_supply_gossip_event(event)
    assert srv._gossiped_supply_total == 1000

    srv._task_store = original_task_store


def test_earnlog_record_duplicate_returns_false():
    """Duplicate (device_id, task_id) should return False."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    earn_log = EarnLog(conn, db_lock)

    assert earn_log.record("test-device", "test-task") is True
    assert earn_log.record("test-device", "test-task") is False


def test_earnlog_record_propagates_non_constraint_errors():
    """Non-UNIQUE-constraint IntegrityErrors should be raised, not masked."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    earn_log = EarnLog(conn, db_lock)

    try:
        earn_log.record(None, "task")
        assert False, "Should have raised IntegrityError"
    except (sqlite3.IntegrityError, TypeError):
        pass


def test_earnlog_record_handles_connection_errors():
    """Connection errors should not be masked."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    earn_log = EarnLog(conn, db_lock)
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        earn_log.record("device", "task")
