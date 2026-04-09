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
    prev = b'\x00' * 32
    for i, block in enumerate(chain):
        proof = make_proof(f"p{i}")
        credits = i + 1
        expected = hashlib.sha3_256(prev + proof + credits.to_bytes(8, 'big')).digest()
        assert block == expected
        prev = block


def test_verify_spend_valid_receipt():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("valid"))
    assert ledger.verify_spend(receipt) is True


def test_verify_spend_tampered_receipt():
    ledger = CreditLedger()
    receipt = ledger.mint(5, make_proof("valid"))
    tampered = Receipt(chain_hash=b'\xff' * 32, credits=5)
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
