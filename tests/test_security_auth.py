# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import pytest
from tfp_client.lib.fountain.raptorq_ffi import RealRaptorQAdapter, IntegrityError, _shard_hmac


def test_fallback_shard_without_hmac_rejected_when_key_supplied():
    """
    Security verification: A forged packet prefixed with b'fallback_shard_'
    must NOT bypass authentication if an hmac_key is provided.
    """
    adapter = RealRaptorQAdapter()
    key = b"secret-authentication-key-123"

    # Attacker crafts an unauthenticated fallback shard
    forged_shard = b"fallback_shard_MALICIOUS_INJECTED_CONTENT"

    # Should raise IntegrityError or ValueError because HMAC tag is missing or invalid
    with pytest.raises((IntegrityError, ValueError)):
        adapter.decode([forged_shard], k=1, hmac_key=key)


def test_fallback_shard_with_valid_hmac_accepted_when_key_supplied():
    """
    Legitimate NDN fallback shard carrying a valid HMAC tag is accepted.
    """
    adapter = RealRaptorQAdapter()
    key = b"secret-authentication-key-123"
    content = b"fallback_shard_LEGITIMATE_CONTENT"

    # Append valid HMAC
    valid_mac = _shard_hmac(key, content)
    authenticated_shard = content + valid_mac

    decoded = adapter.decode([authenticated_shard], k=1, hmac_key=key)
    assert decoded == b"LEGITIMATE_CONTENT"
