# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Content distribution module for P2P mesh networking.

This module provides content sharding, distribution across peers,
and retrieval from distributed shards using existing RaptorQ fountain coding.
"""

from .shard_manager import ShardManager, DistributionPlan, DistributionResult
from .shard_retriever import ShardRetriever

__all__ = [
    "ShardManager",
    "DistributionPlan",
    "DistributionResult",
    "ShardRetriever",
]