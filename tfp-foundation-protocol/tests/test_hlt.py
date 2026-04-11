"""
Tests for Hierarchical Lexicon Tree (HLT) - Semantic Synchronization Layer

HLT ensures all devices share the same generative prior (AI model weights, grammar, dictionary)
to prevent semantic drift when reconstructing content from hashes.
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tfp_client.lib.lexicon.hlt.delta import DeltaType, LexiconDelta
from tfp_client.lib.lexicon.hlt.sync import LexiconSynchronizer, SyncState
from tfp_client.lib.lexicon.hlt.tree import (
    HierarchicalLexiconTree,
    LexiconNode,
    NodeType,
)


class TestLexiconNode:
    """Test individual lexicon nodes in the hierarchy."""

    def test_create_root_node(self):
        """Root node represents base lexicon version."""
        node = LexiconNode(
            node_id="root",
            node_type=NodeType.ROOT,
            version="v1.0.0",
            content_hash=hashlib.sha3_256(b"base_lexicon").hexdigest(),
        )
        assert node.node_id == "root"
        assert node.node_type == NodeType.ROOT
        assert node.version == "v1.0.0"
        assert node.parent_id is None

    def test_create_domain_node(self):
        """Domain nodes represent specialized lexicons (medical, legal, technical)."""
        node = LexiconNode(
            node_id="medical_v2",
            node_type=NodeType.DOMAIN,
            version="v2.1.0",
            parent_id="root",
            tags=["medical", "healthcare"],
            content_hash=hashlib.sha3_256(b"medical_lexicon").hexdigest(),
        )
        assert node.node_type == NodeType.DOMAIN
        assert node.parent_id == "root"
        assert "medical" in node.tags

    def test_create_adapter_node(self):
        """Adapter nodes contain delta updates for specific domains."""
        node = LexiconNode(
            node_id="medical_adapter_001",
            node_type=NodeType.ADAPTER,
            version="v2.1.1",
            parent_id="medical_v2",
            precision_anchor="anchor_med_42",
            content_hash=hashlib.sha3_256(b"adapter_delta").hexdigest(),
        )
        assert node.node_type == NodeType.ADAPTER
        assert node.parent_id == "medical_v2"
        assert node.precision_anchor == "anchor_med_42"

    def test_node_serialization(self):
        """Nodes must serialize/deserialize for network transmission."""
        node = LexiconNode(
            node_id="test_node",
            node_type=NodeType.DOMAIN,
            version="v1.0.0",
            tags=["test"],
            content_hash="abc123",
        )
        data = node.to_dict()
        restored = LexiconNode.from_dict(data)
        assert restored.node_id == node.node_id
        assert restored.version == node.version
        assert restored.tags == node.tags


class TestHierarchicalLexiconTree:
    """Test the HLT structure and operations."""

    def test_create_empty_tree(self):
        """Empty tree starts with root node only."""
        hlt = HierarchicalLexiconTree()
        assert len(hlt.nodes) == 1
        assert hlt.root.node_type == NodeType.ROOT

    def test_add_domain_to_tree(self):
        """Add domain-specific lexicon as child of root."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            name="medical",
            version="v2.1.0",
            content_hash=hashlib.sha3_256(b"medical").hexdigest(),
            tags=["healthcare", "biology"],
        )
        assert domain_id is not None
        assert hlt.get_node(domain_id).node_type == NodeType.DOMAIN

    def test_add_adapter_to_domain(self):
        """Add adapter delta to existing domain."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            "medical", "v2.1.0", hashlib.sha3_256(b"med").hexdigest()
        )
        adapter_id = hlt.add_adapter(
            domain_id=domain_id,
            version="v2.1.1",
            delta_content=b"adapter_changes",
            precision_anchor="anchor_001",
        )
        adapter = hlt.get_node(adapter_id)
        assert adapter.node_type == NodeType.ADAPTER
        assert adapter.parent_id == domain_id

    def test_get_path_from_root(self):
        """Retrieve full path from root to any node."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            "legal", "v1.0.0", hashlib.sha3_256(b"legal").hexdigest()
        )
        adapter_id = hlt.add_adapter(domain_id, "v1.0.1", b"delta", "anchor_01")

        path = hlt.get_path_from_root(adapter_id)
        assert len(path) == 3  # root -> domain -> adapter
        assert path[0].node_type == NodeType.ROOT
        assert path[-1].node_id == adapter_id

    def test_has_domain_check(self):
        """Check if tree contains specific domain."""
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("technical", "v3.0.0", hashlib.sha3_256(b"tech").hexdigest())

        assert hlt.has_domain("technical") is True
        assert hlt.has_domain("medical") is False

    def test_get_latest_version(self):
        """Get latest version of a domain including adapters."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            "science", "v1.0.0", hashlib.sha3_256(b"sci").hexdigest()
        )
        hlt.add_adapter(domain_id, "v1.0.1", b"delta1", "a1")
        hlt.add_adapter(domain_id, "v1.0.2", b"delta2", "a2")

        latest = hlt.get_latest_version("science")
        assert latest["version"] == "v1.0.2"

    def test_merkle_root_computation(self):
        """Compute Merkle root of entire tree for verification."""
        hlt = HierarchicalLexiconTree()
        hlt.add_domain("math", "v1.0.0", hashlib.sha3_256(b"math").hexdigest())
        hlt.add_domain("physics", "v1.0.0", hashlib.sha3_256(b"phys").hexdigest())

        merkle_root = hlt.compute_merkle_root()
        assert len(merkle_root) == 64  # SHA3-256 hex
        assert merkle_root != hashlib.sha3_256(b"empty").hexdigest()

    def test_tree_serialization(self):
        """Serialize/deserialize entire tree."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            "art", "v1.0.0", hashlib.sha3_256(b"art").hexdigest()
        )
        hlt.add_adapter(domain_id, "v1.0.1", b"delta", "anchor")

        data = hlt.to_dict()
        restored = HierarchicalLexiconTree.from_dict(data)

        assert len(restored.nodes) == len(hlt.nodes)
        assert restored.has_domain("art")


class TestLexiconDelta:
    """Test delta encoding for efficient lexicon updates."""

    def test_create_addition_delta(self):
        """Delta representing new terms added."""
        delta = LexiconDelta(
            delta_type=DeltaType.ADDITION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data={"new_term": "definition"},
        )
        assert delta.delta_type == DeltaType.ADDITION
        assert "new_term" in delta.data

    def test_create_modification_delta(self):
        """Delta representing term modifications."""
        delta = LexiconDelta(
            delta_type=DeltaType.MODIFICATION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data={"term": {"old": "def1", "new": "def2"}},
        )
        assert delta.delta_type == DeltaType.MODIFICATION

    def test_create_deletion_delta(self):
        """Delta representing removed terms."""
        delta = LexiconDelta(
            delta_type=DeltaType.DELETION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data=["obsolete_term"],
        )
        assert delta.delta_type == DeltaType.DELETION

    def test_delta_serialization(self):
        """Deltas must serialize compactly for transmission."""
        delta = LexiconDelta(
            delta_type=DeltaType.ADDITION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data={"term": "def"},
        )
        data = delta.to_bytes()
        restored = LexiconDelta.from_bytes(data)
        assert restored.delta_type == delta.delta_type
        assert restored.data == delta.data

    def test_apply_addition_delta(self):
        """Apply addition delta to lexicon state."""
        state = {"existing": "def1"}
        delta = LexiconDelta(
            delta_type=DeltaType.ADDITION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data={"new": "def2"},
        )
        result = delta.apply(state)
        assert "existing" in result
        assert "new" in result

    def test_apply_deletion_delta(self):
        """Apply deletion delta to lexicon state."""
        state = {"keep": "def1", "remove": "def2"}
        delta = LexiconDelta(
            delta_type=DeltaType.DELETION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data=["remove"],
        )
        result = delta.apply(state)
        assert "keep" in result
        assert "remove" not in result


class TestLexiconSynchronizer:
    """Test synchronization protocol between devices."""

    def test_create_synchronizer(self):
        """Synchronizer manages sync state between local and remote HLT."""
        local_hlt = HierarchicalLexiconTree()
        sync = LexiconSynchronizer(local_hlt)
        assert sync.local_hlt == local_hlt
        assert sync.state == SyncState.IDLE

    def test_compute_sync_request(self):
        """Generate sync request based on local state."""
        local_hlt = HierarchicalLexiconTree()
        local_hlt.add_domain("medical", "v1.0.0", hashlib.sha3_256(b"med").hexdigest())

        sync = LexiconSynchronizer(local_hlt)
        request = sync.compute_sync_request(remote_merkle_root="different_root")

        assert "missing_domains" in request or "outdated_domains" in request

    def test_process_sync_response(self):
        """Process incoming sync response with deltas."""
        local_hlt = HierarchicalLexiconTree()
        domain_id = local_hlt.add_domain(
            "legal", "v1.0.0", hashlib.sha3_256(b"leg").hexdigest()
        )

        sync = LexiconSynchronizer(local_hlt)
        delta = LexiconDelta(
            delta_type=DeltaType.ADDITION,
            source_version="v1.0.0",
            target_version="v1.0.1",
            data={"new_term": "definition"},
        )

        sync.process_sync_response(
            domain_id=domain_id, deltas=[delta], new_merkle_root="new_root_hash"
        )

        latest = local_hlt.get_latest_version("legal")
        assert latest["version"] == "v1.0.1"

    def test_sync_state_transitions(self):
        """Synchronizer transitions through proper states."""
        local_hlt = HierarchicalLexiconTree()
        sync = LexiconSynchronizer(local_hlt)

        assert sync.state == SyncState.IDLE

        sync.start_sync("remote_root")
        assert sync.state == SyncState.SYNCING

        sync.complete_sync()
        assert sync.state == SyncState.SYNCED

    def test_detect_semantic_drift(self):
        """Detect when local lexicon diverges from network."""
        local_hlt = HierarchicalLexiconTree()
        local_hlt.add_domain(
            "science", "v1.0.0", hashlib.sha3_256(b"sci_local").hexdigest()
        )

        sync = LexiconSynchronizer(local_hlt)
        # Remote has different content hash for same domain
        has_drift = sync.detect_drift(
            domain_name="science",
            remote_content_hash=hashlib.sha3_256(b"sci_remote").hexdigest(),
        )
        assert has_drift is True

    def test_no_drift_when_matched(self):
        """No drift detected when hashes match."""
        local_hlt = HierarchicalLexiconTree()
        content_hash = hashlib.sha3_256(b"matched").hexdigest()
        local_hlt.add_domain("math", "v1.0.0", content_hash)

        sync = LexiconSynchronizer(local_hlt)
        has_drift = sync.detect_drift("math", content_hash)
        assert has_drift is False


class TestHLTIntegration:
    """Integration tests for HLT with chunking system."""

    def test_hlt_validates_chunk_recipe(self):
        """HLT validates that device has correct AI adapter before chunk assembly."""
        hlt = HierarchicalLexiconTree()
        domain_id = hlt.add_domain(
            "news_layout", "v4.0.0", hashlib.sha3_256(b"news").hexdigest()
        )
        hlt.add_adapter(domain_id, "v4.0.1", b"layout_delta", "layout_anchor")

        # Device has the required adapter
        has_adapter = hlt.has_domain("news_layout")
        assert has_adapter is True

        latest = hlt.get_latest_version("news_layout")
        assert latest["version"] == "v4.0.1"

    def test_hlt_with_tag_index_discovery(self):
        """HLT integrates with tag overlay for discovering domain availability."""
        hlt = HierarchicalLexiconTree()
        hlt.add_domain(
            "medical",
            "v2.1.0",
            hashlib.sha3_256(b"med").hexdigest(),
            tags=["healthcare"],
        )
        hlt.add_domain(
            "legal", "v1.0.0", hashlib.sha3_256(b"leg").hexdigest(), tags=["law"]
        )

        # Query by tag
        medical_domains = [
            n
            for n in hlt.nodes.values()
            if n.node_type == NodeType.DOMAIN and "healthcare" in n.tags
        ]
        assert len(medical_domains) == 1
