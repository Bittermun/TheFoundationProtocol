# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Embedded Hybrid Search Engine: BM25 Lexical + MinHash LSH Semantic Retrieval.

Provides sub-millisecond offline keyword and semantic nearest-neighbor search
for modest edge devices without heavy neural dependencies (zero PyTorch / ChromaDB).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple


_TOKEN_RE = re.compile(r"\b\w+\b")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
    "at", "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "then", "once",
    "here", "there", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "s", "t", "can", "will", "just", "don", "should", "now", "is", "are", "was",
}


def tokenize(text: str) -> List[str]:
    """Tokenize lowercase alphanumeric words, filtering minimal stopwords."""
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


class BM25Index:
    """Okapi BM25 lexical ranking engine."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_lengths: Dict[str, int] = {}
        self.avg_doc_len: float = 0.0
        self.doc_count: int = 0
        self.term_doc_freq: Counter[str] = Counter()
        self.inverted_index: Dict[str, Dict[str, int]] = defaultdict(dict)  # term -> {doc_id: count}
        self.doc_contents: Dict[str, str] = {}
        self.doc_metadata: Dict[str, Dict[str, Any]] = {}

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add a single document to the BM25 index."""
        tokens = tokenize(content)
        doc_len = len(tokens)
        if doc_len == 0:
            return

        self.doc_lengths[doc_id] = doc_len
        self.doc_contents[doc_id] = content
        self.doc_metadata[doc_id] = metadata or {}

        term_counts = Counter(tokens)
        for term, count in term_counts.items():
            self.inverted_index[term][doc_id] = count
            self.term_doc_freq[term] += 1

        self.doc_count = len(self.doc_lengths)
        self.avg_doc_len = sum(self.doc_lengths.values()) / self.doc_count

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Search index and return sorted list of (doc_id, bm25_score)."""
        tokens = tokenize(query)
        if not tokens or self.doc_count == 0:
            return []

        scores: Dict[str, float] = defaultdict(float)
        n = self.doc_count

        for term in tokens:
            if term not in self.inverted_index:
                continue

            df = self.term_doc_freq[term]
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))

            for doc_id, tf in self.inverted_index[term].items():
                doc_len = self.doc_lengths[doc_id]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                scores[doc_id] += idf * (numerator / denominator)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


class MinHashLSH:
    """
    MinHash Locality-Sensitive Hashing for fast semantic approximate Jaccard similarity.
    """

    def __init__(self, num_perm: int = 64, shingle_size: int = 3):
        self.num_perm = num_perm
        self.shingle_size = shingle_size
        self.signatures: Dict[str, List[int]] = {}

        # Generate deterministic linear congruential hash parameters: (a * x + b) % p
        import random
        rng = random.Random(42)
        self._prime = 2147483647  # 2^31 - 1 (Mersenne prime)
        self._a = [rng.randint(1, self._prime - 1) for _ in range(num_perm)]
        self._b = [rng.randint(0, self._prime - 1) for _ in range(num_perm)]

    def _shingles(self, text: str) -> Set[int]:
        """Generate n-gram shingles as 32-bit hash integers."""
        clean = " ".join(text.lower().split())
        shingles = set()
        for i in range(len(clean) - self.shingle_size + 1):
            sh = clean[i : i + self.shingle_size]
            sh_hash = int.from_bytes(hashlib.md5(sh.encode("utf-8")).digest()[:4], "big")
            shingles.add(sh_hash)
        return shingles

    def compute_signature(self, text: str) -> List[int]:
        """Compute MinHash signature vector."""
        shingles = self._shingles(text)
        if not shingles:
            return [0] * self.num_perm

        sig = []
        for a, b in zip(self._a, self._b):
            min_val = min(((a * s + b) % self._prime) for s in shingles)
            sig.append(min_val)
        return sig

    def add_document(self, doc_id: str, content: str):
        """Index document MinHash signature."""
        self.signatures[doc_id] = self.compute_signature(content)

    def similarity_with_sig(self, q_sig: List[int], doc_id: str) -> float:
        """Estimate Jaccard semantic similarity using precomputed query signature."""
        if doc_id not in self.signatures:
            return 0.0
        doc_sig = self.signatures[doc_id]
        matches = sum(1 for q, d in zip(q_sig, doc_sig) if q == d)
        return matches / self.num_perm

    def similarity(self, query: str, doc_id: str) -> float:
        """Estimate Jaccard semantic similarity between query and indexed document."""
        q_sig = self.compute_signature(query)
        return self.similarity_with_sig(q_sig, doc_id)


@dataclass
class HybridSearchResult:
    """Unified hybrid search result."""

    chunk_id: str
    content: str
    metadata: Dict[str, Any]
    score: float
    lexical_score: float = 0.0
    semantic_score: float = 0.0


class HybridSearchEngine:
    """
    Combined BM25 + MinHash LSH Hybrid Search Engine.
    """

    def __init__(self, bm25_weight: float = 0.70, lsh_weight: float = 0.30):
        self.bm25_weight = bm25_weight
        self.lsh_weight = lsh_weight
        self.bm25 = BM25Index()
        self.lsh = MinHashLSH()

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add document to both lexical BM25 and MinHash semantic indexes."""
        self.bm25.add_document(doc_id, content, metadata)
        self.lsh.add_document(doc_id, content)

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[HybridSearchResult]:
        """Execute hybrid search combining BM25 ranking and MinHash similarity."""
        bm25_results = self.bm25.search(query, top_k=top_k * 3)
        if not bm25_results:
            return []

        # Precompute query MinHash signature ONCE for all candidates
        q_sig = self.lsh.compute_signature(query)

        # Normalize BM25 scores to [0, 1] range
        max_bm25 = max(s for _, s in bm25_results) if bm25_results else 1.0
        if max_bm25 <= 0.0:
            max_bm25 = 1.0

        hybrid_results = []
        for doc_id, raw_bm25 in bm25_results:
            norm_bm25 = raw_bm25 / max_bm25
            lsh_sim = self.lsh.similarity_with_sig(q_sig, doc_id)

            combined_score = (self.bm25_weight * norm_bm25) + (self.lsh_weight * lsh_sim)
            if combined_score < min_score:
                continue

            res = HybridSearchResult(
                chunk_id=doc_id,
                content=self.bm25.doc_contents[doc_id],
                metadata=self.bm25.doc_metadata[doc_id],
                score=round(combined_score, 4),
                lexical_score=round(norm_bm25, 4),
                semantic_score=round(lsh_sim, 4),
            )
            hybrid_results.append(res)

        hybrid_results.sort(key=lambda r: r.score, reverse=True)
        return hybrid_results[:top_k]

    def count(self) -> int:
        """Return total indexed documents."""
        return self.bm25.doc_count
