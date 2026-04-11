from typing import Tuple

REQUIRED_FIELDS = {"task_type", "params_hash", "difficulty"}
MAX_RECIPE_BYTES = 2048


class SymbolicPreprocessor:
    def validate(self, recipe: dict, raw_bytes: bytes = None) -> Tuple[bool, float]:
        if raw_bytes and len(raw_bytes) > MAX_RECIPE_BYTES:
            return False, 0.0
        if not REQUIRED_FIELDS.issubset(recipe.keys()):
            return False, 0.1
        if (
            not isinstance(recipe.get("difficulty"), (int, float))
            or recipe["difficulty"] < 0
        ):
            return False, 0.2
        if (
            not isinstance(recipe.get("task_type"), str)
            or not recipe["task_type"].strip()
        ):
            return False, 0.1
        confidence = 0.7
        if recipe.get("difficulty", 0) > 0:
            confidence += 0.15
        if len(recipe.get("params_hash", "")) == 64:
            confidence += 0.15
        return True, min(confidence, 1.0)
