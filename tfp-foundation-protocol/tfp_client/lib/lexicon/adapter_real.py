# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Real Lexicon adapter for semantic content reconstruction.

Uses HierarchicalLexiconTree for domain-aware reconstruction and
semantic search capabilities.
"""

import dataclasses
import hashlib
import logging
from typing import Optional

from ..lexicon.hlt.tree import HierarchicalLexiconTree, LexiconNode

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Content:
    root_hash: str
    data: bytes
    metadata: dict


class RealLexiconAdapter:
    """
    Real Lexicon adapter with HierarchicalLexiconTree integration.
    
    Provides semantic reconstruction by:
    1. Selecting appropriate domain lexicon based on content tags
    2. Applying adapter deltas for precision reconstruction
    3. Computing semantic similarity scores for search
    """

    def __init__(self, hlt: Optional[HierarchicalLexiconTree] = None):
        """
        Initialize Lexicon adapter.
        
        Args:
            hlt: HierarchicalLexiconTree instance. If None, creates a new one.
        """
        self.hlt = hlt or HierarchicalLexiconTree()
        self._domain_cache = {}  # Cache for domain selection

    def reconstruct(
        self, file_bytes: bytes, tags: Optional[list] = None, model=None
    ) -> Content:
        """
        Reconstruct content with semantic awareness.
        
        For the current implementation, this performs basic reconstruction
        with metadata enrichment. Future versions would apply actual
        semantic transformations based on the HLT.
        
        Args:
            file_bytes: Raw file bytes from RaptorQ decode
            tags: Content tags for domain selection
            model: Optional AI model for advanced reconstruction
            
        Returns:
            Content object with semantic metadata
        """
        root_hash = hashlib.sha3_256(file_bytes).hexdigest()
        
        # Select domain based on tags
        domain = self._select_domain(tags or [])
        
        # Build semantic metadata
        domain_info = self.hlt.get_latest_version(domain) or {}
        metadata = {
            "domain": domain,
            "reconstruction_method": "hlt_v1",
            "domain_version": domain_info.get("version"),
            "semantic_hash": self._compute_semantic_hash(file_bytes, domain),
        }
        
        # In a full implementation, we would:
        # 1. Apply domain-specific lexicon transformations
        # 2. Use adapter deltas for precision reconstruction
        # 3. Validate reconstruction against HLT constraints
        
        # For now, return the bytes with enriched metadata
        return Content(
            root_hash=root_hash,
            data=file_bytes,
            metadata=metadata,
        )

    def _select_domain(self, tags: list) -> str:
        """
        Select appropriate domain from HLT based on tags.
        
        Args:
            tags: Content tags
            
        Returns:
            Domain name string
        """
        # Simple tag-to-domain mapping
        # In a full implementation, this would use semantic similarity
        tag_domain_map = {
            "medical": "medical",
            "healthcare": "medical",
            "biology": "medical",
            "legal": "legal",
            "law": "legal",
            "engineering": "technical",
            "code": "technical",
            "technical": "technical",
        }
        
        for tag in tags:
            # Handle non-string tags gracefully
            if not isinstance(tag, str):
                continue
            tag_lower = tag.lower()
            if tag_lower in tag_domain_map:
                return tag_domain_map[tag_lower]
        
        # Default to technical domain
        return "technical"

    def _compute_semantic_hash(self, data: bytes, domain: str) -> str:
        """
        Compute domain-aware semantic hash.
        
        Args:
            data: Content data
            domain: Selected domain
            
        Returns:
            Semantic hash string
        """
        # Combine data with domain for domain-specific hash
        domain_bytes = domain.encode()
        combined = data + domain_bytes
        return hashlib.sha3_256(combined).hexdigest()

    def semantic_search(
        self, query: str, domain: Optional[str] = None, limit: int = 10
    ) -> list:
        """
        Perform semantic search using HLT.
        
        Args:
            query: Search query
            domain: Optional domain filter
            limit: Maximum results
            
        Returns:
            List of matching content hashes with scores
        """
        # Placeholder for semantic search
        # In a full implementation, this would:
        # 1. Embed query using domain-specific lexicon
        # 2. Search HLT for similar content
        # 3. Return ranked results with similarity scores
        
        log.warning("Semantic search not fully implemented yet")
        return []

    def add_domain_lexicon(
        self, name: str, version: str, content_hash: str, tags: Optional[list] = None
    ) -> str:
        """
        Add a domain lexicon to the HLT.
        
        Args:
            name: Domain name
            version: Version string
            content_hash: Hash of lexicon content
            tags: Optional tags
            
        Returns:
            Node ID of created domain
        """
        return self.hlt.add_domain(name, version, content_hash, tags)

    def add_adapter_delta(
        self,
        domain_id: str,
        version: str,
        delta_content: bytes,
        precision_anchor: str,
    ) -> str:
        """
        Add an adapter delta to a domain.
        
        Args:
            domain_id: Parent domain node ID
            version: Adapter version
            delta_content: Binary delta data
            precision_anchor: Anchor point for precise application
            
        Returns:
            Node ID of created adapter
        """
        return self.hlt.add_adapter(domain_id, version, delta_content, precision_anchor)

    def get_tree_state(self) -> dict:
        """Get current HLT state for debugging/monitoring."""
        return self.hlt.to_dict()
