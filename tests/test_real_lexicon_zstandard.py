# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import json
import pytest
from tfp_client.lib.lexicon.adapter_real import RealLexiconAdapter


class TestRealLexiconZstandard:
    """Test suite verifying genuine Zstandard dictionary compression and search."""

    def test_zstandard_compression_and_lossless_reconstruction(self):
        adapter = RealLexiconAdapter()

        # Structured domain payload
        raw_payload = json.dumps([{
            "status": "ok",
            "type": "task",
            "compute": "matrix",
            "algorithm": "ed25519",
            "protocol": "Foundation",
            "device_id": "rpi3_edge_node_77",
            "timestamp": 1773800000,
            "observations": "Matrix multiplication completed in 42ms with 0 errors.",
        }] * 10).encode("utf-8")

        # Compress with technical domain dictionary
        compressed = adapter.compress(raw_payload, tags=["technical", "code"])
        assert len(compressed) < len(raw_payload), "Payload must achieve actual compression"

        # Reconstruct (lossless decompression)
        content = adapter.reconstruct(compressed, tags=["technical"])

        assert content.data == raw_payload, "Decompressed payload must exactly match original bytes"
        assert content.metadata["was_compressed"] is True
        assert content.metadata["bandwidth_savings_pct"] > 20.0
        assert content.metadata["domain"] == "technical"

    def test_uncompressed_passthrough_reconstruction(self):
        adapter = RealLexiconAdapter()
        raw_payload = b"Simple raw text payload without zstd compression"

        content = adapter.reconstruct(raw_payload, tags=["general"])
        assert content.data == raw_payload
        assert content.metadata["was_compressed"] is False
        assert content.metadata["bandwidth_savings_pct"] == 0.0

    def test_semantic_search_with_ranking(self):
        adapter = RealLexiconAdapter()

        doc1 = b"Heart rate 75 bpm blood pressure normal patient healthy"
        doc2 = b"Arbitration clause mandatory under Delaware corporate law"
        doc3 = b"Network peer active latency 10ms matrix compute task running"

        content1 = adapter.reconstruct(doc1, tags=["medical"])
        content2 = adapter.reconstruct(doc2, tags=["legal"])
        content3 = adapter.reconstruct(doc3, tags=["technical"])

        # Search for medical keywords
        results_med = adapter.semantic_search("patient healthy blood pressure", domain="medical")
        assert len(results_med) >= 1
        assert results_med[0]["content_hash"] == content1.root_hash
        assert results_med[0]["score"] > 0
        assert "patient" in results_med[0]["matched_terms"]

        # Search for technical keywords
        results_tech = adapter.semantic_search("matrix compute latency", domain="technical")
        assert len(results_tech) >= 1
        assert results_tech[0]["content_hash"] == content3.root_hash

        # Search query with no match returns empty list
        results_none = adapter.semantic_search("quantum teleportation satellite")
        assert len(results_none) == 0
