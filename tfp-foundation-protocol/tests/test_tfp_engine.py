# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import os
from unittest.mock import MagicMock

import pytest
from tfp_client.lib.core.tfp_engine import SecurityError, TFPClient
from tfp_client.lib.credit.ledger import CreditLedger, Receipt
from tfp_client.lib.identity.puf_enclave.enclave import PUFEnclave
from tfp_client.lib.lexicon.adapter import Content
from tfp_client.lib.ndn.adapter import Data, Interest, NDNAdapter
from tfp_client.lib.security.symbolic_preprocessor.preprocessor import (
    SymbolicPreprocessor,
)


def _client_with_credits(n_tasks: int = 1) -> tuple:
    """Return (client, ledger) with `n_tasks * 10` credits already minted."""
    ledger = CreditLedger()
    client = TFPClient(ledger=ledger)
    for i in range(n_tasks):
        client.submit_compute_task(f"task_hash_{i}")
    return client, ledger


def test_request_content_returns_content():
    client, _ = _client_with_credits()
    content = client.request_content("abc123")
    assert isinstance(content, Content)
    assert content.data is not None


def test_request_content_calls_ndn_interest():
    mock_ndn = MagicMock(spec=NDNAdapter)
    mock_ndn.create_interest.return_value = Interest(name="/tfp/content/abc123")
    mock_ndn.express_interest.return_value = Data(
        name="/tfp/content/abc123", content=b"data"
    )
    ledger = CreditLedger()
    client = TFPClient(ndn=mock_ndn, ledger=ledger)
    client.submit_compute_task("task_hash")
    client.request_content("abc123")
    mock_ndn.create_interest.assert_called_once_with("abc123")


def test_request_content_spends_credits():
    client, ledger = _client_with_credits()
    balance_after_earn = ledger.balance  # 10
    client.request_content("abc123")
    assert len(client._spends) == 1
    assert ledger.balance == balance_after_earn - 1  # spent 1 credit


def test_request_content_no_credits_raises():
    ledger = CreditLedger()
    client = TFPClient(ledger=ledger)
    with pytest.raises(ValueError, match="no earned credits"):
        client.request_content("abc123")


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


# ── Security gate: SymbolicPreprocessor ──────────────────────────────────────


def test_request_content_valid_recipe_passes():
    client, _ = _client_with_credits()
    preprocessor = SymbolicPreprocessor()
    client.preprocessor = preprocessor
    recipe = {"task_type": "inference", "params_hash": "a" * 64, "difficulty": 3}
    content = client.request_content("abc123", recipe=recipe)
    assert content is not None


def test_request_content_poisoned_recipe_raises():
    client, _ = _client_with_credits()
    client.preprocessor = SymbolicPreprocessor()
    poisoned = {"task_type": "inference", "params_hash": "a" * 64, "difficulty": -5}
    with pytest.raises(SecurityError, match="recipe validation failed"):
        client.request_content("abc123", recipe=poisoned)


def test_request_content_no_preprocessor_skips_validation():
    """Without a preprocessor, even a bad recipe dict is ignored."""
    client, _ = _client_with_credits()
    # No preprocessor set — should not raise
    poisoned = {"task_type": "inference", "params_hash": "a" * 64, "difficulty": -5}
    content = client.request_content("abc123", recipe=poisoned)
    assert content is not None


def test_request_content_no_recipe_skips_validation():
    """Without a recipe, preprocessor is not invoked."""
    client, _ = _client_with_credits()
    client.preprocessor = SymbolicPreprocessor()
    content = client.request_content("abc123")
    assert content is not None


# ── Security gate: PUFEnclave ─────────────────────────────────────────────────


def test_submit_compute_task_valid_puf_passes():
    seed = os.urandom(32)
    puf = PUFEnclave(seed=seed)
    client = TFPClient(puf=puf)  # no puf_expected_seed → uses puf's own seed
    receipt = client.submit_compute_task("task_hash")
    assert isinstance(receipt, Receipt)


def test_submit_compute_task_sybil_raises():
    seed = os.urandom(32)
    wrong_seed = os.urandom(32)
    puf = PUFEnclave(seed=seed)
    client = TFPClient(puf=puf, puf_expected_seed=wrong_seed)
    with pytest.raises(SecurityError, match="Sybil detection"):
        client.submit_compute_task("task_hash")


def test_submit_compute_task_no_puf_skips_check():
    """Without a PUF, identity verification is skipped."""
    client = TFPClient()  # no puf
    receipt = client.submit_compute_task("task_hash")
    assert isinstance(receipt, Receipt)
