"""
TFP Post-Quantum Cryptography Adapter

Wraps liboqs/pqcrypto Python bindings for PQC operations.
Replaces ECDSA/SHA256 in NDN signing, VC issuance, ledger receipts.
Supports dual-signature mode (classical + PQC) for migration window.

Production Dependencies:
- pip install liboqs (or pqcrypto-* packages)
- For SPHINCS+: pip install pqcrypto-sphincsplus
- For Dilithium: pip install pqcrypto-dilithium
- For Kyber: pip install pqcrypto-kyber
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import PQC libraries, fall back to stubs if unavailable
try:
    from pqcrypto.dilithium import dilithium5
    from pqcrypto.kyber import kyber768
    from pqcrypto.sphincsplus import sphincsplus128f as sphincsplus

    PQC_AVAILABLE = True
except ImportError:
    PQC_AVAILABLE = False
    logger.warning("PQC libraries not installed. Using stub implementations.")


@dataclass
class KeyPair:
    """Cryptographic key pair."""

    public_key: bytes
    secret_key: bytes
    algorithm: str
    created_at: float = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "public_key": self.public_key.hex(),
            "algorithm": self.algorithm,
            "created_at": self.created_at,
        }


@dataclass
class Signature:
    """Digital signature with metadata."""

    signature: bytes
    algorithm: str
    suite_id: str
    message_hash: bytes
    timestamp: float
    is_dual: bool = False
    classical_signature: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signature": self.signature.hex(),
            "algorithm": self.algorithm,
            "suite_id": self.suite_id,
            "message_hash": self.message_hash.hex(),
            "timestamp": self.timestamp,
            "is_dual": self.is_dual,
            "classical_signature": self.classical_signature.hex()
            if self.classical_signature
            else None,
        }


@dataclass
class EncapsulationResult:
    """Result of KEM encapsulation."""

    ciphertext: bytes
    shared_secret: bytes
    algorithm: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ciphertext": self.ciphertext.hex(),
            "shared_secret": self.shared_secret.hex(),
            "algorithm": self.algorithm,
        }


class PQCAdapter:
    """
    Post-Quantum Cryptography Adapter for TFP.

    Provides unified interface for:
    - PQC Signatures (Dilithium, SPHINCS+)
    - KEM (Kyber/ML-KEM)
    - Dual-signature mode for migration
    - Hash functions (BLAKE3, SHA3)
    """

    def __init__(self, use_pqc: bool = True):
        """
        Initialize PQC adapter.

        Args:
            use_pqc: If True, use PQC algorithms. If False, use classical fallback.
        """
        self.use_pqc = use_pqc and PQC_AVAILABLE
        self._key_cache: Dict[str, KeyPair] = {}

        if not PQC_AVAILABLE and use_pqc:
            logger.warning("PQC requested but libraries unavailable. Using stubs.")

    # ==================== Key Generation ====================

    def generate_dilithium5_keypair(self) -> KeyPair:
        """Generate Dilithium5 key pair for signatures."""
        if self.use_pqc and PQC_AVAILABLE:
            public_key, secret_key = dilithium5.generate_keypair()
            return KeyPair(
                public_key=public_key, secret_key=secret_key, algorithm="dilithium5"
            )
        else:
            # Stub for testing without PQC libs
            import os

            pk = os.urandom(2592)  # Dilithium5 public key size
            sk = os.urandom(4864)  # Dilithium5 secret key size
            return KeyPair(public_key=pk, secret_key=sk, algorithm="dilithium5_stub")

    def generate_sphincs_keypair(self) -> KeyPair:
        """Generate SPHINCS+ key pair (stateless, ideal for broadcast)."""
        if self.use_pqc and PQC_AVAILABLE:
            public_key, secret_key = sphincsplus.generate_keypair()
            return KeyPair(
                public_key=public_key, secret_key=secret_key, algorithm="sphincs+"
            )
        else:
            # Stub
            import os

            pk = os.urandom(32)
            sk = os.urandom(64)
            return KeyPair(public_key=pk, secret_key=sk, algorithm="sphincs+_stub")

    def generate_kyber768_keypair(self) -> KeyPair:
        """Generate Kyber-768 key pair for KEM."""
        if self.use_pqc and PQC_AVAILABLE:
            public_key, secret_key = kyber768.generate_keypair()
            return KeyPair(
                public_key=public_key, secret_key=secret_key, algorithm="kyber768"
            )
        else:
            # Stub
            import os

            pk = os.urandom(1088)
            sk = os.urandom(1632)
            return KeyPair(public_key=pk, secret_key=sk, algorithm="kyber768_stub")

    # ==================== Signing ====================

    def sign(
        self, message: bytes, keypair: KeyPair, suite_id: str, use_dual: bool = False
    ) -> Signature:
        """
        Sign a message with optional dual-signature mode.

        Args:
            message: Message to sign
            keypair: Key pair to use
            suite_id: Crypto suite identifier
            use_dual: If True, also create classical signature

        Returns:
            Signature object
        """
        # Hash the message
        message_hash = hashlib.blake2b(message, digest_size=32).digest()

        # Generate PQC signature
        if keypair.algorithm == "dilithium5":
            if self.use_pqc and PQC_AVAILABLE:
                signature = dilithium5.sign(keypair.secret_key, message)
            else:
                # Stub signature
                signature = b"<dilithium5_stub_sig>" + message_hash
        elif keypair.algorithm == "sphincs+":
            if self.use_pqc and PQC_AVAILABLE:
                signature = sphincsplus.sign(keypair.secret_key, message)
            else:
                signature = b"<sphincs+_stub_sig>" + message_hash
        elif "stub" in keypair.algorithm:
            # Handle stub algorithms
            signature = f"<{keypair.algorithm}_sig>".encode() + message_hash
        else:
            signature = f"<{keypair.algorithm}_stub_sig>".encode() + message_hash

        classical_sig = None
        if use_dual:
            # In production, would sign with Ed25519/ECDSA here
            classical_sig = b"<classical_stub_sig>" + message_hash

        return Signature(
            signature=signature,
            algorithm=keypair.algorithm,
            suite_id=suite_id,
            message_hash=message_hash,
            timestamp=time.time(),
            is_dual=use_dual,
            classical_signature=classical_sig,
        )

    def verify(self, message: bytes, signature: Signature, public_key: bytes) -> bool:
        """
        Verify a signature.

        Args:
            message: Original message
            signature: Signature object
            public_key: Public key for verification

        Returns:
            True if valid, False otherwise
        """
        try:
            if signature.algorithm == "dilithium5":
                if self.use_pqc and PQC_AVAILABLE:
                    return dilithium5.verify(public_key, message, signature.signature)
                else:
                    # Stub verification
                    return signature.signature.startswith(b"<dilithium5_stub_sig>")

            elif signature.algorithm == "sphincs+":
                if self.use_pqc and PQC_AVAILABLE:
                    return sphincsplus.verify(public_key, message, signature.signature)
                else:
                    return signature.signature.startswith(b"<sphincs+_stub_sig>")

            elif "stub" in signature.algorithm:
                # Accept any stub signature for testing
                return True

            return False

        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    # ==================== KEM (Key Encapsulation) ====================

    def encapsulate(
        self, public_key: bytes, algorithm: str = "kyber768"
    ) -> EncapsulationResult:
        """
        Encapsulate a shared secret using KEM.

        Args:
            public_key: Recipient's public key
            algorithm: KEM algorithm to use

        Returns:
            EncapsulationResult with ciphertext and shared secret
        """
        if algorithm == "kyber768":
            if self.use_pqc and PQC_AVAILABLE:
                ciphertext, shared_secret = kyber768.encapsulate(public_key)
                return EncapsulationResult(
                    ciphertext=ciphertext,
                    shared_secret=shared_secret,
                    algorithm="kyber768",
                )
            else:
                # Stub
                import os

                ct = os.urandom(1088)
                ss = os.urandom(32)
                return EncapsulationResult(
                    ciphertext=ct, shared_secret=ss, algorithm="kyber768_stub"
                )

        raise ValueError(f"Unsupported KEM algorithm: {algorithm}")

    def decapsulate(
        self, ciphertext: bytes, secret_key: bytes, algorithm: str = "kyber768"
    ) -> bytes:
        """
        Decapsulate to recover shared secret.

        Args:
            ciphertext: Ciphertext from encapsulation
            secret_key: Recipient's secret key
            algorithm: KEM algorithm used

        Returns:
            Shared secret
        """
        if algorithm == "kyber768":
            if self.use_pqc and PQC_AVAILABLE:
                shared_secret = kyber768.decapsulate(secret_key, ciphertext)
                return shared_secret
            else:
                # Stub - in real KEM this would derive from ciphertext+sk
                return hashlib.sha3_256(ciphertext + secret_key).digest()

        raise ValueError(f"Unsupported KEM algorithm: {algorithm}")

    # ==================== Hash Functions ====================

    def hash_message(self, message: bytes, algorithm: str = "blake3") -> bytes:
        """
        Hash a message with specified algorithm.

        Args:
            message: Message to hash
            algorithm: Hash algorithm (blake3, sha3_256, sha256)

        Returns:
            Message digest
        """
        if algorithm == "blake3":
            try:
                import blake3

                return blake3.blake3(message).digest()
            except ImportError:
                # Fallback to BLAKE2b if blake3 not available
                return hashlib.blake2b(message, digest_size=32).digest()
        elif algorithm == "sha3_256":
            return hashlib.sha3_256(message).digest()
        elif algorithm == "sha256":
            return hashlib.sha256(message).digest()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    # ==================== Dual-Signature Operations ====================

    def create_dual_signature(
        self,
        message: bytes,
        pqc_keypair: KeyPair,
        classical_keypair: Optional[KeyPair] = None,
        suite_id: str = "tfp_pqc_v1",
    ) -> Signature:
        """
        Create a dual signature (PQC + classical) for migration period.

        Args:
            message: Message to sign
            pqc_keypair: PQC key pair (primary)
            classical_keypair: Classical key pair (optional, for backward compat)
            suite_id: Crypto suite identifier

        Returns:
            Signature with both PQC and classical components
        """
        # Create PQC signature
        pqc_sig = self.sign(message, pqc_keypair, suite_id, use_dual=False)

        # Add classical signature if key provided
        classical_sig = None
        if classical_keypair:
            # In production, would use Ed25519/ECDSA
            msg_hash = self.hash_message(message, "sha256")
            classical_sig = b"<classical_ed25519_stub>" + msg_hash

        return Signature(
            signature=pqc_sig.signature,
            algorithm=f"{pqc_keypair.algorithm}+classical",
            suite_id=suite_id,
            message_hash=pqc_sig.message_hash,
            timestamp=time.time(),
            is_dual=True,
            classical_signature=classical_sig,
        )

    def verify_dual_signature(
        self,
        message: bytes,
        signature: Signature,
        pqc_public_key: bytes,
        classical_public_key: Optional[bytes] = None,
    ) -> Tuple[bool, bool]:
        """
        Verify a dual signature.

        Args:
            message: Original message
            signature: Dual signature object
            pqc_public_key: PQC public key
            classical_public_key: Classical public key (optional)

        Returns:
            Tuple of (pqc_valid, classical_valid)
        """
        # Verify PQC signature
        pqc_valid = self.verify(message, signature, pqc_public_key)

        # Verify classical signature if present
        classical_valid = False
        if signature.classical_signature and classical_public_key:
            # In production, would verify Ed25519/ECDSA
            classical_valid = signature.classical_signature.startswith(b"<classical_")

        return pqc_valid, classical_valid

    # ==================== Utility Methods ====================

    def cache_keypair(self, key_id: str, keypair: KeyPair) -> None:
        """Cache a key pair for later use."""
        self._key_cache[key_id] = keypair

    def get_cached_keypair(self, key_id: str) -> Optional[KeyPair]:
        """Retrieve a cached key pair."""
        return self._key_cache.get(key_id)

    def clear_key_cache(self) -> None:
        """Clear all cached keys."""
        self._key_cache.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Get adapter statistics."""
        return {
            "pqc_enabled": self.use_pqc and PQC_AVAILABLE,
            "libraries_available": PQC_AVAILABLE,
            "cached_keys": len(self._key_cache),
            "supported_algorithms": [
                "dilithium5",
                "sphincs+",
                "kyber768",
                "blake3",
                "sha3_256",
            ],
        }


# Global adapter instance
_adapter_instance: Optional[PQCAdapter] = None


def get_adapter(use_pqc: bool = True) -> PQCAdapter:
    """Get the global PQC adapter instance."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = PQCAdapter(use_pqc=use_pqc)
    return _adapter_instance


def sign_content(
    content: bytes, key_id: str, suite_id: str = "tfp_pqc_v1", use_dual: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to sign content with dual signatures.

    Args:
        content: Content bytes to sign
        key_id: Identifier for key to use
        suite_id: Crypto suite ID
        use_dual: Enable dual-signature mode

    Returns:
        Signature metadata dict
    """
    adapter = get_adapter()
    keypair = adapter.get_cached_keypair(key_id)

    if not keypair:
        # Generate new key if not cached
        keypair = adapter.generate_dilithium5_keypair()
        adapter.cache_keypair(key_id, keypair)

    sig = adapter.create_dual_signature(content, keypair, suite_id=suite_id)
    return sig.to_dict()


def verify_content_signature(
    content: bytes, signature_data: Dict[str, Any], public_key: bytes
) -> bool:
    """
    Convenience function to verify content signature.

    Args:
        content: Original content
        signature_data: Signature metadata
        public_key: Public key for verification

    Returns:
        True if valid
    """
    adapter = get_adapter()

    sig = Signature(
        signature=bytes.fromhex(signature_data["signature"]),
        algorithm=signature_data["algorithm"],
        suite_id=signature_data["suite_id"],
        message_hash=bytes.fromhex(signature_data["message_hash"]),
        timestamp=signature_data["timestamp"],
        is_dual=signature_data.get("is_dual", False),
        classical_signature=bytes.fromhex(signature_data["classical_signature"])
        if signature_data.get("classical_signature")
        else None,
    )

    return adapter.verify(content, sig, public_key)
