"""Tests for real ZKP using SECP256K1 elliptic curves."""
import hashlib
import pytest
from tfp_client.lib.zkp.zkp_real import RealZKPAdapter


class TestRealZKP:
    """Test real elliptic curve ZKP."""

    def test_proof_generation(self):
        """Can generate proof with real crypto."""
        adapter = RealZKPAdapter()
        proof = adapter.generate_proof("access_to_hash", b"private_claim")
        assert len(proof) == 65  # 33 bytes compressed point + 32 bytes scalar

    def test_proof_verification(self):
        """Can verify valid proof."""
        adapter = RealZKPAdapter()
        private = b"test_private"
        public = hashlib.sha3_256(b"test_public").digest()

        proof = adapter.generate_proof("test_circuit", private)
        assert adapter.verify_proof(proof, public) is True

    def test_invalid_proof_fails(self):
        """Invalid proof is rejected."""
        adapter = RealZKPAdapter()
        # Corrupted proof (all zeros)
        invalid_proof = b"\x00" * 65
        assert adapter.verify_proof(invalid_proof, b"test") is False

    def test_proof_with_different_public_fails(self):
        """Proof for wrong public input fails."""
        adapter = RealZKPAdapter()
        private = b"private_data"

        proof = adapter.generate_proof("circuit", private)
        # Try to verify with different public input
        wrong_public = hashlib.sha3_256(b"different").digest()
        assert adapter.verify_proof(proof, wrong_public) is False

    def test_different_key_fails(self):
        """Proof from different key fails."""
        adapter1 = RealZKPAdapter()
        adapter2 = RealZKPAdapter()  # Different key

        private = b"secret"
        public = hashlib.sha3_256(b"public").digest()

        proof = adapter1.generate_proof("circuit", private)
        # Verification with different key should fail
        assert adapter2.verify_proof(proof, public) is False

    def test_public_key_bytes(self):
        """Can get compressed public key."""
        adapter = RealZKPAdapter()
        pub_key = adapter.get_public_key_bytes()
        assert len(pub_key) == 33  # Compressed SECP256K1 public key

    def test_custom_private_key(self):
        """Can initialize with custom private key."""
        private_key = b"\x01" * 32
        adapter = RealZKPAdapter(private_key=private_key)
        proof = adapter.generate_proof("test", b"witness")
        assert len(proof) == 65
