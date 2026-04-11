import hashlib
from unittest.mock import MagicMock

from tfp_client.lib.fountain.adapter import RaptorQAdapter
from tfp_client.lib.ndn.adapter import Data, Interest, NDNAdapter
from tfp_common.sync.lexicon_delta.hlt import HierarchicalLexiconTree


def test_apply_delta_succeeds_on_valid_hash():
    tree = HierarchicalLexiconTree()
    base_hash = hashlib.sha3_256(b"base").hexdigest()
    tree.set_base(base_hash, b"base")
    delta = b"delta_data"
    result = tree.apply_delta(base_hash, delta)
    assert result is True


def test_apply_delta_rolls_back_on_hash_mismatch():
    tree = HierarchicalLexiconTree()
    base_hash = hashlib.sha3_256(b"base").hexdigest()
    tree.set_base(base_hash, b"base")
    wrong_hash = "wrong_hash_value"
    original_state_hash = tree.current_hash
    result = tree.apply_delta(wrong_hash, b"delta")
    assert result is False
    assert tree.current_hash == original_state_hash


def test_sync_via_ndn_calls_raptorq():
    tree = HierarchicalLexiconTree()
    mock_ndn = MagicMock(spec=NDNAdapter)
    mock_ndn.create_interest.return_value = Interest(name="/tfp/lexicon/prefix")
    mock_ndn.express_interest.return_value = Data(
        name="/tfp/lexicon/prefix", content=b"shard_data"
    )
    mock_rq = MagicMock(spec=RaptorQAdapter)
    mock_rq.decode.return_value = b"decoded_data"
    result = tree.sync_via_ndn(
        "/tfp/lexicon/prefix", ndn_adapter=mock_ndn, raptorq_adapter=mock_rq
    )
    mock_rq.decode.assert_called_once()
    assert result == b"decoded_data"


def test_multiple_deltas_stack():
    tree = HierarchicalLexiconTree()
    base_data = b"base_data"
    base_hash = hashlib.sha3_256(base_data).hexdigest()
    tree.set_base(base_hash, base_data)

    current_hash = base_hash
    current_base = base_data
    for i in range(3):
        delta = f"delta_{i}".encode()
        result = tree.apply_delta(current_hash, delta)
        assert result is True
        current_hash = hashlib.sha3_256(current_base + delta).hexdigest()
        current_base = current_base  # base doesn't change in state, only the hash key

    assert tree.current_hash is not None
    assert tree.current_hash != base_hash


def test_atomic_rollback_leaves_no_partial_state():
    tree = HierarchicalLexiconTree()
    base_hash = hashlib.sha3_256(b"clean_base").hexdigest()
    tree.set_base(base_hash, b"clean_base")
    state_before = dict(tree._state)
    hash_before = tree.current_hash
    # Apply with wrong hash
    result = tree.apply_delta("wrong_hash", b"should_not_apply")
    assert result is False
    assert tree._state == state_before
    assert tree.current_hash == hash_before
