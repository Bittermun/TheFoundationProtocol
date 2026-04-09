"""
LDM Semantic Mapper — assigns semantic-DAG keys to ATSC 3.0 PLPs.

Core PLP  : structural / safety content (QPSK-equivalent, lower redundancy,
            always-on).  Keys whose values are dicts or strings with structural
            significance (prefixes: "struct", "layout", "core", "nav", "alert",
            "emergency") are placed here.

Enhanced PLP : texture deltas / metadata (64-QAM-equivalent, higher throughput
               optional).  All remaining keys are placed here.
"""
from __future__ import annotations
from typing import Dict, Any

_CORE_PREFIXES = ("struct", "layout", "core", "nav", "alert", "emergency")


class LDMSemanticMapper:
    """Maps a semantic DAG dict to Core and Enhanced PLPs."""

    def map_to_plps(self, semantic_dag: dict) -> dict:
        """Assign keys from *semantic_dag* to Core PLP or Enhanced PLP.

        Args:
            semantic_dag: Flat or nested dict representing a semantic content DAG.

        Returns:
            ``{"core_plp": {...}, "enhanced_plp": {...}}``
        """
        if not isinstance(semantic_dag, dict):
            raise TypeError("semantic_dag must be a dict")

        core: Dict[str, Any] = {}
        enhanced: Dict[str, Any] = {}

        for key, value in semantic_dag.items():
            if self._is_core(key, value):
                core[key] = value
            else:
                enhanced[key] = value

        return {"core_plp": core, "enhanced_plp": enhanced}

    # ------------------------------------------------------------------
    @staticmethod
    def _is_core(key: str, value: Any) -> bool:
        """Return True if this key/value pair belongs in the Core PLP."""
        key_lower = str(key).lower()
        # Key prefix match
        if any(key_lower.startswith(p) for p in _CORE_PREFIXES):
            return True
        # Nested dict → treat as structural node
        if isinstance(value, dict):
            return True
        return False