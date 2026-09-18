# SPDX-License-Identifier: Apache-2.0
"""
Lightweight SearchResult container and RAGGraph provider.
Eliminates 2.5GB CodeBERT/ChromaDB dependencies while preserving API interface.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """Result of a semantic search query."""
    content: str
    metadata: Dict[str, Any]
    score: float
    chunk_id: str


class RAGGraph:
    """Lightweight stub provider for optional search endpoints."""
    def __init__(self, *args, **kwargs):
        self.persist_directory = kwargs.get("persist_directory", "./rag_storage")
        self.collection_name = kwargs.get("collection_name", "tfp")

    def search(self, query: str, top_k: int = 5, min_score: float = 0.5) -> List[SearchResult]:
        return []

    def get_stats(self) -> Dict[str, Any]:
        return {"total_chunks": 0, "collection_name": self.collection_name}

    def index_directory(self, *args, **kwargs) -> int:
        return 0
