import json
import pytest
from tfp_client.lib.security.symbolic_preprocessor.preprocessor import SymbolicPreprocessor


def valid_recipe():
    return {
        "task_type": "inference",
        "params_hash": "a" * 64,
        "difficulty": 3,
    }


def test_valid_recipe_passes():
    sp = SymbolicPreprocessor()
    ok, confidence = sp.validate(valid_recipe())
    assert ok is True
    assert confidence > 0.8


def test_missing_required_field_fails():
    sp = SymbolicPreprocessor()
    recipe = valid_recipe()
    del recipe["task_type"]
    ok, _ = sp.validate(recipe)
    assert ok is False


def test_oversized_recipe_fails():
    sp = SymbolicPreprocessor()
    big_bytes = b"x" * 2049
    ok, _ = sp.validate(valid_recipe(), raw_bytes=big_bytes)
    assert ok is False


def test_confidence_is_float_in_range():
    sp = SymbolicPreprocessor()
    for recipe in [valid_recipe(), {"task_type": "x"}, {"task_type": "x", "params_hash": "y", "difficulty": -1}]:
        _, confidence = sp.validate(recipe)
        assert 0.0 <= confidence <= 1.0


def test_poisoned_recipe_fails():
    sp = SymbolicPreprocessor()
    poisoned = {"task_type": "inference", "params_hash": "a" * 64, "difficulty": -5}
    ok, confidence = sp.validate(poisoned)
    assert ok is False
    assert confidence < 0.5


def test_batch_validation():
    sp = SymbolicPreprocessor()
    good = [valid_recipe() for _ in range(80)]
    bad_difficulty = {"task_type": "inference", "params_hash": "a" * 64, "difficulty": -1}
    poisoned = [bad_difficulty for _ in range(20)]
    all_recipes = good + poisoned
    results = [sp.validate(r) for r in all_recipes]
    good_results = results[:80]
    failures_in_good = sum(1 for ok, _ in good_results if not ok)
    assert failures_in_good / 80 < 0.08
