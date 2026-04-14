# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_supply_cap.py

Verifies that the global 21,000,000-credit supply cap is enforced at the
ledger level (CreditLedger.mint) and at the server level (TaskStore).
"""

import hashlib
import os
import sqlite3
import threading

os.environ.setdefault("TFP_DB_PATH", ":memory:")

import pytest
from tfp_client.lib.credit.ledger import MAX_SUPPLY, CreditLedger, SupplyCapError
from tfp_demo.server import TaskStore


# ---------------------------------------------------------------------------
# CreditLedger-level tests
# ---------------------------------------------------------------------------


def test_max_supply_constant_is_21_million():
    """MAX_SUPPLY must equal 21,000,000."""
    assert MAX_SUPPLY == 21_000_000


def test_ledger_mint_raises_supply_cap_error_at_limit():
    """Minting beyond MAX_SUPPLY must raise SupplyCapError."""
    ledger = CreditLedger()
    ledger.set_network_total_minted(MAX_SUPPLY - 5)

    # Minting exactly 5 is still fine
    receipt = ledger.mint(5, hashlib.sha3_256(b"ok").digest())
    assert receipt.credits == 5

    # Reset and push over the cap
    ledger2 = CreditLedger()
    ledger2.set_network_total_minted(MAX_SUPPLY)
    with pytest.raises(SupplyCapError):
        ledger2.mint(1, hashlib.sha3_256(b"over").digest())


def test_ledger_mint_raises_when_partial_amount_would_exceed_cap():
    """Minting an amount that would exceed (not just equal) the cap is rejected."""
    ledger = CreditLedger()
    ledger.set_network_total_minted(MAX_SUPPLY - 9)
    with pytest.raises(SupplyCapError):
        ledger.mint(10, hashlib.sha3_256(b"exceed").digest())


def test_ledger_mint_exactly_at_cap_succeeds():
    """Minting exactly the remaining supply to reach the cap must succeed."""
    remaining = 50
    ledger = CreditLedger()
    ledger.set_network_total_minted(MAX_SUPPLY - remaining)
    receipt = ledger.mint(remaining, hashlib.sha3_256(b"last").digest())
    assert receipt.credits == remaining


def test_ledger_network_total_tracked_after_mint():
    """network_total_minted increases by exactly credits after each mint."""
    ledger = CreditLedger()
    ledger.set_network_total_minted(0)
    ledger.mint(100, hashlib.sha3_256(b"t1").digest())
    assert ledger.network_total_minted == 100
    ledger.mint(50, hashlib.sha3_256(b"t2").digest())
    assert ledger.network_total_minted == 150


# ---------------------------------------------------------------------------
# TaskStore-level tests
# ---------------------------------------------------------------------------


def test_task_store_increment_total_minted_enforces_cap():
    """TaskStore.increment_total_minted must raise SupplyCapError at the cap."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)

    # Manually push the supply ledger near the cap
    conn.execute(
        "UPDATE supply_ledger SET total_minted = ? WHERE id = 1",
        (MAX_SUPPLY,),
    )
    conn.commit()

    with pytest.raises(SupplyCapError):
        store.increment_total_minted(1)


def test_task_store_get_total_minted_reflects_increments():
    """get_total_minted returns the running total after each increment."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)

    assert store.get_total_minted() == 0
    store.increment_total_minted(10)
    assert store.get_total_minted() == 10
    store.increment_total_minted(25)
    assert store.get_total_minted() == 35


def test_task_store_stats_supply_fields():
    """stats() must expose total_minted, supply_cap, and supply_remaining."""
    conn = sqlite3.connect(":memory:")
    db_lock = threading.RLock()
    store = TaskStore(conn, db_lock)
    store.increment_total_minted(100)

    stats = store.stats()
    assert stats["total_minted"] == 100
    assert stats["supply_cap"] == MAX_SUPPLY
    assert stats["supply_remaining"] == MAX_SUPPLY - 100
