# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unit and Integration Tests for Zero-Dependency Hybrid Search (BM25 + MinHash LSH).

Verifies:
1. Okapi BM25 lexical ranking accuracy and inverse document frequency.
2. MinHash LSH semantic similarity estimation.
3. Sub-15ms hybrid search latency across domain documents.
4. RAGGraph drop-in replacement interface compatibility.
"""

from pathlib import Path
import time
import sys
import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_tfp_root = _repo_root / "tfp-foundation-protocol"
if str(_tfp_root) not in sys.path:
    sys.path.insert(0, str(_tfp_root))

from tfp_client.lib.search.hybrid_search import BM25Index, MinHashLSH, HybridSearchEngine
from tfp_client.lib.rag_search import RAGGraph, SearchResult


@pytest.fixture
def domain_documents():
    return [
        ("med_01", "Oral rehydration therapy requires 6 teaspoons sugar and half teaspoon salt in one liter boiled water.", {"domain": "medical"}),
        ("med_02", "Emergency triage category Red indicates immediate life-threatening injury requiring urgent resuscitation.", {"domain": "medical"}),
        ("med_03", "Treat hypothermia with gradual core rewarming, warm fluids, and removal of wet clothing.", {"domain": "medical"}),
        ("tech_01", "FastCDC uses a 64-bit random gear hash matrix with normalized masks to compute chunk boundaries.", {"domain": "technical"}),
        ("tech_02", "Vectorized rateless fountain codes perform whole-payload Gaussian elimination over Galois field GF(2).", {"domain": "technical"}),
        ("tech_03", "KISS protocol frames serial bytes using FEND 0xC0 and FESC 0xDB delimiters with byte stuffing.", {"domain": "technical"}),
        ("radio_01", "Amateur radio AX.25 packet framing transmits over VHF frequencies at 1200 baud Bell 202 tones.", {"domain": "radio"}),
        ("radio_02", "LoRa physical layer uses Chirp Spread Spectrum modulation to operate beneath the thermal noise floor.", {"domain": "radio"}),
        ("disaster_01", "Post-earthquake search and rescue grid marking uses structural triage symbols to tag cleared buildings.", {"domain": "disaster"}),
        ("disaster_02", "Emergency water purification guidelines recommend boiling water vigorously for at least one minute.", {"domain": "disaster"}),
    ]


def test_bm25_lexical_ranking(domain_documents):
    """Verify BM25 index correctly ranks specific keyword matches first."""
    bm25 = BM25Index()
    for doc_id, text, meta in domain_documents:
        bm25.add_document(doc_id, text, meta)

    assert bm25.doc_count == len(domain_documents)

    results = bm25.search("oral rehydration therapy salt sugar", top_k=3)
    assert len(results) > 0
    top_doc_id, score = results[0]
    assert top_doc_id == "med_01"
    assert score > 0


def test_minhash_semantic_similarity():
    """Verify MinHash Jaccard similarity estimation between related and unrelated texts."""
    lsh = MinHashLSH(num_perm=64)

    text_a = "Emergency water purification guidelines recommend boiling water vigorously."
    text_b = "Guidelines for emergency water purification suggest boiling clean water."
    text_c = "Vectorized rateless fountain codes perform Gaussian elimination over GF(2)."

    lsh.add_document("doc_a", text_a)
    lsh.add_document("doc_c", text_c)

    sim_ab = lsh.similarity(text_b, "doc_a")
    sim_bc = lsh.similarity(text_b, "doc_c")

    assert sim_ab > 0.35  # High similarity between water purification sentences
    assert sim_bc < 0.15  # Low similarity between water purification and math/coding


def test_hybrid_search_speed_and_recall(domain_documents):
    """Verify hybrid search executes in under 15ms and returns combined scored results."""
    engine = HybridSearchEngine(bm25_weight=0.7, lsh_weight=0.3)

    # Expand dataset to 50 documents for benchmark
    for i in range(5):
        for doc_id, text, meta in domain_documents:
            engine.add_document(f"{doc_id}_{i}", text, meta)

    assert engine.count() == 50

    queries = [
        "water boiling purification",
        "triage resuscitation urgent",
        "LoRa chirp spread spectrum",
        "Gaussian elimination Galois field",
    ]

    for q in queries:
        t0 = time.perf_counter()
        results = engine.search(q, top_k=3)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        assert len(results) > 0
        assert latency_ms < 15.0  # Ultra-fast sub-15ms query execution
        assert results[0].score > 0.20


def test_rag_graph_integration():
    """Verify RAGGraph acts as a drop-in semantic search engine."""
    rag = RAGGraph(collection_name="tfp_emergency")
    rag.add_chunk("c1", "Patient presents with severe hypothermia. Rewarming protocol initiated.", {"priority": 1})
    rag.add_chunk("c2", "Network router configured with OSPF routing protocol.", {"priority": 2})

    stats = rag.get_stats()
    assert stats["total_chunks"] == 2
    assert stats["collection_name"] == "tfp_emergency"

    results = rag.search("hypothermia rewarming patient", top_k=1)
    assert len(results) == 1
    res = results[0]
    assert isinstance(res, SearchResult)
    assert res.chunk_id == "c1"
    assert res.score > 0
    assert "hypothermia" in res.content
