# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
DictLexiconAdapter — deterministic text/dictionary domain term-expansion adapter.

Replaces the identity-stub ``LexiconAdapter`` for text/dictionary domains.  No GPU
or large-model required: operates on a built-in ``Dict[str, str]`` term map that
expands well-known TFP/protocol abbreviations so downstream consumers (template
assembler, search indexer, HLT gossip) work with fully-expanded prose.

Design notes
------------
- Pure-Python, zero optional dependencies.
- Deterministic: same input → same output (safe for content-addressed hashing).
- Domain-aware: only expands when ``domain`` in metadata is ``"text"`` or
  ``"dictionary"`` (caller can override via constructor).
- Thread-safe: the term map is read-only after construction.
"""

import hashlib
import re
from typing import Dict, List, Optional, Tuple

from tfp_client.lib.lexicon.adapter import Content


# ---------------------------------------------------------------------------
# Built-in term dictionary
# ---------------------------------------------------------------------------

_DEFAULT_TERMS: Dict[str, str] = {
    # TFP-specific
    "TFP": "The Foundation Protocol",
    "HABP": "Heterogeneous Autonomous Byzantine Protocol",
    "HLT": "Hierarchical Lexicon Tree",
    "NDN": "Named Data Networking",
    "PUF": "Physical Unclonable Function",
    "TEE": "Trusted Execution Environment",
    "ZKP": "Zero-Knowledge Proof",
    "IPFS": "InterPlanetary File System",
    "CID": "Content Identifier",
    "PoW": "Proof of Work",
    "LDM": "Latent Diffusion Model",
    "RaptorQ": "RaptorQ erasure coding",
    "NIP": "Nostr Implementation Possibility",
    # General networking
    "API": "Application Programming Interface",
    "REST": "Representational State Transfer",
    "HTTP": "HyperText Transfer Protocol",
    "HTTPS": "HTTP Secure",
    "WSS": "WebSocket Secure",
    "WS": "WebSocket",
    "TCP": "Transmission Control Protocol",
    "IP": "Internet Protocol",
    "DNS": "Domain Name System",
    "URL": "Uniform Resource Locator",
    "URI": "Uniform Resource Identifier",
    # Security
    "HMAC": "Hash-based Message Authentication Code",
    "SHA": "Secure Hash Algorithm",
    "AES": "Advanced Encryption Standard",
    "RSA": "Rivest–Shamir–Adleman",
    "TLS": "Transport Layer Security",
    "SSL": "Secure Sockets Layer",
    # Storage / databases
    "DB": "database",
    "SQL": "Structured Query Language",
    "SQLite": "SQLite embedded database",
    "WAL": "Write-Ahead Log",
    # Development
    "CLI": "Command Line Interface",
    "UI": "User Interface",
    "SDK": "Software Development Kit",
    "ORM": "Object-Relational Mapper",
    "CRUD": "Create, Read, Update, Delete",
    "CI": "Continuous Integration",
    "CD": "Continuous Deployment",
}


# ---------------------------------------------------------------------------
# Expansion helpers
# ---------------------------------------------------------------------------


def _build_pattern(terms: Dict[str, str]) -> Tuple[re.Pattern, Dict[str, str]]:
    """
    Compile a single regex that matches any key in *terms* as a whole word,
    case-sensitive (acronyms are usually uppercase; mixed-case handled via
    ``re.IGNORECASE`` is deliberately avoided to prevent false expansions).

    Returns the compiled pattern and a case-normalised lookup dict.
    """
    # Sort longest first to prevent partial matches (e.g. "SHA" before "SHA-256")
    sorted_keys = sorted(terms.keys(), key=len, reverse=True)
    escaped = [re.escape(k) for k in sorted_keys]
    pattern = re.compile(r"\b(?:" + "|".join(escaped) + r")\b")
    return pattern, terms


def expand_terms(text: str, terms: Dict[str, str]) -> str:
    """
    Expand abbreviations in *text* using the provided *terms* dictionary.

    Each occurrence of a term key as a whole word is replaced with
    ``"{key} ({expansion})"`` so that the original token is preserved alongside
    the expansion.  Repeated occurrences within the same passage are expanded
    only the first time to avoid noisy text.

    Args:
        text: Source text to expand.
        terms: Mapping of abbreviation → full phrase.

    Returns:
        Text with expansions inserted inline.
    """
    pattern, lookup = _build_pattern(terms)
    already_expanded: set = set()

    def _replace(m: re.Match) -> str:
        token = m.group(0)
        if token in already_expanded:
            return token
        expansion = lookup.get(token)
        if expansion is None:
            return token
        already_expanded.add(token)
        return f"{token} ({expansion})"

    return pattern.sub(_replace, text)


# ---------------------------------------------------------------------------
# DictLexiconAdapter
# ---------------------------------------------------------------------------


class DictLexiconAdapter:
    """
    Deterministic text/dictionary domain content adapter.

    Expands well-known TFP/protocol abbreviations in plain-text content so
    that downstream semantic search, HLT gossip, and recipe assembly work with
    fully-expanded prose rather than opaque acronyms.

    Replaces the 4-line identity stub ``LexiconAdapter`` for text and dictionary
    domains.  Compatible with the same ``reconstruct(file_bytes, model=None)``
    calling convention.

    Args:
        extra_terms: Optional additional ``{abbreviation: expansion}`` entries
            merged on top of the built-in dictionary.
        domains: Domain names this adapter should accept.  Defaults to the
            common text/dictionary set.
    """

    DEFAULT_DOMAINS: frozenset = frozenset({"text", "dictionary", "general"})

    def __init__(
        self,
        extra_terms: Optional[Dict[str, str]] = None,
        domains: Optional[List[str]] = None,
    ) -> None:
        self._terms: Dict[str, str] = dict(_DEFAULT_TERMS)
        if extra_terms:
            self._terms.update(extra_terms)
        self._domains = frozenset(domains) if domains else self.DEFAULT_DOMAINS

    # ------------------------------------------------------------------
    # Public API  (same interface as LexiconAdapter.reconstruct)
    # ------------------------------------------------------------------

    def reconstruct(self, file_bytes: bytes, model=None) -> Content:
        """
        Decode *file_bytes* as UTF-8 text, expand known abbreviations, and
        return a ``Content`` object whose ``data`` field holds the expanded
        bytes.

        If the bytes are not valid UTF-8 (binary content), the original bytes
        are returned unchanged — the adapter never raises on binary input.

        Args:
            file_bytes: Raw content bytes.
            model: Ignored — kept for API compatibility with LexiconAdapter.

        Returns:
            ``Content(root_hash, data, metadata)`` where
            ``metadata["expanded"]`` is True when expansions were applied.
        """
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # Binary content: return unchanged
            return Content(
                root_hash=hashlib.sha3_256(file_bytes).hexdigest(),
                data=file_bytes,
                metadata={"expanded": False, "domain": "binary"},
            )

        expanded = expand_terms(text, self._terms)
        expanded_bytes = expanded.encode("utf-8")

        return Content(
            root_hash=hashlib.sha3_256(file_bytes).hexdigest(),
            data=expanded_bytes,
            metadata={
                "expanded": expanded_bytes != file_bytes,
                "domain": "dictionary",
                "original_length": len(file_bytes),
                "expanded_length": len(expanded_bytes),
            },
        )

    def domains(self) -> frozenset:
        """Return the set of domain names this adapter handles."""
        return self._domains

    @classmethod
    def term_count(cls) -> int:
        """Return the number of built-in terms."""
        return len(_DEFAULT_TERMS)
