# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Zero-Dependency Embedded Hybrid Search Engine for TFP v4.0.

Combines Okapi BM25 lexical ranking with MinHash Locality-Sensitive Hashing (LSH)
to provide fast, offline semantic information retrieval across compressed domain
archives without requiring PyTorch, Transformers, or external vector databases.
"""

from .hybrid_search import BM25Index, MinHashLSH, HybridSearchEngine

__all__ = [
    "BM25Index",
    "MinHashLSH",
    "HybridSearchEngine",
]
