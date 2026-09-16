"""The local hybrid-wallet simulation must conserve balances and reject unpaid spends."""

import pytest

from tfp_client.lib.credit.hybrid_wallet import HybridWallet


def funded():
    wallet = HybridWallet("sender")
    receipt = wallet.mint_compute_credits(50, b"proof")
    wallet.mint_pinning_credits({"content": 50})
    return wallet, receipt


def test_mixed_without_receipt_cannot_count_unspent_compute():
    wallet, _ = funded()
    before = wallet.get_balance()
    with pytest.raises(ValueError):
        wallet.spend(75, "mixed")
    assert wallet.get_balance() == before


def test_insufficient_mixed_spend_cannot_destroy_compute():
    wallet, receipt = funded()
    before = wallet.get_balance()
    with pytest.raises(ValueError):
        wallet.spend(101, "mixed", receipt)
    assert wallet.get_balance() == before
    assert wallet._compute_ledger.verify_spend(receipt)


@pytest.mark.parametrize("kind,amount", [("compute", 25), ("pinning", 25.5), ("mixed", 75.5)])
def test_transfer_preserves_each_balance_and_returns_record(kind, amount):
    wallet, receipt = funded()
    before = wallet.get_balance()
    recipient, record = wallet.transfer("receiver", amount, kind, receipt=receipt)
    after = wallet.get_balance()
    received = recipient.get_balance()
    assert after.total() == before.total() - amount
    assert received.total() == amount
    assert after.compute_credits + received.compute_credits == before.compute_credits
    assert after.pinning_credits + received.pinning_credits == before.pinning_credits
    assert record.tx_type == "transfer" and record.amount == amount


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1, 0])
def test_nonpositive_or_nonfinite_spend_is_rejected(amount):
    wallet, _ = funded()
    before = wallet.get_balance()
    with pytest.raises(ValueError):
        wallet.spend(amount, "pinning")
    assert wallet.get_balance() == before


def test_partial_compute_spend_and_transfer_keep_remaining_credits_usable():
    wallet, receipt = funded()
    wallet.spend(10, "compute", receipt)
    change = wallet.get_compute_receipts()[0]
    recipient, _ = wallet.transfer("receiver", 15, "compute", receipt=change)
    wallet.spend(25, "compute", wallet.get_compute_receipts()[0])
    recipient.spend(15, "compute", recipient.get_compute_receipts()[0])
    assert wallet.get_balance().compute_credits == 0
    assert recipient.get_balance().compute_credits == 0
