# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import hashlib

import pytest
from tfp_client.lib.credit.ledger import CreditLedger, Receipt


def make_proof(label: str) -> bytes:
    return hashlib.sha3_256(label.encode()).digest()


def test_mint_creates_receipt():
    ledger = CreditLedger()
    receipt = ledger.mint(10, make_proof("p1"))
    assert isinstance(receipt, Receipt)
    assert len(receipt.chain_hash) > 0


def test_chain_integrity_after_multiple_mints():
    ledger = CreditLedger()
    for i in range(5):
        ledger.mint(i + 1, make_proof(f"p{i}"))
    chain = ledger.chain
    assert len(chain) == 5
    # Verify each block references the previous
    prev = b"\x00" * 32
    for i, block in enumerate(chain):
        proof = make_proof(f"p{i}")
        credits = i + 1
        expected = hashlib.sha3_256(prev + proof + credits.to_bytes(8, "big")).digest()
        assert block == expected
        prev = block


def test_verify_spend_valid_receipt():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("valid"))
    assert ledger.verify_spend(receipt) is True


def test_verify_spend_tampered_receipt():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("valid"))
    tampered = Receipt(chain_hash=b"\xff" * 32, credits=5)
    assert ledger.verify_spend(tampered) is False


def test_mint_zero_credits_raises():
    ledger = CreditLedger()
    with pytest.raises(ValueError):
        ledger.mint(0, make_proof("zero"))
    with pytest.raises(ValueError):
        ledger.mint(-1, make_proof("neg"))


def test_chain_is_append_only():
    ledger = CreditLedger()
    lengths = []
    for i in range(5):
        ledger.mint(i + 1, make_proof(f"p{i}"))
        lengths.append(len(ledger.chain))
    assert lengths == sorted(lengths)
    assert lengths == list(range(1, 6))


# ── spend() tests ─────────────────────────────────────────────────────────────


def test_spend_deducts_balance():
    ledger = CreditLedger()
    receipt = ledger.mint(10, make_proof("earn"))
    assert ledger.balance == 10
    ledger.spend(3, receipt)
    assert ledger.balance == 7


def test_spend_to_zero_balance():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("earn"))
    ledger.spend(5, receipt)
    assert ledger.balance == 0


def test_spend_insufficient_balance_raises():
    ledger = CreditLedger()
    receipt = ledger.mint(2, make_proof("earn"))
    with pytest.raises(ValueError, match="insufficient balance"):
        ledger.spend(3, receipt)


def test_spend_invalid_receipt_raises():
    ledger = CreditLedger()
    ledger.mint(10, make_proof("earn"))
    fake_receipt = Receipt(chain_hash=b"\xab" * 32, credits=10)
    with pytest.raises(ValueError, match="not in chain"):
        ledger.spend(1, fake_receipt)


def test_spend_zero_credits_raises():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("earn"))
    with pytest.raises(ValueError):
        ledger.spend(0, receipt)


def test_spend_does_not_alter_chain():
    ledger = CreditLedger()
    receipt = ledger.mint(10, make_proof("earn"))
    chain_before = ledger.chain
    ledger.spend(1, receipt)
    assert ledger.chain == chain_before


# ── Merkle tree export tests ──────────────────────────────────────────────────


def test_export_merkle_root_empty_chain():
    ledger = CreditLedger()
    root = ledger.export_merkle_root()
    assert isinstance(root, bytes)
    assert len(root) == 32


def test_export_merkle_root_single_block():
    ledger = CreditLedger()
    ledger.mint(1, make_proof("p0"))
    root = ledger.export_merkle_root()
    assert isinstance(root, bytes)
    assert len(root) == 32
    # Single node: root == the only chain block
    assert root == ledger.chain[0]


def test_export_merkle_root_two_blocks():
    ledger = CreditLedger()
    ledger.mint(1, make_proof("p0"))
    ledger.mint(2, make_proof("p1"))
    root = ledger.export_merkle_root()
    chain = ledger.chain
    expected = hashlib.sha3_256(chain[0] + chain[1]).digest()
    assert root == expected


def test_export_merkle_root_is_deterministic():
    ledger = CreditLedger()
    for i in range(4):
        ledger.mint(i + 1, make_proof(f"p{i}"))
    assert ledger.export_merkle_root() == ledger.export_merkle_root()


def test_export_merkle_root_changes_on_new_block():
    ledger = CreditLedger()
    ledger.mint(1, make_proof("p0"))
    root1 = ledger.export_merkle_root()
    ledger.mint(2, make_proof("p1"))
    root2 = ledger.export_merkle_root()
    assert root1 != root2


# ── audit_trail() tests ───────────────────────────────────────────────────────


def test_audit_trail_empty():
    ledger = CreditLedger()
    trail = ledger.audit_trail()
    assert trail == []


def test_audit_trail_structure():
    ledger = CreditLedger()
    for i in range(3):
        ledger.mint(i + 1, make_proof(f"p{i}"))
    trail = ledger.audit_trail()
    assert len(trail) == 3
    for i, entry in enumerate(trail):
        assert entry["index"] == i
        assert isinstance(entry["block_hash"], bytes)
        assert isinstance(entry["hex"], str)
        assert entry["hex"] == entry["block_hash"].hex()


def test_audit_trail_matches_chain():
    ledger = CreditLedger()
    for i in range(5):
        ledger.mint(i + 1, make_proof(f"p{i}"))
    chain = ledger.chain
    trail = ledger.audit_trail()
    for i, entry in enumerate(trail):
        assert entry["block_hash"] == chain[i]
