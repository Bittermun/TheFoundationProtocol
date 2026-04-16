# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Content caching utilities for TFP operations.

This module provides in-memory caching for frequently accessed content
to reduce redundant BlobStore and IPFS lookups.
"""

from tfp_client.lib.cache.content_cache import (
    ContentCache,
    get_global_cache,
    reset_global_cache,
)

__all__ = ["ContentCache", "get_global_cache", "reset_global_cache"]
