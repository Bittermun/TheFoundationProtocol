# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hypothesis Property Testing for Nostr Gossip Protocol (Kinds 30078 & 30080).

Verifies invariants:
1. BIP-340 Schnorr Sign/Verify Roundtrip: Valid secp256k1 keys and SHA-256 digests verify 100%;
   bit-flipped signatures, messages, or keys strictly fail verification.
2. Replay Window Guard: _check_replay_window(event) returns False if |created_at - t_now| > 300s,
   returns True if <= 300s, and returns False on malformed/non-integer types.
3. Malformed Kind 30078 & 30080 JSON Handling: Fuzzing content payloads with arbitrary strings,
   truncated JSON, or unexpected structures yields zero unhandled exceptions.
4. Deduplication Invariant: Duplicate event IDs are dropped idempotently without state duplication.
"""

import hashlib
import json
import os
import time
import pytest
from hypothesis import given, settings, strategies as st

from tfp_client.lib.bridges.nostr_bridge import (
    _N,
    _P,
    _derive_pubkey_bytes,
    _schnorr_sign,
    _schnorr_verify,
)
from tfp_demo.server import (
    TFP_CONTENT_ANNOUNCE_KIND,
    TFP_CONTENT_KIND,
    _check_replay_window,
    _on_nostr_event,
    _seen_nostr_event_ids,
    _seen_nostr_ids_lock,
)


class TestNostrHypothesis:
    """Property-based verification of Nostr gossip protocol invariants."""

    @settings(max_examples=40, deadline=None)
    @given(
        sk_seed=st.binary(min_size=32, max_size=32),
        message_data=st.binary(min_size=0, max_size=2048),
    )
    def test_bip340_schnorr_sign_verify_roundtrip(self, sk_seed: bytes, message_data: bytes):
        """Invariant: BIP-340 Schnorr sign/verify roundtrip across valid secp256k1 keys."""
        # Derive private key within [1, _N - 1]
        sk_int = (int.from_bytes(sk_seed, "big") % (_N - 1)) + 1
        sk_bytes = sk_int.to_bytes(32, "big")

        pubkey_hex = _derive_pubkey_bytes(sk_bytes).hex()
        msg32 = hashlib.sha256(message_data).digest()
        event_id_hex = msg32.hex()

        sig_bytes = _schnorr_sign(sk_bytes, msg32)
        sig_hex = sig_bytes.hex()

        # Genuine signature must verify
        assert _schnorr_verify(pubkey_hex, event_id_hex, sig_hex) is True

        # Mutation: flip first byte of signature
        corrupted_sig = bytes([sig_bytes[0] ^ 0xFF]) + sig_bytes[1:]
        assert _schnorr_verify(pubkey_hex, event_id_hex, corrupted_sig.hex()) is False

        # Mutation: flip first byte of message digest
        corrupted_msg = bytes([msg32[0] ^ 0xFF]) + msg32[1:]
        assert _schnorr_verify(pubkey_hex, corrupted_msg.hex(), sig_hex) is False

        # Mutation: flip first byte of pubkey
        corrupted_pk = bytes([bytes.fromhex(pubkey_hex)[0] ^ 0xFF]) + bytes.fromhex(pubkey_hex)[1:]
        assert _schnorr_verify(corrupted_pk.hex(), event_id_hex, sig_hex) is False

    @settings(max_examples=50, deadline=None)
    @given(
        delta_seconds=st.integers(min_value=-2000, max_value=2000),
    )
    def test_replay_window_guard(self, delta_seconds: int):
        """Invariant: _check_replay_window returns False iff |created_at - t_now| > 300s."""
        t_now = int(time.time())
        created_at = t_now + delta_seconds
        event = {"created_at": created_at, "id": "test_id", "kind": 30080}

        is_accepted = _check_replay_window(event)
        if abs(delta_seconds) <= 300:
            assert is_accepted is True, f"Valid age {delta_seconds}s unexpectedly rejected"
        else:
            assert is_accepted is False, f"Expired age {delta_seconds}s unexpectedly accepted"

    @settings(max_examples=40, deadline=None)
    @given(
        invalid_created_at=st.one_of(
            st.none(),
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz!@#$%^&*()", min_size=1, max_size=20),
            st.lists(st.integers(), min_size=1, max_size=3),
            st.dictionaries(st.text(), st.text()),
        )
    )
    def test_replay_window_malformed_types(self, invalid_created_at):
        """Invariant: _check_replay_window handles malformed types gracefully without raising."""
        event = {"created_at": invalid_created_at}
        assert _check_replay_window(event) is False

    @settings(max_examples=50, deadline=None)
    @given(
        kind=st.sampled_from([TFP_CONTENT_KIND, TFP_CONTENT_ANNOUNCE_KIND, 30079, 30081]),
        fuzzed_content=st.one_of(
            st.text(max_size=2048),
            st.binary(max_size=1024).map(lambda b: b.decode("latin1")),
            st.dictionaries(
                st.text(max_size=30),
                st.one_of(st.text(max_size=50), st.integers(), st.booleans(), st.none()),
                max_size=10,
            ).map(json.dumps),
        ),
    )
    def test_malformed_kind_json_graceful_handling(self, kind: int, fuzzed_content: str):
        """
        Invariant: Fuzzing Kind 30078 (HLT gossip) and 30080 (content announce) JSON content
        never produces unhandled 500 exceptions. All errors are caught and logged.
        """
        t_now = int(time.time())
        event_id = hashlib.sha256(f"{kind}:{fuzzed_content}:{time.time_ns()}".encode()).hexdigest()

        event = {
            "id": event_id,
            "pubkey": "a" * 64,
            "created_at": t_now,
            "kind": kind,
            "tags": [["t", "test"]],
            "content": fuzzed_content,
            "sig": "b" * 128,
        }

        # Should execute cleanly without raising any exception
        try:
            _on_nostr_event(event)
        except Exception as exc:
            pytest.fail(f"_on_nostr_event crashed on fuzzed input for kind {kind}: {exc}")

    @settings(max_examples=30, deadline=None)
    @given(
        event_seed=st.text(min_size=1, max_size=50),
    )
    def test_deduplication_invariant(self, event_seed: str):
        """Invariant: Duplicate event IDs are dropped idempotently without reprocessing."""
        t_now = int(time.time())
        event_id = hashlib.sha256(f"dedup_test_{event_seed}_{time.time_ns()}".encode()).hexdigest()

        event = {
            "id": event_id,
            "pubkey": "a" * 64,
            "created_at": t_now,
            "kind": TFP_CONTENT_ANNOUNCE_KIND,
            "tags": [],
            "content": json.dumps({"hash": "0" * 64, "tags": ["fuzz"]}),
            "sig": "0" * 128,
        }

        # First ingestion
        _on_nostr_event(event)
        with _seen_nostr_ids_lock:
            assert event_id in _seen_nostr_event_ids

        # Count how many times event_id appears in seen buffer
        with _seen_nostr_ids_lock:
            count_before = _seen_nostr_event_ids.count(event_id)

        # Second ingestion of the same event
        _on_nostr_event(event)

        with _seen_nostr_ids_lock:
            count_after = _seen_nostr_event_ids.count(event_id)

        assert count_before == count_after == 1, "Duplicate event ID was appended more than once"
