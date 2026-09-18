# SPDX-License-Identifier: Apache-2.0
"""
Production Zero-Dependency Hybrid Search Provider.
Eliminates 2.5GB CodeBERT/ChromaDB dependencies while preserving API interface.
Powered by BM25 lexical ranking and MinHash LSH semantic retrieval.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from .search.hybrid_search import HybridSearchEngine, HybridSearchResult


@dataclass
class SearchResult:
    """Result of a semantic search query."""
    content: str
    metadata: Dict[str, Any]
    score: float
    chunk_id: str


class RAGGraph:
    """Zero-dependency hybrid search provider for TFP."""
    def __init__(self, *args, **kwargs):
        self.persist_directory = kwargs.get("persist_directory", "./rag_storage")
        self.collection_name = kwargs.get("collection_name", "tfp")
        self.engine = HybridSearchEngine()

    def add_chunk(self, chunk_id: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Index a text chunk into the search engine."""
        self.engine.add_document(chunk_id, content, metadata)

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> List[SearchResult]:
        """Execute hybrid search query."""
        results = self.engine.search(query, top_k=top_k, min_score=min_score)
        return [
            SearchResult(
                content=r.content,
                metadata=r.metadata,
                score=r.score,
                chunk_id=r.chunk_id,
            )
            for r in results
        ]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_chunks": self.engine.count(),
            "collection_name": self.collection_name,
        }

    def index_directory(self, *args, **kwargs) -> int:
        return self.engine.count()
