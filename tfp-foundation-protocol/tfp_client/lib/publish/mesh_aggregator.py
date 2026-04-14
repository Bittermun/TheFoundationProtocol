# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Mesh Aggregator - Aggregates demand signals from local mesh nodes

Collects publish announcements, aggregates demand scores,
and forwards to gateway scheduler.
"""

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional


class MeshAggregator:
    """
    Aggregates content demand signals from mesh network.

    Usage:
        aggregator = MeshAggregator(region="us-west")
        aggregator.receive_announcement(hash_hex, metadata)
        aggregator.increment_demand(hash_hex)

        # Periodically aggregate and forward
        aggregated = aggregator.aggregate_demand_signals()
        gateway.forward_to_gateway(aggregated)
    """

    def __init__(self, region: str = "default"):
        """
        Initialize mesh aggregator.

        Args:
            region: Region identifier for this aggregator
        """
        self._region = region
        self._announcements: Dict[str, Dict[str, Any]] = {}  # hash -> metadata
        self._demand_counts: Dict[str, int] = defaultdict(int)  # hash -> request count
        self._first_seen: Dict[str, float] = {}  # hash -> timestamp
        self._last_aggregated: float = 0.0

    def receive_announcement(
        self, hash_hex: str, metadata: Dict[str, Any], source_node: str = ""
    ) -> None:
        """
        Receive a publish announcement from a mesh node.

        Args:
            hash_hex: Content hash
            metadata: Content metadata
            source_node: ID of announcing node (optional)
        """
        if hash_hex not in self._announcements:
            self._announcements[hash_hex] = {
                "metadata": metadata,
                "source_nodes": [],
                "first_seen": time.time(),
            }
            self._first_seen[hash_hex] = time.time()

        if (
            source_node
            and source_node not in self._announcements[hash_hex]["source_nodes"]
        ):
            self._announcements[hash_hex]["source_nodes"].append(source_node)

    def increment_demand(self, hash_hex: str, count: int = 1) -> None:
        """
        Increment demand counter for content.

        Called when an Interest packet is received for this content.

        Args:
            hash_hex: Content hash
            count: Number of requests to add (default 1)
        """
        self._demand_counts[hash_hex] += count

    def aggregate_demand_signals(
        self, time_window: float = 3600.0
    ) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate demand signals into scored results.

        Args:
            time_window: Time window in seconds for demand calculation (default 1 hour)

        Returns:
            Dict mapping hash -> {hash, demand_score, request_count, metadata}
        """
        current_time = time.time()
        cutoff_time = current_time - time_window  # noqa: F841
        aggregated = {}

        for hash_hex, count in self._demand_counts.items():
            if hash_hex not in self._first_seen:
                continue

            first_seen = self._first_seen[hash_hex]
            metadata = self._announcements.get(hash_hex, {}).get("metadata", {})

            # Calculate demand score: requests per hour, normalized
            time_active = max(1.0, current_time - first_seen)
            hours_active = time_active / 3600.0
            requests_per_hour = count / hours_active

            # Normalize to 0-1 scale (assuming max ~100 req/hour is very popular)
            demand_score = min(1.0, requests_per_hour / 100.0)

            aggregated[hash_hex] = {
                "hash": hash_hex,
                "demand_score": demand_score,
                "request_count": count,
                "metadata": metadata,
                "time_active_hours": hours_active,
                "source_node_count": len(
                    self._announcements.get(hash_hex, {}).get("source_nodes", [])
                ),
            }

        self._last_aggregated = current_time
        return aggregated

    def get_top_demand(
        self, limit: int = 10, time_window: float = 3600.0
    ) -> List[Dict[str, Any]]:
        """
        Get top content by demand score.

        Args:
            limit: Maximum number of results
            time_window: Time window for demand calculation

        Returns:
            List of top demand entries, sorted by demand_score descending
        """
        aggregated = self.aggregate_demand_signals(time_window)
        sorted_items = sorted(
            aggregated.values(), key=lambda x: x["demand_score"], reverse=True
        )
        return sorted_items[:limit]

    def get_demand_for_hash(self, hash_hex: str) -> Optional[Dict[str, Any]]:
        """
        Get demand info for a specific hash.

        Args:
            hash_hex: Content hash

        Returns:
            Demand dict or None if not found
        """
        aggregated = self.aggregate_demand_signals()
        return aggregated.get(hash_hex)

    def reset_demand(self, hash_hex: str) -> None:
        """Reset demand counter for a hash (after gateway scheduling)."""
        if hash_hex in self._demand_counts:
            del self._demand_counts[hash_hex]

    def clear_old_announcements(self, max_age: float = 86400.0) -> int:
        """
        Clear announcements older than max_age.

        Args:
            max_age: Maximum age in seconds (default 24 hours)

        Returns:
            Number of cleared announcements
        """
        current_time = time.time()
        to_remove = []

        for hash_hex, data in self._announcements.items():
            if current_time - data["first_seen"] > max_age:
                to_remove.append(hash_hex)

        for hash_hex in to_remove:
            del self._announcements[hash_hex]
            if hash_hex in self._demand_counts:
                del self._demand_counts[hash_hex]
            if hash_hex in self._first_seen:
                del self._first_seen[hash_hex]

        return len(to_remove)

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics."""
        total_demand = sum(self._demand_counts.values())
        avg_demand = (
            total_demand / len(self._demand_counts) if self._demand_counts else 0.0
        )

        return {
            "region": self._region,
            "total_announcements": len(self._announcements),
            "total_demand_requests": total_demand,
            "avg_demand_per_content": avg_demand,
            "last_aggregated": self._last_aggregated,
        }

    def export_for_gateway(self) -> bytes:
        """
        Export aggregated demand for transmission to gateway.

        Returns:
            Serialized demand data (JSON bytes)
        """
        import json

        aggregated = self.aggregate_demand_signals()
        return json.dumps(
            {"region": self._region, "timestamp": time.time(), "demand": aggregated}
        ).encode("utf-8")

    @classmethod
    def import_from_gateway(cls, data: bytes) -> Dict[str, Any]:
        """
        Import demand data (for gateway side).

        Args:
            data: Serialized demand data

        Returns:
            Deserialized demand dict
        """
        import json

        return json.loads(data.decode("utf-8"))
