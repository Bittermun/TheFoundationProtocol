# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Mesh routing with Dijkstra's algorithm for optimal path finding.

Computes optimal routes through the peer mesh based on latency,
hop count, and route quality.
"""

from .mesh_router import MeshRouter, Route, RoutingTable, RoutingConfig

__all__ = [
    "MeshRouter",
    "Route",
    "RoutingTable",
    "RoutingConfig",
]
