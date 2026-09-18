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
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

try:
    import zstandard as zstd
except ImportError:
    zstd = None

from ..lexicon.hlt.tree import HierarchicalLexiconTree


@dataclasses.dataclass
class Content:
    root_hash: str
    data: bytes
    metadata: dict


log = logging.getLogger(__name__)

# Pre-trained domain seed dictionaries for high-ratio Zstandard compression
DOMAIN_SEEDS: Dict[str, bytes] = {
    "technical": (
        b"{\"status\": \"ok\", \"timestamp\": 0, \"version\": \"3.2\", \"hash\": \"\", "
        b"\"type\": \"task\", \"compute\": \"matrix\", \"algorithm\": \"ed25519\", "
        b"\"author\": \"tfp\", \"device_id\": \"\", \"shards\": [], \"reconstruction\": true, "
        b"\"protocol\": \"Foundation\", \"network\": \"mesh\", \"peer\": \"active\", "
        b"\"block\": 0, \"height\": 0, \"signature\": \"\", \"latency_ms\": 12.5}"
    ) * 32,
    "medical": (
        b"{\"patient_id\": \"\", \"diagnosis\": \"\", \"vitals\": {\"heart_rate\": 72, "
        b"\"blood_pressure\": \"120/80\", \"temperature\": 98.6}, \"medication\": [], "
        b"\"dosage_mg\": 500, \"frequency\": \"daily\", \"observations\": \"normal\"}"
    ) * 32,
    "legal": (
        b"{\"jurisdiction\": \"common_law\", \"party_a\": \"\", \"party_b\": \"\", "
        b"\"clause\": \"confidentiality\", \"governing_law\": \"delaware\", \"term_days\": 365, "
        b"\"indemnification\": true, \"liability_cap\": 1000000, \"arbitration\": \"mandatory\"}"
    ) * 32,
    "emergency": (
        b"{\"alert_level\": \"critical\", \"category\": \"weather\", \"action\": \"shelter\", "
        b"\"affected_radius_km\": 25, \"broadcast_epoch\": 0, \"coordinate\": {\"lat\": 0.0, \"lon\": 0.0}}"
    ) * 32,
}


class RealLexiconAdapter:
    """
    Real Lexicon adapter with HierarchicalLexiconTree and Zstandard dictionary compression.

    Provides true semantic reconstruction and bandwidth reduction by:
    1. Selecting domain-tailored Zstandard compression dictionaries
    2. Compressing/decompressing payloads losslessly with measured ratio metrics
    3. Indexing content keywords for live semantic/lexical discovery
    """

    def __init__(
        self,
        hlt: Optional[HierarchicalLexiconTree] = None,
        lexicon_dir: Optional[str] = None,
    ):
        """
        Initialize Lexicon adapter.

        Args:
            hlt: HierarchicalLexiconTree instance. If None, creates a new one.
            lexicon_dir: Optional explicit directory path to look for .zdict files.
        """
        self.hlt = hlt or HierarchicalLexiconTree()
        self.lexicon_dir = Path(lexicon_dir) if lexicon_dir else None
        self._dict_cache: Dict[str, Any] = {}
        self._search_index: Dict[str, Dict[str, Any]] = {}

        if zstd is not None:
            for domain_name in list(DOMAIN_SEEDS.keys()) + ["disaster_relief"]:
                self._load_domain_dict(domain_name)

    def _load_domain_dict(self, domain: str) -> Optional[Any]:
        """Load dictionary from disk if available, otherwise fallback to domain seeds."""
        if zstd is None:
            return None
        search_dirs = [Path("lexicons"), Path(__file__).resolve().parents[4] / "lexicons"]
        if self.lexicon_dir:
            search_dirs.insert(0, self.lexicon_dir)

        for base_dir in search_dirs:
            candidate = base_dir / f"{domain}.zdict"
            if candidate.exists():
                try:
                    self._dict_cache[domain] = zstd.ZstdCompressionDict(candidate.read_bytes())
                    return self._dict_cache[domain]
                except Exception as exc:
                    log.debug("Failed loading disk dict %s: %s", candidate, exc)

        seed = DOMAIN_SEEDS.get(domain, DOMAIN_SEEDS["technical"])
        try:
            self._dict_cache[domain] = zstd.ZstdCompressionDict(seed)
            return self._dict_cache[domain]
        except Exception:
            return None

    def _get_zstd_dict(self, domain: str) -> Optional[Any]:
        """Retrieve or construct Zstandard dictionary for domain."""
        if zstd is None:
            return None
        if domain in self._dict_cache:
            return self._dict_cache[domain]
        return self._load_domain_dict(domain)

    def decompress(
        self, file_bytes: Union[bytes, Content], tags: Optional[list] = None
    ) -> Union[Tuple[bytes, dict], bytes]:
        """Convenience method returning (decompressed_bytes, metadata_dict) or decompressed bytes."""
        if isinstance(file_bytes, Content):
            data = file_bytes.data
            content_tags = tags or file_bytes.metadata.get("tags", [])
            content = self.reconstruct(data, tags=content_tags)
            return content.data

        content = self.reconstruct(file_bytes, tags=tags)
        return content.data, content.metadata

    def compress(
        self, file_bytes: Union[bytes, Content], tags: Optional[list] = None
    ) -> Union[bytes, Content]:
        """
        Compress file bytes or Content object using the domain-specific Lexicon dictionary.
        """
        if isinstance(file_bytes, Content):
            content_obj = file_bytes
            content_tags = tags or content_obj.metadata.get("tags", [])
            comp_data = self.compress(content_obj.data, tags=content_tags)
            return Content(root_hash=content_obj.root_hash, data=comp_data, metadata=content_obj.metadata)

        if zstd is None:
            return file_bytes
        domain = self._select_domain(tags or [])
        dict_data = self._get_zstd_dict(domain)
        try:
            cctx = zstd.ZstdCompressor(dict_data=dict_data, level=3)
            return cctx.compress(file_bytes)
        except Exception as exc:
            log.warning("Lexicon compression fallback to raw bytes: %s", exc)
            return file_bytes

    def _select_domain(self, tags: list) -> str:
        """
        Select appropriate domain from HLT based on tags.

        Args:
            tags: Content tags

        Returns:
            Domain name string
        """
        tag_domain_map = {
            "medical": "medical",
            "healthcare": "medical",
            "biology": "medical",
            "legal": "legal",
            "law": "legal",
            "engineering": "technical",
            "code": "technical",
            "technical": "technical",
            "emergency": "emergency",
            "weather": "emergency",
            "alert": "emergency",
            "disaster_relief": "disaster_relief",
            "relief": "disaster_relief",
            "disaster": "disaster_relief",
        }

        for tag in tags:
            if not isinstance(tag, str):
                continue
            tag_lower = tag.lower()
            if tag_lower in tag_domain_map:
                return tag_domain_map[tag_lower]

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
        domain_bytes = domain.encode()
        combined = data + domain_bytes
        return hashlib.sha3_256(combined).hexdigest()

    def reconstruct(
        self, file_bytes: bytes, tags: Optional[list] = None, model=None
    ) -> Content:
        """
        Reconstruct content with semantic awareness and dictionary decompression.

        Args:
            file_bytes: Raw file bytes (either compressed with zstd or uncompressed)
            tags: Content tags for domain selection
            model: Optional AI model for advanced reconstruction

        Returns:
            Content object with semantic metadata and uncompressed data
        """
        domain = self._select_domain(tags or [])
        decompressed = file_bytes
        was_compressed = False
        dict_data = self._get_zstd_dict(domain)

        # Detect Zstandard frame magic bytes (\x28\xb5\x2f\xfd)
        if zstd is not None and len(file_bytes) >= 4 and file_bytes[:4] == b"\x28\xb5\x2f\xfd":
            try:
                dctx = zstd.ZstdDecompressor(dict_data=dict_data)
                decompressed = dctx.decompress(file_bytes)
                was_compressed = True
            except Exception:
                # Try decompressing without custom dictionary
                try:
                    dctx_plain = zstd.ZstdDecompressor()
                    decompressed = dctx_plain.decompress(file_bytes)
                    was_compressed = True
                except Exception:
                    decompressed = file_bytes

        root_hash = hashlib.sha3_256(decompressed).hexdigest()

        # Build semantic metadata
        domain_info = self.hlt.get_latest_version(domain) or {}
        orig_size = len(decompressed)
        wire_size = len(file_bytes)
        savings_pct = round((1.0 - (wire_size / orig_size)) * 100.0, 2) if was_compressed and orig_size > 0 else 0.0

        metadata = {
            "domain": domain,
            "reconstruction_method": "zstd_hlt_v2",
            "domain_version": domain_info.get("version", "1.0.0"),
            "was_compressed": was_compressed,
            "original_size": orig_size,
            "wire_size": wire_size,
            "bandwidth_savings_pct": savings_pct,
            "semantic_hash": self._compute_semantic_hash(decompressed, domain),
        }

        # Index text tokens for live search
        self.index_content(root_hash, decompressed, domain=domain, tags=tags or [])

        return Content(
            root_hash=root_hash,
            data=decompressed,
            metadata=metadata,
        )

    def index_content(
        self,
        content_hash: str,
        data: bytes,
        domain: str = "technical",
        tags: Optional[list] = None,
    ) -> None:
        """Index textual tokens of content for semantic/keyword search."""
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

        # Extract normalized words
        words = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
        tag_words = [t.lower() for t in (tags or []) if isinstance(t, str)]
        all_tokens = set(words).union(tag_words)

        self._search_index[content_hash] = {
            "tokens": all_tokens,
            "token_counts": Counter(words),
            "domain": domain,
            "tags": tags or [],
            "preview": text[:200].replace("\n", " "),
        }

    def semantic_search(
        self, query: str, domain: Optional[str] = None, limit: int = 10
    ) -> list:
        """
        Perform semantic keyword and tag search over indexed Lexicon content.

        Args:
            query: Search query
            domain: Optional domain filter
            limit: Maximum results

        Returns:
            List of matching content hashes with scores and snippets
        """
        query_words = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())
        if not query_words:
            return []

        results = []
        for content_hash, entry in self._search_index.items():
            if domain and entry["domain"] != domain:
                continue

            entry_tokens: Set[str] = entry["tokens"]
            entry_counts: Counter = entry["token_counts"]

            # Compute term overlap score
            matched_terms = [w for w in query_words if w in entry_tokens]
            if not matched_terms:
                continue

            # Weight by query coverage and frequency
            score = sum(entry_counts.get(w, 1) for w in matched_terms) / (len(query_words) + 1.0)
            results.append({
                "content_hash": content_hash,
                "score": round(score, 3),
                "domain": entry["domain"],
                "matched_terms": matched_terms,
                "snippet": entry.get("preview", ""),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

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
