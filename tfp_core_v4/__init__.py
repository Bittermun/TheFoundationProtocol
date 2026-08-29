# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
The Foundation Protocol (TFP v4.0) - Canonical Core Engine

A decentralized, loss-tolerant, deduplicating information distribution protocol.
"""

from .cdc import ChunkRecipe, ContentDefinedChunker
from .fountain import FountainCodec, FountainDroplet
from .merkle import MerkleTree, verify_merkle_proof
from .mesh import MeshPeer, SwarmNetwork
from .node import TFPNode

__version__ = "4.0.0"
__all__ = [
    "ContentDefinedChunker",
    "ChunkRecipe",
    "FountainCodec",
    "FountainDroplet",
    "MerkleTree",
    "verify_merkle_proof",
    "MeshPeer",
    "SwarmNetwork",
    "TFPNode",
]
