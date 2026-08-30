# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Manifest Module

Provides high-level interfaces for Tier 1 PQC Content & Governance Manifests
and Tier 2 Intra-Mesh Hop Transport Authentication.
"""

from typing import Any, Dict, List, Optional

from tfp_core.crypto.manifest_agility import (
    PQCAlgorithm,
    Tier1ContentManifest,
    Tier1ManifestSigner,
    Tier2HopAuthenticator,
    TieredManifestManager,
)


def create_tiered_manifest(
    content_hash: str,
    total_size: int,
    chunk_hashes: List[str],
    chunk_sizes: List[int],
    author_pubkey: bytes,
    author_privkey: bytes,
    algorithm: str = "dilithium5",
    fountain_params: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tier1ContentManifest:
    """Create and sign a Tier 1 PQC Content Manifest."""
    manager = TieredManifestManager()
    return manager.create_manifest(
        content_hash=content_hash,
        total_size=total_size,
        chunk_hashes=chunk_hashes,
        chunk_sizes=chunk_sizes,
        author_pubkey=author_pubkey,
        author_privkey=author_privkey,
        algorithm=algorithm,
        fountain_params=fountain_params,
        metadata=metadata,
    )


def verify_tiered_manifest(
    manifest: Tier1ContentManifest,
    author_pubkey: Optional[bytes] = None,
) -> bool:
    """Verify a Tier 1 PQC Content Manifest."""
    manager = TieredManifestManager()
    return manager.verify_manifest(manifest, author_pubkey)


__all__ = [
    "PQCAlgorithm",
    "Tier1ContentManifest",
    "Tier1ManifestSigner",
    "Tier2HopAuthenticator",
    "TieredManifestManager",
    "create_tiered_manifest",
    "verify_tiered_manifest",
]
