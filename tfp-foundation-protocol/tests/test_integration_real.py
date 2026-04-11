"""
Integration test: end-to-end request_content using real adapters.
All adapters fall back gracefully — no NFD or network required.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tfp_broadcaster.broadcaster import Broadcaster
from tfp_broadcaster.src.multicast.multicast_real import RealMulticastAdapter
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import CreditLedger
from tfp_client.lib.fountain.fountain_real import IntegrityError, RealRaptorQAdapter
from tfp_client.lib.lexicon.adapter import LexiconAdapter
from tfp_client.lib.ndn.ndn_real import RealNDNAdapter
from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

# ── Fountain code round-trip ──────────────────────────────────────────────────


class TestRealFountainRoundTrip:
    def setup_method(self):
        self.fq = RealRaptorQAdapter()

    def test_encode_decode_small(self):
        data = b"Hello TFP v2.2 world!"
        shards = self.fq.encode(data, redundancy=0.1)
        assert len(shards) > 1
        recovered = self.fq.decode(shards)
        assert recovered == data

    def test_encode_decode_large(self):
        data = os.urandom(4096)
        shards = self.fq.encode(data, redundancy=0.2)
        recovered = self.fq.decode(shards)
        assert recovered == data

    def test_encode_all_source_shards_available(self):
        data = b"A" * 512
        shards = self.fq.encode(data, redundancy=0.1)
        # Use only source shards (indices 0..k-1)
        import struct

        k = struct.unpack(">QII", shards[0][:16])[1]
        source_only = [s for s in shards if struct.unpack(">QII", s[:16])[2] < k]
        recovered = self.fq.decode(source_only)
        assert recovered == data

    def test_encode_raises_on_empty(self):
        with pytest.raises(ValueError):
            self.fq.encode(b"")

    def test_shard_count_includes_redundancy(self):
        data = b"X" * 256
        shards = self.fq.encode(data, redundancy=0.5)
        import struct

        k = struct.unpack(">QII", shards[0][:16])[1]
        assert len(shards) > k  # repair shards exist


# ── ZKP Schnorr proof ─────────────────────────────────────────────────────────


class TestRealZKPAdapter:
    def setup_method(self):
        self.zkp = RealZKPAdapter()

    def test_proof_is_64_bytes(self):
        proof = self.zkp.generate_proof("access_to_hash", b"secret_claim")
        assert len(proof) == 64

    def test_proof_verifies(self):
        proof = self.zkp.generate_proof("access_to_hash", b"secret_claim")
        assert self.zkp.verify_proof(proof, b"public") is True

    def test_two_proofs_differ(self):
        proof1 = self.zkp.generate_proof("access_to_hash", b"secret")
        proof2 = self.zkp.generate_proof("access_to_hash", b"secret")
        # Different nonces → different proofs (non-deterministic)
        assert proof1 != proof2

    def test_tampered_proof_fails(self):
        proof = self.zkp.generate_proof("access_to_hash", b"secret")
        bad = b"\x00" * 64
        assert self.zkp.verify_proof(bad, b"public") is False

    def test_wrong_length_fails(self):
        assert self.zkp.verify_proof(b"short", b"public") is False


# ── NDN adapter (fallback mode — no NFD) ─────────────────────────────────────


class TestRealNDNAdapterFallback:
    def setup_method(self):
        self.ndn = RealNDNAdapter(fallback_content=b"test_content_bytes")

    def test_create_interest(self):
        interest = self.ndn.create_interest("abc123")
        assert interest.name == "/tfp/content/abc123"

    def test_express_interest_returns_data(self):
        interest = self.ndn.create_interest("abc123")
        data = self.ndn.express_interest(interest)
        assert isinstance(data.content, bytes)
        assert len(data.content) > 0

    def test_fallback_content_used(self):
        interest = self.ndn.create_interest("deadbeef")
        data = self.ndn.express_interest(interest)
        # In fallback mode, the fallback_content or fallback pattern is returned
        assert data.content is not None


# ── Multicast adapter (fallback mode — no network required) ──────────────────


class TestRealMulticastAdapterFallback:
    def setup_method(self):
        self.mc = RealMulticastAdapter()

    def teardown_method(self):
        self.mc.close()

    def test_transmit_increments_count(self):
        shards = [b"shard_a", b"shard_b"]
        self.mc.transmit(shards)
        assert self.mc.transmission_count == 1

    def test_transmit_multiple(self):
        for i in range(3):
            self.mc.transmit([f"shard_{i}".encode()])
        assert self.mc.transmission_count == 3


# ── Full end-to-end request_content with real adapters ───────────────────────


class TestEndToEndRealAdapters:
    def setup_method(self):
        # Use real adapters with pre-loaded fallback content
        fallback_data = b"Hello from real NDN fallback" * 10  # 280 bytes

        # Pre-encode with real fountain adapter so NDN returns decodable shards
        fq = RealRaptorQAdapter()
        shards = fq.encode(fallback_data, redundancy=0.1)
        fallback_shard = shards[0]  # first shard as fallback content

        self.ndn = RealNDNAdapter(fallback_content=fallback_shard)
        self.fq = fq
        self.zkp = RealZKPAdapter()
        self.lexicon = LexiconAdapter()
        self.ledger = CreditLedger()
        self.client = TFPClient(
            ndn=self.ndn,
            raptorq=self.fq,
            zkp=self.zkp,
            lexicon=self.lexicon,
            ledger=self.ledger,
        )

    def test_request_content_returns_content(self):
        self.client.submit_compute_task("task_for_content_request")
        content = self.client.request_content("abc123deadbeef")
        assert content is not None
        assert isinstance(content.data, bytes)
        assert len(content.data) > 0

    def test_request_content_deducts_credits(self):
        # First earn credits via a compute task, then spend one on a request
        before_earn = self.ledger.balance
        self.client.submit_compute_task("recipe_for_spend_test")
        after_earn = self.ledger.balance
        assert after_earn == before_earn + 10

        before_spend = self.ledger.balance
        self.client.request_content("hash_xyz")
        assert self.ledger.balance == before_spend - 1  # spent 1 credit

    def test_prove_access_returns_64_bytes(self):
        proof = self.client.prove_access("hash_abc", b"my_private_key")
        assert len(proof) == 64

    def test_submit_task_mints_credits(self):
        before = self.ledger.balance
        receipt = self.client.submit_compute_task("recipe_hash_001")
        assert self.ledger.balance == before + 10
        assert self.ledger.verify_spend(receipt) is True

    def test_full_pipeline_hash_integrity(self):
        # Earn 2 credits (need to spend one per request)
        self.client.submit_compute_task("task_for_hash_integrity_1")
        self.client.submit_compute_task("task_for_hash_integrity_2")
        # Test that reconstructed content hash is deterministic
        content1 = self.client.request_content("same_hash")
        content2 = self.client.request_content("same_hash")
        assert content1.root_hash == content2.root_hash

    def test_broadcaster_with_real_fountain(self):
        mc = RealMulticastAdapter()
        broadcaster = Broadcaster(raptorq=self.fq, multicast=mc)
        result = broadcaster.seed_content(b"Some important data " * 20)
        assert "root_hash" in result
        assert len(result["root_hash"]) == 64
        assert result["shard_count"] > 1
        mc.close()


# ── Per-shard HMAC tests ──────────────────────────────────────────────────────


class TestPerShardHMAC:
    def setup_method(self):
        self.fq = RealRaptorQAdapter()
        self.key = os.urandom(32)

    def test_encode_decode_with_hmac_key(self):
        data = b"HMAC-protected content for TFP v2.3"
        shards = self.fq.encode(data, hmac_key=self.key)
        recovered = self.fq.decode(shards, hmac_key=self.key)
        assert recovered == data

    def test_encode_decode_large_with_hmac(self):
        data = os.urandom(2048)
        shards = self.fq.encode(data, redundancy=0.1, hmac_key=self.key)
        recovered = self.fq.decode(shards, hmac_key=self.key)
        assert recovered == data

    def test_hmac_shards_longer_than_plain(self):
        data = b"X" * 256
        plain = self.fq.encode(data)
        protected = self.fq.encode(data, hmac_key=self.key)
        # Each protected shard is 32 bytes longer (HMAC appended)
        assert len(protected[0]) == len(plain[0]) + 32

    def test_tampered_shard_raises_integrity_error(self):
        data = b"important payload"
        shards = self.fq.encode(data, hmac_key=self.key)
        # Flip a byte in the payload area of the first shard (after the 16-byte header)
        import struct

        header_size = struct.calcsize(">QII")  # 16 bytes: orig_len(8) + k(4) + idx(4)
        bad = bytearray(shards[0])
        bad[header_size] ^= 0xFF  # corrupt first payload byte
        shards[0] = bytes(bad)
        with pytest.raises(IntegrityError):
            self.fq.decode(shards, hmac_key=self.key)

    def test_wrong_key_raises_integrity_error(self):
        data = b"secret payload"
        shards = self.fq.encode(data, hmac_key=self.key)
        wrong_key = os.urandom(32)
        with pytest.raises(IntegrityError):
            self.fq.decode(shards, hmac_key=wrong_key)

    def test_no_key_roundtrip_unchanged(self):
        """Without hmac_key, behaviour is identical to previous version."""
        data = b"plain data no hmac"
        shards = self.fq.encode(data)
        recovered = self.fq.decode(shards)
        assert recovered == data
