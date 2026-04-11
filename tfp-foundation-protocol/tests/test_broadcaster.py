from unittest.mock import MagicMock

import pytest
from tfp_broadcaster.broadcaster import Broadcaster, TaskRecipe
from tfp_broadcaster.src.ldm_semantic_mapper import LDMSemanticMapper
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


# ── LDM Semantic Mapper tests ─────────────────────────────────────────────────


def test_seed_content_no_ldm_no_plp_assignment():
    broadcaster = Broadcaster()
    result = broadcaster.seed_content(b"data", metadata={"core_info": "val"})
    assert "plp_assignment" not in result


def test_seed_content_use_ldm_without_metadata_no_assignment():
    broadcaster = Broadcaster()
    result = broadcaster.seed_content(b"data", use_ldm=True)
    assert "plp_assignment" not in result


def test_seed_content_use_ldm_with_metadata():
    broadcaster = Broadcaster()
    metadata = {
        "struct_layout": {"rows": 4, "cols": 3},
        "texture_delta": b"compressed",
        "nav_info": "gps_coords",
        "metadata_tag": "low_priority",
    }
    result = broadcaster.seed_content(
        b"content_payload", metadata=metadata, use_ldm=True
    )
    assert "plp_assignment" in result
    plp = result["plp_assignment"]
    assert "core_plp" in plp
    assert "enhanced_plp" in plp


def test_ldm_mapper_core_prefix_keys():
    mapper = LDMSemanticMapper()
    dag = {
        "struct_main": "layout_data",
        "core_safety": "alert_data",
        "nav_coords": "gps",
        "alert_level": 3,
        "emergency_msg": "evacuate",
        "texture_detail": "pixels",
        "metadata": {"source": "cam1"},
    }
    result = mapper.map_to_plps(dag)
    core = result["core_plp"]
    enhanced = result["enhanced_plp"]
    # Keys with core prefixes → Core PLP
    assert "struct_main" in core
    assert "core_safety" in core
    assert "nav_coords" in core
    assert "alert_level" in core
    assert "emergency_msg" in core
    # Nested dict → Core PLP
    assert "metadata" in core
    # Texture delta → Enhanced PLP
    assert "texture_detail" in enhanced


def test_ldm_mapper_enhanced_keys():
    mapper = LDMSemanticMapper()
    dag = {
        "texture_delta_high": b"raw",
        "quality_score": 0.95,
        "redundant_bytes": 1024,
    }
    result = mapper.map_to_plps(dag)
    assert len(result["core_plp"]) == 0
    assert len(result["enhanced_plp"]) == 3


def test_ldm_mapper_empty_dag():
    mapper = LDMSemanticMapper()
    result = mapper.map_to_plps({})
    assert result == {"core_plp": {}, "enhanced_plp": {}}


def test_ldm_mapper_non_dict_raises():
    mapper = LDMSemanticMapper()
    with pytest.raises(TypeError):
        mapper.map_to_plps("not a dict")


def test_ldm_mapper_all_keys_assigned():
    mapper = LDMSemanticMapper()
    dag = {f"key_{i}": f"val_{i}" for i in range(10)}
    result = mapper.map_to_plps(dag)
    total = len(result["core_plp"]) + len(result["enhanced_plp"])
    assert total == len(dag)
