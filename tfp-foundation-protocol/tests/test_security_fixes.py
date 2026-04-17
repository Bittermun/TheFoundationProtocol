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
    store = TaskStore(conn, db_lock, clock_skew_tolerance=30)
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


def test_clock_skew_tolerance_allows_late_submissions():
    """Device with clock slightly behind server should still be able to submit results within tolerance."""
    import time
    from tfp_client.lib.compute.task_executor import generate_hash_preimage_task

    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    # Set clock skew tolerance to 30 seconds
    store = TaskStore(conn, db_lock, clock_skew_tolerance=30)

    # Create a task with a deadline 20 seconds ago (within tolerance)
    spec = generate_hash_preimage_task("skew-test", 1, b"seed")
    # Manually set deadline to 20 seconds in the past
    past_deadline = time.time() - 20
    conn.execute(
        """
        INSERT INTO tasks (task_id, task_type, difficulty, spec_json, status, created_at, deadline, credit_reward)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec.task_id,
            spec.task_type.value,
            spec.difficulty,
            json.dumps(spec.to_dict()),
            "open",
            time.time(),
            past_deadline,
            10,
        ),
    )
    conn.commit()

    # Should still be able to get the task (not reaped yet due to tolerance)
    task_row = store.get_task_row(spec.task_id)
    assert task_row is not None
    assert task_row["status"] == "open"


def test_clock_skew_tolerance_rejects_very_late_submissions():
    """Device with clock far behind server should be rejected (exceeds tolerance)."""
    import time
    from tfp_client.lib.compute.task_executor import generate_hash_preimage_task

    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    # Set clock skew tolerance to 30 seconds
    store = TaskStore(conn, db_lock, clock_skew_tolerance=30)

    # Create a task with a deadline 60 seconds ago (beyond tolerance)
    spec = generate_hash_preimage_task("skew-test-2", 1, b"seed")
    # Manually set deadline to 60 seconds in the past
    past_deadline = time.time() - 60
    conn.execute(
        """
        INSERT INTO tasks (task_id, task_type, difficulty, spec_json, status, created_at, deadline, credit_reward)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec.task_id,
            spec.task_type.value,
            spec.difficulty,
            json.dumps(spec.to_dict()),
            "open",
            time.time(),
            past_deadline,
            10,
        ),
    )
    conn.commit()

    # Reap expired tasks
    reaped = store.reap_expired_tasks()
    # Task should be reaped because it's beyond tolerance
    assert reaped >= 1

    # Verify task is now failed
    task_row = store.get_task_row(spec.task_id)
    assert task_row is not None
    assert task_row["status"] == "failed"


def test_state_transition_validation_rejects_invalid_transitions():
    """Invalid state transitions should be rejected with ValueError."""
    # Try to transition from completed to verifying (invalid)
    with pytest.raises(ValueError) as exc_info:
        store = TaskStore(
            sqlite3.connect(":memory:"), threading.RLock(), clock_skew_tolerance=30
        )
        store._validate_state_transition("test-task", "completed", "verifying")
    assert "Invalid state transition" in str(exc_info.value)

    # Try to transition from failed to open (invalid)
    with pytest.raises(ValueError) as exc_info:
        store = TaskStore(
            sqlite3.connect(":memory:"), threading.RLock(), clock_skew_tolerance=30
        )
        store._validate_state_transition("test-task", "failed", "open")
    assert "Invalid state transition" in str(exc_info.value)


def test_state_transition_validation_allows_valid_transitions():
    """Valid state transitions should be accepted."""
    store = TaskStore(
        sqlite3.connect(":memory:"), threading.RLock(), clock_skew_tolerance=30
    )

    # All valid transitions should not raise
    store._validate_state_transition("task-1", "open", "verifying")
    store._validate_state_transition("task-2", "open", "failed")
    store._validate_state_transition("task-3", "verifying", "completed")
    store._validate_state_transition("task-4", "verifying", "failed")
