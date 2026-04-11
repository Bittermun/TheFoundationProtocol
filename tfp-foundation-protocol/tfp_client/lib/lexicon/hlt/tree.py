"""
Hierarchical Lexicon Tree (HLT) - Core Tree Structure

The HLT ensures all devices share the same generative prior (AI model weights,
grammar, dictionary) to prevent semantic drift when reconstructing content from hashes.

Structure:
  ROOT (base lexicon v1.0.0)
  ├── DOMAIN: medical (v2.1.0) [tags: healthcare, biology]
  │   └── ADAPTER: medical_adapter_001 (v2.1.1) [precision_anchor: anchor_med_42]
  ├── DOMAIN: legal (v1.0.0) [tags: law]
  │   └── ADAPTER: legal_adapter_001 (v1.0.1)
  └── DOMAIN: technical (v3.0.0) [tags: engineering, code]
"""

import dataclasses
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(Enum):
    """Types of nodes in the HLT hierarchy."""

    ROOT = "root"  # Base lexicon
    DOMAIN = "domain"  # Domain-specific lexicon (medical, legal, etc.)
    ADAPTER = "adapter"  # Delta updates for specific domains


@dataclasses.dataclass
class LexiconNode:
    """A node in the Hierarchical Lexicon Tree."""

    node_id: str
    node_type: NodeType
    version: str
    content_hash: str
    parent_id: Optional[str] = None
    tags: List[str] = dataclasses.field(default_factory=list)
    precision_anchor: Optional[str] = None
    created_at: str = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Serialize node to dictionary."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "version": self.version,
            "content_hash": self.content_hash,
            "parent_id": self.parent_id,
            "tags": self.tags,
            "precision_anchor": self.precision_anchor,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "LexiconNode":
        """Deserialize node from dictionary."""
        return cls(
            node_id=data["node_id"],
            node_type=NodeType(data["node_type"]),
            version=data["version"],
            content_hash=data["content_hash"],
            parent_id=data.get("parent_id"),
            tags=data.get("tags", []),
            precision_anchor=data.get("precision_anchor"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


class HierarchicalLexiconTree:
    """
    Hierarchical Lexicon Tree for semantic synchronization.

    Maintains a tree of lexicon versions with domain-specific branches
    and adapter deltas for efficient updates.
    """

    def __init__(self):
        self.nodes: Dict[str, LexiconNode] = {}
        self.domain_names: Dict[str, str] = {}  # name -> node_id mapping
        self._initialize_root()

    def _initialize_root(self):
        """Create root node representing base lexicon."""
        root = LexiconNode(
            node_id="root",
            node_type=NodeType.ROOT,
            version="v1.0.0",
            content_hash=hashlib.sha3_256(b"base_lexicon_v1").hexdigest(),
        )
        self.nodes["root"] = root

    @property
    def root(self) -> LexiconNode:
        """Get root node."""
        return self.nodes["root"]

    def add_domain(
        self,
        name: str,
        version: str,
        content_hash: str,
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Add a domain-specific lexicon as child of root.

        Args:
            name: Domain name (e.g., "medical", "legal")
            version: Version string (e.g., "v2.1.0")
            content_hash: SHA3-256 hash of lexicon content
            tags: Optional tags for discovery

        Returns:
            node_id of created domain
        """
        node_id = f"{name}_{version.replace('.', '_')}"

        if name in self.domain_names:
            # Update existing domain's version reference
            old_id = self.domain_names[name]
            if self.nodes[old_id].version < version:
                self.domain_names[name] = node_id

        node = LexiconNode(
            node_id=node_id,
            node_type=NodeType.DOMAIN,
            version=version,
            content_hash=content_hash,
            parent_id="root",
            tags=tags or [],
        )
        self.nodes[node_id] = node
        self.domain_names[name] = node_id
        return node_id

    def add_adapter(
        self, domain_id: str, version: str, delta_content: bytes, precision_anchor: str
    ) -> str:
        """
        Add an adapter delta to an existing domain.

        Args:
            domain_id: Parent domain node ID
            version: Adapter version
            delta_content: Binary delta data
            precision_anchor: Anchor point for precise application

        Returns:
            node_id of created adapter
        """
        if domain_id not in self.nodes:
            raise ValueError(f"Domain {domain_id} not found")

        domain = self.nodes[domain_id]
        if domain.node_type != NodeType.DOMAIN:
            raise ValueError(f"{domain_id} is not a domain node")

        content_hash = hashlib.sha3_256(delta_content).hexdigest()
        node_id = f"{domain_id}_adapter_{version.replace('.', '_')}"

        node = LexiconNode(
            node_id=node_id,
            node_type=NodeType.ADAPTER,
            version=version,
            content_hash=content_hash,
            parent_id=domain_id,
            precision_anchor=precision_anchor,
        )
        self.nodes[node_id] = node
        return node_id

    def get_node(self, node_id: str) -> LexiconNode:
        """Get node by ID."""
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found")
        return self.nodes[node_id]

    def get_path_from_root(self, node_id: str) -> List[LexiconNode]:
        """
        Get full path from root to specified node.

        Returns:
            List of nodes from root to target (inclusive)
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found")

        path = []
        current_id = node_id

        while current_id:
            node = self.nodes[current_id]
            path.append(node)
            current_id = node.parent_id

        path.reverse()
        return path

    def has_domain(self, name: str) -> bool:
        """Check if tree contains domain by name."""
        return name in self.domain_names

    def get_latest_version(self, domain_name: str) -> Dict[str, str]:
        """
        Get latest version info for a domain including all adapters.

        Returns:
            Dict with version, node_id, and adapter count
        """
        if domain_name not in self.domain_names:
            return {"version": None, "node_id": None, "adapter_count": 0}

        domain_id = self.domain_names[domain_name]
        domain = self.nodes[domain_id]

        # Find all adapters for this domain
        adapters = [
            n
            for n in self.nodes.values()
            if n.node_type == NodeType.ADAPTER and n.parent_id == domain_id
        ]

        # Sort by version to find latest
        if adapters:
            adapters.sort(key=lambda x: x.version, reverse=True)
            latest_adapter = adapters[0]
            return {
                "version": latest_adapter.version,
                "node_id": latest_adapter.node_id,
                "adapter_count": len(adapters),
                "base_version": domain.version,
            }

        return {
            "version": domain.version,
            "node_id": domain_id,
            "adapter_count": 0,
            "base_version": domain.version,
        }

    def compute_merkle_root(self) -> str:
        """
        Compute Merkle root of entire tree for verification.

        Returns:
            SHA3-256 hash of tree state
        """
        # Sort nodes by ID for deterministic ordering
        sorted_nodes = sorted(self.nodes.values(), key=lambda x: x.node_id)

        # Hash each node's essential data
        leaf_hashes = []
        for node in sorted_nodes:
            data = f"{node.node_id}:{node.version}:{node.content_hash}"
            leaf_hashes.append(hashlib.sha3_256(data.encode()).hexdigest())

        # Build Merkle tree
        if not leaf_hashes:
            return hashlib.sha3_256(b"empty_tree").hexdigest()

        while len(leaf_hashes) > 1:
            if len(leaf_hashes) % 2 == 1:
                leaf_hashes.append(leaf_hashes[-1])

            new_level = []
            for i in range(0, len(leaf_hashes), 2):
                combined = leaf_hashes[i] + leaf_hashes[i + 1]
                new_level.append(hashlib.sha3_256(combined.encode()).hexdigest())
            leaf_hashes = new_level

        return leaf_hashes[0]

    def to_dict(self) -> Dict:
        """Serialize entire tree to dictionary."""
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "domain_names": self.domain_names,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "HierarchicalLexiconTree":
        """Deserialize tree from dictionary."""
        hlt = cls()
        hlt.nodes = {
            nid: LexiconNode.from_dict(ndata) for nid, ndata in data["nodes"].items()
        }
        hlt.domain_names = data.get("domain_names", {})
        return hlt
