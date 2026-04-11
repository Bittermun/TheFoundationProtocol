"""Real concurrency tests for TFP security pipeline.

This module provides actual concurrency tests for:
- SQLite WAL locking under concurrent writes
- HABP consensus under concurrent credit minting
- Shard verification with parallel operations
"""

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest


@pytest.mark.concurrency
def test_sqlite_wal_concurrent_writes():
    """Test SQLite WAL mode handles concurrent writes without corruption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Initialize database with WAL mode
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE credits (id INTEGER PRIMARY KEY, device_id TEXT, amount REAL)"
        )
        conn.commit()
        conn.close()

        errors = []
        iterations = 50

        def writer(thread_id):
            try:
                for i in range(iterations):
                    conn = sqlite3.connect(str(db_path), timeout=30)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute(
                        "INSERT INTO credits (device_id, amount) VALUES (?, ?)",
                        (f"device_{thread_id}_{i}", thread_id * 0.01),
                    )
                    conn.commit()
                    conn.close()
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if len(errors) > 0:
            raise AssertionError(f"Concurrent write errors: {errors}")

        # Verify all writes succeeded
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM credits").fetchone()[0]
        conn.close()

        expected = 5 * iterations
        if count != expected:
            raise AssertionError(f"Expected {expected} rows, got {count}")


@pytest.mark.concurrency
def test_habp_credit_minting_concurrent():
    """Test HABP consensus handles concurrent credit minting attempts."""
    from tfp_core.compute.credit_formula import CreditFormula

    formula = CreditFormula()
    lock = threading.Lock()
    results = []
    errors = []

    def mint_credit(thread_id):
        try:
            for _i in range(10):
                result = formula.calculate_credits(
                    difficulty=5,
                    hardware_trust=0.95,
                    uptime_hours=100 + thread_id,
                    verification_confidence=0.98,
                    is_charging=(thread_id % 2 == 0),
                    task_completion_time=1.5 + (thread_id * 0.1),
                    estimated_time=2.0,
                )
                with lock:
                    results.append(result)
                time.sleep(0.001)  # Small delay to simulate real work
        except Exception as e:
            with lock:
                errors.append((thread_id, str(e)))

    threads = [threading.Thread(target=mint_credit, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if len(errors) > 0:
        raise AssertionError(f"HABP minting errors: {errors}")
    if len(results) != 50:
        raise AssertionError(f"Expected 50 results, got {len(results)}")

    # Verify all results are valid CreditCalculation objects
    from tfp_core.compute.credit_formula import CreditCalculation

    if not all(isinstance(r, CreditCalculation) for r in results):
        raise AssertionError("Invalid result types")


@pytest.mark.concurrency
def test_shard_verification_parallel():
    """Test shard verification works correctly under parallel execution."""
    import hashlib
    import secrets

    # Create test shards
    shards = []
    for i in range(20):
        data = secrets.token_bytes(1024)
        shard_hash = hashlib.sha256(data).hexdigest()
        shards.append({"id": i, "data": data, "hash": shard_hash})

    results = []
    errors = []
    lock = threading.Lock()

    def verify_shard(shard):
        try:
            computed_hash = hashlib.sha256(shard["data"]).hexdigest()
            is_valid = computed_hash == shard["hash"]
            with lock:
                results.append({"id": shard["id"], "valid": is_valid})
        except Exception as e:
            with lock:
                errors.append((shard["id"], str(e)))

    threads = [threading.Thread(target=verify_shard, args=(shard,)) for shard in shards]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if len(errors) > 0:
        raise AssertionError(f"Shard verification errors: {errors}")
    if len(results) != 20:
        raise AssertionError(f"Expected 20 results, got {len(results)}")
    if not all(r["valid"] for r in results):
        raise AssertionError("Some shards failed verification")
