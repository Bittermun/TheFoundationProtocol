import hashlib
import pytest
from unittest.mock import MagicMock

from tfp_broadcaster.broadcaster import Broadcaster, TaskRecipe
from tfp_broadcaster.src.multicast.adapter import MulticastAdapter


def test_seed_content_returns_root_hash():
    broadcaster = Broadcaster()
    result = broadcaster.seed_content(b"hello world content")
    assert "root_hash" in result


def test_seed_content_root_hash_is_sha3():
    broadcaster = Broadcaster()
    result = broadcaster.seed_content(b"hello world content")
    root_hash = result["root_hash"]
    assert len(root_hash) == 64
    int(root_hash, 16)  # must be valid hex


def test_broadcast_task_returns_task_hash():
    broadcaster = Broadcaster()
    recipe = TaskRecipe(task_type="inference", params_hash="a" * 64, difficulty=3)
    result = broadcaster.broadcast_compute_task(recipe)
    assert "task_hash" in result


def test_broadcast_task_calls_multicast():
    mock_multicast = MagicMock(spec=MulticastAdapter)
    broadcaster = Broadcaster(multicast=mock_multicast)
    recipe = TaskRecipe(task_type="inference", params_hash="a" * 64, difficulty=3)
    broadcaster.broadcast_compute_task(recipe)
    mock_multicast.transmit.assert_called_once()


def test_seed_empty_file_raises():
    broadcaster = Broadcaster()
    with pytest.raises(ValueError):
        broadcaster.seed_content(b"")
