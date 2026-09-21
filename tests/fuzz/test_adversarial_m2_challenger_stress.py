# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial Empirical Stress Testing Suite for Milestone 2.
Constructed by challenger_m2_1 to adversarially challenge and verify:
1. FastCDC & Merkle Trees:
   - Corrupted chunk hashes, truncated payloads, forged Merkle roots are strictly rejected.
   - Boundary values: 0 bytes, 1 byte, 100KB, exact min/target/max chunk boundaries.
2. Nostr Gossip Protocol:
   - Invalid Schnorr signatures, event ID tampering, replay timestamps >300s, malformed Kind 30078/30080 JSON.
   - Zero unhandled 500 internal server exceptions under fuzz payloads.
3. Fountain Codec & Anti-Pollution Invariants:
   - Byzantine droplet injection and tampered repair seeds.
   - O(1) time verification in verify_droplet_seed_authenticity.
   - Bit-exact GF(2) recovery under 40% and 50% packet erasure channels.
"""

import hashlib
import hmac
import json
import os
import random
import struct
import tempfile
import time
from typing import Dict, List

import pytest
from starlette.testclient import TestClient

from tfp_core_v4.cdc import ContentDefinedChunker, ChunkRecipe
from tfp_core_v4.merkle import MerkleTree, sha3_256, verify_merkle_proof
from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    _sample_soliton_degree,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)
from tfp_core_v4.node import TFPNode
from tfp_transport.fountain import TransportFountainChannel
from tfp_client.lib.bridges.nostr_bridge import (
    _N,
    _derive_pubkey_bytes,
    _schnorr_sign,
    _schnorr_verify,
)
from tfp_demo.server import (
    app,
    _check_replay_window,
    _on_nostr_event,
    _verify_nostr_event,
    TFP_CONTENT_KIND,
    TFP_CONTENT_ANNOUNCE_KIND,
)


class TestFastCDCAndMerkleAdversarialChallenger:
    """Adversarial challenge for FastCDC chunking and Merkle tree proofs."""

    def test_fastcdc_boundary_0_bytes(self):
        """Boundary test: 0 bytes input."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        chunks = chunker.chunk(b"")
        assert chunks == []

        recipe, chunks = chunker.create_recipe(b"")
        assert recipe.total_size == 0
        assert recipe.chunk_hashes == []
        assert recipe.chunk_sizes == []

        assembled = chunker.assemble(recipe, {})
        assert assembled == b""

    def test_fastcdc_boundary_1_byte(self):
        """Boundary test: 1 byte input."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        data = b"\x42"
        chunks = chunker.chunk(data)
        assert chunks == [b"\x42"]

        recipe, chunks = chunker.create_recipe(data)
        chunk_map = {recipe.chunk_hashes[0]: chunks[0]}
        assembled = chunker.assemble(recipe, chunk_map)
        assert assembled == data

    @pytest.mark.parametrize("size", [128, 256, 512, 1024])
    def test_fastcdc_exact_chunk_boundaries(self, size: int):
        """Boundary test: exact chunk size boundaries (min, target, max, 2*max)."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        data = bytes([(i % 251) for i in range(size)])
        chunks = chunker.chunk(data)
        assert b"".join(chunks) == data
        for c in chunks[:-1]:
            assert 128 <= len(c) <= 512
        assert 0 < len(chunks[-1]) <= 512

        recipe, created_chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, created_chunks)}
        assembled = chunker.assemble(recipe, chunk_map)
        assert assembled == data

    def test_fastcdc_boundary_100kb(self):
        """Boundary test: 100KB input (102,400 bytes)."""
        chunker = ContentDefinedChunker(min_size=256, max_size=2048, target_size=1024)
        data = bytes([(i * 37 + 13) % 256 for i in range(102_400)])
        chunks = chunker.chunk(data)
        assert b"".join(chunks) == data
        assert len(chunks) > 30

        recipe, created_chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, created_chunks)}
        assembled = chunker.assemble(recipe, chunk_map)
        assert assembled == data

    def test_fastcdc_corrupted_chunk_hashes_strictly_rejected(self):
        """Verify tampered chunk hashes in recipe or missing map keys raise KeyError/ValueError."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        data = os.urandom(2048)
        recipe, chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, chunks)}

        # Missing key
        missing_map = dict(chunk_map)
        del missing_map[recipe.chunk_hashes[0]]
        with pytest.raises(KeyError, match="Missing required chunk"):
            chunker.assemble(recipe, missing_map)

        # Forged hash in recipe (mismatched root hash triggers recipe validation failure)
        forged_hashes = list(recipe.chunk_hashes)
        forged_hashes[0] = hashlib.sha3_256(b"forged").hexdigest()
        forged_recipe_bad_root = ChunkRecipe(
            root_hash=recipe.root_hash,
            total_size=recipe.total_size,
            chunk_hashes=forged_hashes,
            chunk_sizes=recipe.chunk_sizes,
            metadata={},
        )
        with pytest.raises(ValueError, match="Invalid recipe"):
            chunker.assemble(forged_recipe_bad_root, chunk_map)

        # Forged hash with aligned root hash triggers missing chunk in chunk_map
        hasher = hashlib.sha3_256()
        for chash in forged_hashes:
            hasher.update(chash.encode("utf-8"))
        forged_recipe_valid_root = ChunkRecipe(
            root_hash=hasher.hexdigest(),
            total_size=recipe.total_size,
            chunk_hashes=forged_hashes,
            chunk_sizes=recipe.chunk_sizes,
            metadata={},
        )
        with pytest.raises(KeyError, match="Missing required chunk"):
            chunker.assemble(forged_recipe_valid_root, chunk_map)

    def test_fastcdc_truncated_payload_strictly_rejected(self):
        """Verify truncated chunk payloads raise ValueError (size mismatch)."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        data = os.urandom(2048)
        recipe, chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, chunks)}

        # Truncate first chunk
        first_h = recipe.chunk_hashes[0]
        chunk_map[first_h] = chunk_map[first_h][:-1]
        with pytest.raises(ValueError, match="size mismatch"):
            chunker.assemble(recipe, chunk_map)

    def test_fastcdc_bitflip_payload_strictly_rejected(self):
        """Verify bit-flipped chunk payloads raise ValueError (hash mismatch)."""
        chunker = ContentDefinedChunker(min_size=128, max_size=512, target_size=256)
        data = os.urandom(2048)
        recipe, chunks = chunker.create_recipe(data)
        chunk_map = {h: c for h, c in zip(recipe.chunk_hashes, chunks)}

        # Flip a bit in first chunk
        first_h = recipe.chunk_hashes[0]
        corrupted = bytes([chunk_map[first_h][0] ^ 0x01]) + chunk_map[first_h][1:]
        chunk_map[first_h] = corrupted
        with pytest.raises(ValueError, match="hash mismatch"):
            chunker.assemble(recipe, chunk_map)

    def test_merkle_boundary_empty_leaves_rejected(self):
        """Empty leaf list strictly raises ValueError."""
        with pytest.raises(ValueError, match="Cannot build Merkle tree from empty leaf list"):
            MerkleTree([])

    def test_merkle_boundary_single_leaf(self):
        """Single leaf tree produces valid empty proof verifying against root."""
        leaf = b"single_leaf_payload"
        tree = MerkleTree([leaf])
        assert tree.root == sha3_256(leaf)
        proof = tree.get_proof(0)
        assert proof == []
        assert verify_merkle_proof(leaf, proof, tree.root) is True
        assert verify_merkle_proof(b"forged_leaf", proof, tree.root) is False

    @pytest.mark.parametrize("count", [1, 3, 5, 7, 9, 15, 33, 64])
    def test_merkle_odd_and_even_leaf_counts_proof_integrity(self, count: int):
        """Non-power-of-two and power-of-two leaf counts verify 100%."""
        leaves = [f"leaf_{i}_{os.urandom(4).hex()}".encode() for i in range(count)]
        tree = MerkleTree(leaves)
        for i, leaf in enumerate(leaves):
            proof = tree.get_proof(i)
            assert verify_merkle_proof(leaf, proof, tree.root) is True
            assert verify_merkle_proof(leaf + b"x", proof, tree.root) is False

    def test_merkle_forged_root_strictly_rejected(self):
        """Audit proof verification against arbitrary forged roots evaluates to False."""
        leaves = [f"leaf_{i}".encode() for i in range(8)]
        tree = MerkleTree(leaves)
        forged_roots = [
            b"\x00" * 32,
            b"\xFF" * 32,
            os.urandom(32),
            bytes([tree.root[0] ^ 0x01]) + tree.root[1:],
        ]
        for forged_root in forged_roots:
            for i, leaf in enumerate(leaves):
                proof = tree.get_proof(i)
                assert verify_merkle_proof(leaf, proof, forged_root) is False

    def test_merkle_proof_tampered_siblings_rejected(self):
        """Mutating sibling hashes or directions in audit proof evaluates to False."""
        leaves = [f"leaf_{i}".encode() for i in range(8)]
        tree = MerkleTree(leaves)
        for i, leaf in enumerate(leaves):
            proof = tree.get_proof(i)
            if not proof:
                continue
            bad_sibling = bytes([proof[0][0][0] ^ 0xFF]) + proof[0][0][1:]
            bad_proof = [(bad_sibling, proof[0][1])] + proof[1:]
            assert verify_merkle_proof(leaf, bad_proof, tree.root) is False

            inv_dir = "right" if proof[0][1] == "left" else "left"
            bad_dir_proof = [(proof[0][0], inv_dir)] + proof[1:]
            assert verify_merkle_proof(leaf, bad_dir_proof, tree.root) is False


class TestNostrGossipAdversarialChallenger:
    """Adversarial challenge for Nostr gossip protocol."""

    def test_schnorr_invalid_signatures_strictly_rejected(self):
        """Invalid, bit-flipped, or forged signatures strictly evaluate to False."""
        sk_seed = os.urandom(32)
        sk_int = (int.from_bytes(sk_seed, "big") % (_N - 1)) + 1
        sk_bytes = sk_int.to_bytes(32, "big")
        pk_hex = _derive_pubkey_bytes(sk_bytes).hex()

        msg = hashlib.sha256(b"GOSSIP_DATA").digest()
        event_id = msg.hex()
        sig_bytes = _schnorr_sign(sk_bytes, msg)
        sig_hex = sig_bytes.hex()

        assert _schnorr_verify(pk_hex, event_id, sig_hex) is True

        bad_sig = bytes([sig_bytes[0] ^ 0x01]) + sig_bytes[1:]
        assert _schnorr_verify(pk_hex, event_id, bad_sig.hex()) is False

        assert _schnorr_verify(pk_hex, event_id, os.urandom(64).hex()) is False

        wrong_id = hashlib.sha256(b"DIFFERENT").hexdigest()
        assert _schnorr_verify(pk_hex, wrong_id, sig_hex) is False

        other_sk = ((sk_int + 1) % (_N - 1) + 1).to_bytes(32, "big")
        other_pk = _derive_pubkey_bytes(other_sk).hex()
        assert _schnorr_verify(other_pk, event_id, sig_hex) is False

    def test_nostr_event_id_tamper_rejected(self):
        """Modifying content, created_at, or kind causes recomputed ID mismatch in _verify_nostr_event."""
        sk_int = 12345678901234567890
        sk_bytes = sk_int.to_bytes(32, "big")
        pk_hex = _derive_pubkey_bytes(sk_bytes).hex()

        event = {
            "pubkey": pk_hex,
            "created_at": int(time.time()),
            "kind": 30080,
            "tags": [["t", "test"]],
            "content": json.dumps({"hash": "a" * 64, "title": "test"}),
        }
        serialized = json.dumps(
            [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        event["id"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        event["sig"] = _schnorr_sign(sk_bytes, bytes.fromhex(event["id"])).hex()

        assert _verify_nostr_event(event) is True

        tampered_event = dict(event)
        tampered_event["content"] = json.dumps({"hash": "b" * 64})
        assert _verify_nostr_event(tampered_event) is False

        tampered_created = dict(event)
        tampered_created["created_at"] = event["created_at"] + 10
        assert _verify_nostr_event(tampered_created) is False

    @pytest.mark.parametrize("delta,expected", [
        (-301, False),
        (-300, True),
        (-150, True),
        (0, True),
        (150, True),
        (300, True),
        (301, False),
        (-100000, False),
        (100000, False),
    ])
    def test_replay_window_boundary_and_exceeded(self, delta: int, expected: bool):
        """Replay window enforces |created_at - t_now| <= 300 seconds strictly."""
        t_now = int(time.time())
        event = {"created_at": t_now + delta, "id": "test_evt", "kind": 30080}
        assert _check_replay_window(event) is expected

    @pytest.mark.parametrize("bad_created_at", [
        None,
        "invalid_timestamp",
        [12345],
        {"time": 12345},
        "NaN",
        "Infinity",
    ])
    def test_replay_window_malformed_types(self, bad_created_at):
        """Malformed created_at types return False without raising exceptions."""
        event = {"created_at": bad_created_at, "id": "test_evt", "kind": 30080}
        assert _check_replay_window(event) is False

    def test_nostr_malformed_kind_30078_30080_zero_500_exceptions(self):
        """Ingesting malformed payloads into _on_nostr_event yields zero unhandled exceptions."""
        malformed_contents = [
            "not a valid json string",
            "{",
            "{\"unterminated\": ",
            "[1, 2, 3]",
            "123456",
            "null",
            "true",
            "",
            "{\"domains\": \"not_a_list\"}",
            "{\"hash\": 12345}",
            "{" + "\"a\": 1, " * 1000 + "\"b\": 2}",
        ]

        for kind in [TFP_CONTENT_KIND, TFP_CONTENT_ANNOUNCE_KIND, 30079, 30081]:
            for content in malformed_contents:
                event = {
                    "id": hashlib.sha256(os.urandom(16)).hexdigest(),
                    "pubkey": "0" * 64,
                    "created_at": int(time.time()),
                    "kind": kind,
                    "tags": [],
                    "content": content,
                    "sig": "0" * 128,
                }
                try:
                    _on_nostr_event(event)
                except Exception as exc:
                    pytest.fail(f"Unhandled exception in _on_nostr_event: {exc}")

    def test_gossip_broadcast_fastapi_zero_500_on_fuzz(self):
        """FastAPI /api/gossip/broadcast returns 4xx and never 500 on malformed bodies."""
        temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_db.close()
        old_db = os.environ.get("TFP_DB_PATH")
        os.environ["TFP_DB_PATH"] = temp_db.name
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                test_payloads = [
                    {},
                    {"data": None},
                    {"items": [1, 2, "string"]},
                    {"deep": {"nested": {"key": True}}},
                    {"corrupt": "\x00\xFF"},
                ]
                for payload in test_payloads:
                    res = client.post(
                        "/api/gossip/broadcast",
                        params={"message_type": "peer_announcement", "ttl": 5},
                        json=payload,
                    )
                    assert res.status_code in [200, 400, 401, 422], f"Unexpected status {res.status_code}: {res.text}"
                    assert res.status_code != 500

                res = client.post(
                    "/api/gossip/broadcast",
                    params={"message_type": "peer_announcement", "ttl": 5},
                    content="INVALID_RAW_NON_JSON",
                    headers={"Content-Type": "application/json"},
                )
                assert res.status_code == 422
                assert res.status_code != 500
        finally:
            if old_db is not None:
                os.environ["TFP_DB_PATH"] = old_db
            else:
                os.environ.pop("TFP_DB_PATH", None)
            try:
                if os.path.exists(temp_db.name):
                    os.remove(temp_db.name)
            except Exception:
                pass


class TestFountainCodecAdversarialChallenger:
    """Adversarial challenge for rateless fountain codec and anti-pollution."""

    def test_droplet_seed_authenticity_o1_timing(self):
        """Verify verify_droplet_seed_authenticity executes in O(1) time (< 100 microseconds)."""
        k = 32
        seeds = derive_repair_seed_schedule(root_hash="test_root_hash", total_source_blocks=k, repair_count=500)
        
        times = []
        for seed in seeds:
            t0 = time.perf_counter()
            rng = random.Random(seed)
            deg = _sample_soliton_degree(k, rng)
            idx = sorted(rng.sample(range(k), deg))
            is_valid = verify_droplet_seed_authenticity(
                droplet_seed=seed,
                total_source_blocks=k,
                degree=deg,
                indices=idx,
            )
            t1 = time.perf_counter()
            times.append(t1 - t0)
            assert is_valid is True

        mean_time_us = (sum(times) / len(times)) * 1_000_000
        assert mean_time_us < 100, f"Pre-filter too slow: {mean_time_us:.2f} us (not O(1))"

    def test_byzantine_tampered_repair_seeds_rejected(self):
        """Verify tampered degrees, corrupted indices, or negative seeds are strictly rejected."""
        k = 16
        seeds = derive_repair_seed_schedule(root_hash="test_root_hash", total_source_blocks=k, repair_count=20)

        for seed in seeds:
            rng = random.Random(seed)
            expected_degree = _sample_soliton_degree(k, rng)
            expected_indices = sorted(rng.sample(range(k), expected_degree))

            assert verify_droplet_seed_authenticity(-1, total_source_blocks=k) is False

            bad_degree = (expected_degree % k) + 1
            if bad_degree != expected_degree:
                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    total_source_blocks=k,
                    degree=bad_degree,
                    indices=expected_indices,
                ) is False

            bad_indices = list(expected_indices)
            bad_indices[0] = (bad_indices[0] + 1) % k
            bad_indices = sorted(list(set(bad_indices)))
            if bad_indices != expected_indices:
                assert verify_droplet_seed_authenticity(
                    droplet_seed=seed,
                    total_source_blocks=k,
                    degree=expected_degree,
                    indices=bad_indices,
                ) is False

        assert verify_droplet_seed_authenticity(0, total_source_blocks=k, degree=2, indices=[0, 1]) is False
        assert verify_droplet_seed_authenticity(0, total_source_blocks=k, degree=1, indices=[1]) is False
        assert verify_droplet_seed_authenticity(0, total_source_blocks=k, degree=1, indices=[0]) is True

    @pytest.mark.parametrize("symbol_size", [32, 64, 128, 256])
    def test_packet_drops_40_percent_bit_exact_recovery(self, symbol_size: int):
        """Test rateless fountain reconstruction under 40% packet erasure channel."""
        data = bytes([(i * 17 + 7) % 256 for i in range(2048)])
        root_hash = hashlib.sha3_256(data).hexdigest()

        codec = FountainCodec(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = codec.encode(data, redundancy=3.0)

        # 40% random drop rate
        rng = random.Random(42 + symbol_size)
        surviving = [d for d in droplets if rng.random() > 0.40]

        # Rateless accumulation until full rank
        received = []
        recovered = None
        for d in surviving:
            received.append(d)
            if len(received) >= k:
                try:
                    recovered = codec.decode(received, k=k, orig_len=orig_len)
                    break
                except ValueError:
                    continue

        assert recovered is not None, f"Failed to achieve rank K under 40% loss (symbol_size={symbol_size})"
        assert recovered == data, f"Decoded payload bit mismatch for symbol_size={symbol_size}"

    @pytest.mark.parametrize("symbol_size", [32, 64, 128, 256])
    def test_packet_drops_50_percent_bit_exact_recovery(self, symbol_size: int):
        """Test rateless fountain reconstruction under 50% packet erasure channel."""
        data = bytes([(i * 31 + 19) % 256 for i in range(2048)])
        root_hash = hashlib.sha3_256(data).hexdigest()

        codec = FountainCodec(symbol_size=symbol_size, root_hash=root_hash)
        droplets, k, orig_len = codec.encode(data, redundancy=3.5)

        # 50% random drop rate
        rng = random.Random(1337 + symbol_size)
        surviving = [d for d in droplets if rng.random() > 0.50]

        received = []
        recovered = None
        for d in surviving:
            received.append(d)
            if len(received) >= k:
                try:
                    recovered = codec.decode(received, k=k, orig_len=orig_len)
                    break
                except ValueError:
                    continue

        assert recovered is not None, f"Failed to achieve rank K under 50% loss (symbol_size={symbol_size})"
        assert recovered == data, f"Decoded payload bit mismatch under 50% loss for symbol_size={symbol_size}"

    def test_tfp_node_packet_drop_resilience_40_and_50(self):
        """Verify TFPNode.fetch successfully reconstructs content under 40% and 50% loss."""
        data = b"TFP_NODE_LOSS_RESILIENCE_TEST_PAYLOAD_" * 40
        node = TFPNode(node_id="test_challenger_node")
        recipe = node.publish(data)

        recovered_40 = node.fetch(recipe.root_hash, simulated_loss=0.40)
        assert recovered_40 == data

        recovered_50 = node.fetch(recipe.root_hash, simulated_loss=0.50)
        assert recovered_50 == data

    def test_insufficient_rank_strictly_raises_value_error(self):
        """When droplet count or rank is strictly < K, decode raises ValueError and never returns corrupt data."""
        data = os.urandom(1024)
        root_hash = hashlib.sha3_256(data).hexdigest()
        encoder = FountainEncoder(symbol_size=64, root_hash=root_hash)
        droplets, k, orig_len = encoder.encode(data, redundancy=0.5)

        decoder = FountainDecoder(symbol_size=64, root_hash=root_hash)
        # Droplets < K
        with pytest.raises(ValueError, match="Need at least"):
            decoder.decode(droplets[:k - 1], k, orig_len)