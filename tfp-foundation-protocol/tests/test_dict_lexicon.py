# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
tests/test_dict_lexicon.py

Tests for DictLexiconAdapter — deterministic text/dictionary domain adapter.

Verifies:
- Term expansion inserts "(full phrase)" annotations.
- Repeated occurrences of the same term only expand once.
- Binary content is returned unchanged.
- root_hash is always SHA3-256 of the original bytes (not the expanded bytes).
- DictLexiconAdapter.domains() returns the expected domain set.
- Custom extra_terms are merged with the built-in dictionary.
- expand_terms() public function works standalone.
"""

import hashlib

import pytest

from tfp_client.lib.lexicon.dict_lexicon_adapter import (
    DictLexiconAdapter,
    _DEFAULT_TERMS,
    expand_terms,
)


# ---------------------------------------------------------------------------
# expand_terms unit tests
# ---------------------------------------------------------------------------


def test_expand_terms_inserts_expansion():
    text = "TFP is a decentralised protocol."
    result = expand_terms(text, _DEFAULT_TERMS)
    assert "TFP (The Foundation Protocol)" in result


def test_expand_terms_expands_habp():
    text = "HABP consensus requires 3 devices."
    result = expand_terms(text, _DEFAULT_TERMS)
    assert "HABP (Heterogeneous Autonomous Byzantine Protocol)" in result


def test_expand_terms_repeats_not_expanded_twice():
    text = "TFP uses TFP protocol."
    result = expand_terms(text, _DEFAULT_TERMS)
    # Only first occurrence should be expanded
    assert result.count("(The Foundation Protocol)") == 1


def test_expand_terms_word_boundary():
    """HTTPS should not expand inside 'NotHTTPSLike'."""
    text = "Use HTTPS for secure connections. NotHTTPSLike is different."
    result = expand_terms(text, _DEFAULT_TERMS)
    assert "HTTPS (HTTP Secure)" in result
    # The non-boundary occurrence should not trigger expansion
    assert "NotHTTPSLike (HTTP Secure)" not in result


def test_expand_terms_multiple_different_terms():
    text = "TFP uses NDN, ZKP, and PUF."
    result = expand_terms(text, _DEFAULT_TERMS)
    assert "TFP (The Foundation Protocol)" in result
    assert "NDN (Named Data Networking)" in result
    assert "ZKP (Zero-Knowledge Proof)" in result
    assert "PUF (Physical Unclonable Function)" in result


def test_expand_terms_custom_terms():
    custom = {"MYTERM": "My Custom Term"}
    text = "Use MYTERM here."
    result = expand_terms(text, {**_DEFAULT_TERMS, **custom})
    assert "MYTERM (My Custom Term)" in result


def test_expand_terms_empty_text():
    assert expand_terms("", _DEFAULT_TERMS) == ""


def test_expand_terms_no_known_terms_unchanged():
    text = "Hello world, nothing to expand here."
    result = expand_terms(text, _DEFAULT_TERMS)
    assert result == text


# ---------------------------------------------------------------------------
# DictLexiconAdapter.reconstruct tests
# ---------------------------------------------------------------------------


def test_reconstruct_plain_text():
    adapter = DictLexiconAdapter()
    original = b"The TFP node uses NDN for data retrieval."
    content = adapter.reconstruct(original)
    assert "TFP (The Foundation Protocol)" in content.data.decode()
    assert "NDN (Named Data Networking)" in content.data.decode()
    assert content.metadata["expanded"] is True


def test_reconstruct_root_hash_is_of_original_bytes():
    """root_hash must be SHA3-256 of original bytes, not expanded bytes."""
    adapter = DictLexiconAdapter()
    original = b"TFP and HABP and ZKP."
    content = adapter.reconstruct(original)
    expected_hash = hashlib.sha3_256(original).hexdigest()
    assert content.root_hash == expected_hash


def test_reconstruct_binary_content_unchanged():
    """Binary bytes that are not valid UTF-8 must be returned unchanged."""
    adapter = DictLexiconAdapter()
    binary = bytes(range(256))
    content = adapter.reconstruct(binary)
    assert content.data == binary
    assert content.metadata["expanded"] is False
    assert content.metadata["domain"] == "binary"


def test_reconstruct_metadata_includes_lengths():
    adapter = DictLexiconAdapter()
    original = b"TFP protocol."
    content = adapter.reconstruct(original)
    assert "original_length" in content.metadata
    assert "expanded_length" in content.metadata
    assert content.metadata["original_length"] == len(original)
    assert content.metadata["expanded_length"] >= len(original)


def test_reconstruct_no_expansion_if_no_known_terms():
    adapter = DictLexiconAdapter()
    original = b"Hello world, plain text."
    content = adapter.reconstruct(original)
    # No TFP/protocol terms → data unchanged, expanded=False
    assert content.data == original
    assert content.metadata["expanded"] is False


def test_reconstruct_extra_terms():
    adapter = DictLexiconAdapter(extra_terms={"MYABB": "My Abbreviation"})
    original = b"Use MYABB in the text."
    content = adapter.reconstruct(original)
    assert "MYABB (My Abbreviation)" in content.data.decode()


def test_reconstruct_model_arg_ignored():
    """model parameter must not affect output (API compatibility with LexiconAdapter)."""
    adapter = DictLexiconAdapter()
    original = b"TFP node."
    content_no_model = adapter.reconstruct(original)
    content_with_model = adapter.reconstruct(original, model="fake_model")
    assert content_no_model.data == content_with_model.data
    assert content_no_model.root_hash == content_with_model.root_hash


# ---------------------------------------------------------------------------
# Domain awareness
# ---------------------------------------------------------------------------


def test_domains_returns_frozenset():
    adapter = DictLexiconAdapter()
    domains = adapter.domains()
    assert isinstance(domains, frozenset)
    assert "text" in domains
    assert "dictionary" in domains
    assert "general" in domains


def test_custom_domains():
    adapter = DictLexiconAdapter(domains=["code", "text"])
    assert "code" in adapter.domains()
    assert "dictionary" not in adapter.domains()


def test_term_count():
    count = DictLexiconAdapter.term_count()
    assert count >= 20  # At minimum the built-in dictionary size


# ---------------------------------------------------------------------------
# API compatibility with LexiconAdapter (duck typing)
# ---------------------------------------------------------------------------


def test_duck_typing_compatible_with_lexicon_adapter():
    """DictLexiconAdapter must satisfy the same interface as LexiconAdapter."""
    from tfp_client.lib.lexicon.adapter import Content

    adapter = DictLexiconAdapter()
    file_bytes = b"TFP protocol test."
    result = adapter.reconstruct(file_bytes)
    assert isinstance(result, Content)
    assert isinstance(result.root_hash, str) and len(result.root_hash) == 64
    assert isinstance(result.data, bytes)
    assert isinstance(result.metadata, dict)
