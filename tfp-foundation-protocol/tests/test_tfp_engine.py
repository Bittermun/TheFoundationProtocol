import hashlib
import pytest
from unittest.mock import MagicMock, call

from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import CreditLedger, Receipt
from tfp_client.lib.ndn.adapter import NDNAdapter, Interest, Data
from tfp_client.lib.lexicon.adapter import Content


def test_request_content_returns_content():
    client = TFPClient()
    content = client.request_content("abc123")
    assert isinstance(content, Content)
    assert content.data is not None


def test_request_content_calls_ndn_interest():
    mock_ndn = MagicMock(spec=NDNAdapter)
    mock_ndn.create_interest.return_value = Interest(name="/tfp/content/abc123")
    mock_ndn.express_interest.return_value = Data(name="/tfp/content/abc123", content=b"data")
    client = TFPClient(ndn=mock_ndn)
    client.request_content("abc123")
    mock_ndn.create_interest.assert_called_once_with("abc123")


def test_request_content_deducts_credits():
    ledger = CreditLedger()
    client = TFPClient(ledger=ledger)
    initial_balance = ledger.balance
    client.request_content("abc123")
    assert len(client._spends) == 1
    assert ledger.balance > initial_balance


def test_submit_compute_task_returns_receipt():
    client = TFPClient()
    receipt = client.submit_compute_task("task_hash_abc")
    assert isinstance(receipt, Receipt)


def test_submit_compute_task_mints_credits():
    ledger = CreditLedger()
    client = TFPClient(ledger=ledger)
    client.submit_compute_task("task_hash_abc")
    assert ledger.balance == 10


def test_prove_access_returns_proof():
    client = TFPClient()
    proof = client.prove_access("abc123", b"my_secret_claim")
    assert isinstance(proof, bytes)
    assert len(proof) > 0
