"""
tests/test_concurrency.py

Concurrency tests: verify the server data-layer is thread-safe under concurrent
access for the most security-sensitive operations.

Marked with @pytest.mark.concurrency so they can be selectively run by the CI
security job: ``pytest -m concurrency``
"""

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest

from tfp_demo.server import DeviceRegistry, EarnLog, TaskStore

pytestmark = pytest.mark.concurrency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> tuple[sqlite3.Connection, TaskStore]:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)
    return conn, store


def _output_hash(tag: str) -> str:
    import hashlib
    return hashlib.sha3_256(tag.encode()).hexdigest()


def _device_enroll(conn: sqlite3.Connection, device_id: str) -> None:
    reg = DeviceRegistry(conn, threading.RLock())
    reg.enroll(device_id, os.urandom(32))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_concurrent_enrollments_no_crash():
    """Concurrent enroll calls for distinct devices must all succeed without errors."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_lock = threading.RLock()
    reg = DeviceRegistry(conn, db_lock)
    errors = []
    lock = threading.Lock()

    def enroll(i):
        try:
            reg.enroll(f"conc-device-{i}", os.urandom(32))
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=enroll, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent enroll failures: {errors}"
    assert reg.count() == 20


def test_concurrent_earn_log_idempotent():
    """
    EarnLog.record() with UNIQUE(device_id, task_id) must return True exactly
    once across all racing threads and False for every subsequent duplicate.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_lock = threading.RLock()
    earn_log = EarnLog(conn, db_lock)
    device_id = "conc-earn-dev"
    task_id = "conc-task-abc"

    results = []
    lock = threading.Lock()

    def record():
        # Returns False if already recorded (duplicate), True on first insert
        result = earn_log.record(device_id, task_id)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=record) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r is True]
    assert len(successes) == 1, (
        f"EarnLog must record exactly once across {len(threads)} concurrent "
        f"calls; got successes={successes}"
    )


def test_concurrent_submit_result_duplicate_blocked():
    """
    Ten threads race to submit the same (task_id, device_id) pair.
    Exactly one must succeed; all others must raise HTTPException(409).
    The TaskStore._lock + rowcount guard prevents self-mint.
    """
    from fastapi import HTTPException

    conn, store = _make_store()
    task_spec = store.create_task("hash_preimage", difficulty=1, seed=os.urandom(16))
    task_id = task_spec.task_id
    device_id = "self-mint-racer"
    output_hash = _output_hash("fixed-output")

    successes = []
    rejections = []
    errors = []
    lock = threading.Lock()

    def submit():
        try:
            result = store.submit_result(
                task_id=task_id,
                device_id=device_id,
                output_hash=output_hash,
                exec_time_s=0.05,
            )
            with lock:
                successes.append(result)
        except HTTPException as exc:
            with lock:
                rejections.append(exc.status_code)
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=submit) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Unexpected errors: {errors}"
    assert len(successes) == 1, (
        f"Expected exactly 1 accepted submission, got {len(successes)}; "
        f"rejections={rejections}"
    )
    assert all(code == 409 for code in rejections), (
        f"All rejections must be 409, got: {rejections}"
    )


def test_three_devices_concurrent_consensus():
    """
    Three distinct devices race to submit results for the same task.
    At most one thread can trigger consensus (verified=True).
    No double-mint — credits_earned must not be positive for more than one.
    """
    conn, store = _make_store()
    task_spec = store.create_task("hash_preimage", difficulty=1, seed=os.urandom(16))
    task_id = task_spec.task_id
    output_hash = _output_hash("shared-output")

    results = []
    errors = []
    lock = threading.Lock()

    def submit(device_id):
        from fastapi import HTTPException

        try:
            r = store.submit_result(
                task_id=task_id,
                device_id=device_id,
                output_hash=output_hash,
                exec_time_s=0.05,
            )
            with lock:
                results.append(r)
        except HTTPException as exc:
            with lock:
                errors.append(exc.status_code)
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=submit, args=(f"habp-racer-{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    verified = [r for r in results if r.get("verified")]
    credit_earners = [r for r in results if r.get("credits_earned", 0) > 0]

    # At most one thread triggers consensus (the one that provides the 3rd proof)
    assert len(verified) <= 1, f"More than one consensus result: {results}"
    # Credits must be awarded only once
    assert len(credit_earners) <= 1, f"Credits awarded more than once: {results}"
    # All 3 submissions must have been recorded (no spurious errors)
    http_errors = [e for e in errors if isinstance(e, int) and e not in (409, 410)]
    assert not http_errors, f"Unexpected HTTP errors: {http_errors}"


def test_supply_cap_enforced_under_concurrent_mint():
    """
    Concurrent calls to increment_total_minted must not exceed MAX_SUPPLY.
    The TaskStore._lock ensures atomicity; the test fires 10 threads each
    trying to mint 3_000_000 credits (total attempt = 30_000_000 > 21_000_000 cap).
    """
    from tfp_client.lib.credit.ledger import MAX_SUPPLY, SupplyCapError

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)

    MINT_AMOUNT = 3_000_000
    NUM_THREADS = 10  # 10 × 3M = 30M > 21M cap

    successes = []
    cap_errors = []
    other_errors = []
    lock = threading.Lock()

    def try_mint():
        try:
            new_total = store.increment_total_minted(MINT_AMOUNT)
            with lock:
                successes.append(new_total)
        except SupplyCapError:
            with lock:
                cap_errors.append(True)
        except Exception as exc:
            with lock:
                other_errors.append(str(exc))

    threads = [threading.Thread(target=try_mint) for _ in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not other_errors, f"Unexpected errors: {other_errors}"
    # The final total must never exceed MAX_SUPPLY
    final_total = store.get_total_minted()
    assert final_total <= MAX_SUPPLY, (
        f"Supply cap violated: {final_total} > {MAX_SUPPLY}"
    )
    # At least one mint must succeed and at least one must be blocked
    assert successes, "No mints succeeded — cap test is misconfigured"
    assert cap_errors, "Cap was never hit — possible race condition in enforcement"

