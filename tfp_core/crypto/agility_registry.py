"""
TFP Cryptographic Agility Registry

Manages versioned PQC suites with zero hardcoded algorithms.
Devices negotiate crypto suites at boot via NDN config broadcasts.
Supports dual-signature mode (classical + PQC) for migration window.

Algorithms:
- Signatures: Dilithium5, SPHINCS+, Falcon
- KEM: ML-KEM (Kyber)
- Hashes: BLAKE3, SHA3-256
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CryptoAlgorithm(Enum):
    """Supported cryptographic algorithms with security levels."""
    # Post-Quantum Signatures
    DILITHIUM5 = "dilithium5"  # NIST Level 3
    DILITHIUM3 = "dilithium3"  # NIST Level 2
    SPHINCS_PLUS = "sphincs+"  # Stateless, ideal for broadcast
    FALCON = "falcon"  # Compact signatures
    
    # Classical (legacy, for dual-signature migration)
    ECDSA_P256 = "ecdsa_p256"
    ED25519 = "ed25519"
    
    # Key Encapsulation
    ML_KEM_768 = "ml_kem_768"  # Kyber-768
    ML_KEM_1024 = "ml_kem_1024"  # Kyber-1024
    
    # Hash Functions
    BLAKE3 = "blake3"
    SHA3_256 = "sha3_256"
    SHA256 = "sha256"  # Legacy


@dataclass
class CryptoSuite:
    """A versioned cryptographic suite configuration."""
    suite_id: str
    version: int
    signature_algo: CryptoAlgorithm
    hash_algo: CryptoAlgorithm
    kem_algo: Optional[CryptoAlgorithm] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    is_deprecated: bool = False
    fallback_suite_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "version": self.version,
            "signature_algo": self.signature_algo.value,
            "hash_algo": self.hash_algo.value,
            "kem_algo": self.kem_algo.value if self.kem_algo else None,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_deprecated": self.is_deprecated,
            "fallback_suite_id": self.fallback_suite_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CryptoSuite':
        return cls(
            suite_id=data["suite_id"],
            version=data["version"],
            signature_algo=CryptoAlgorithm(data["signature_algo"]),
            hash_algo=CryptoAlgorithm(data["hash_algo"]),
            kem_algo=CryptoAlgorithm(data["kem_algo"]) if data.get("kem_algo") else None,
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            is_deprecated=data.get("is_deprecated", False),
            fallback_suite_id=data.get("fallback_suite_id")
        )


@dataclass
class NegotiationResult:
    """Result of crypto suite negotiation between device and network."""
    success: bool
    selected_suite: Optional[CryptoSuite]
    fallback_used: bool
    reason: str
    supported_algos: List[CryptoAlgorithm] = field(default_factory=list)


class CryptoAgilityRegistry:
    """
    Manages versioned cryptographic suites with automatic negotiation.
    
    Features:
    - Zero hardcoded algorithms
    - Versioned suite broadcasting via NDN
    - Dual-signature mode for PQC migration
    - Automatic fallback chains
    - Deprecation scheduling
    """
    
    DEFAULT_SUITE_ID = "tfp_pqc_v1"
    
    def __init__(self):
        self._suites: Dict[str, CryptoSuite] = {}
        self._active_suite_id: str = self.DEFAULT_SUITE_ID
        self._device_capabilities: Dict[str, List[CryptoAlgorithm]] = {}
        self._negotiation_cache: Dict[str, NegotiationResult] = {}
        
        # Initialize default PQC suite
        self._register_default_suite()
    
    def _register_default_suite(self) -> None:
        """Register the default post-quantum suite."""
        default_suite = CryptoSuite(
            suite_id=self.DEFAULT_SUITE_ID,
            version=1,
            signature_algo=CryptoAlgorithm.DILITHIUM5,
            hash_algo=CryptoAlgorithm.BLAKE3,
            kem_algo=CryptoAlgorithm.ML_KEM_768,
            expires_at=None,  # No expiry for default
            is_deprecated=False
        )
        self._suites[self.DEFAULT_SUITE_ID] = default_suite
        
        # Register legacy suite for dual-signature migration
        legacy_suite = CryptoSuite(
            suite_id="tfp_classic_v1",
            version=1,
            signature_algo=CryptoAlgorithm.ED25519,
            hash_algo=CryptoAlgorithm.SHA256,
            kem_algo=None,
            is_deprecated=True,
            fallback_suite_id=self.DEFAULT_SUITE_ID
        )
        self._suites["tfp_classic_v1"] = legacy_suite
    
    def register_suite(self, suite: CryptoSuite) -> bool:
        """
        Register a new cryptographic suite.
        
        Args:
            suite: CryptoSuite to register
            
        Returns:
            True if registered successfully
        """
        if suite.suite_id in self._suites:
            existing = self._suites[suite.suite_id]
            if suite.version <= existing.version:
                logger.warning(f"Suite {suite.suite_id} v{suite.version} not newer than existing v{existing.version}")
                return False
        
        self._suites[suite.suite_id] = suite
        logger.info(f"Registered crypto suite: {suite.suite_id} v{suite.version}")
        return True
    
    def get_suite(self, suite_id: str) -> Optional[CryptoSuite]:
        """Get a specific suite by ID."""
        return self._suites.get(suite_id)
    
    def get_active_suite(self) -> CryptoSuite:
        """Get the currently active suite."""
        suite = self._suites.get(self._active_suite_id)
        if not suite:
            # Fallback to default
            return self._suites[self.DEFAULT_SUITE_ID]
        return suite
    
    def set_active_suite(self, suite_id: str) -> bool:
        """
        Set the active suite for new operations.
        
        Args:
            suite_id: ID of suite to activate
            
        Returns:
            True if activated successfully
        """
        if suite_id not in self._suites:
            logger.error(f"Cannot activate unknown suite: {suite_id}")
            return False
        
        suite = self._suites[suite_id]
        if suite.is_deprecated:
            logger.warning(f"Activating deprecated suite: {suite_id}")
        
        self._active_suite_id = suite_id
        logger.info(f"Active suite set to: {suite_id}")
        return True
    
    def negotiate_suite(
        self,
        device_id: str,
        device_algos: List[CryptoAlgorithm],
        requested_suite_id: Optional[str] = None
    ) -> NegotiationResult:
        """
        Negotiate crypto suite with a device based on capabilities.
        
        Args:
            device_id: Unique device identifier
            device_algos: Algorithms supported by the device
            requested_suite_id: Optional specific suite requested
            
        Returns:
            NegotiationResult with selected suite
        """
        # Check cache first
        cache_key = f"{device_id}:{requested_suite_id}"
        if cache_key in self._negotiation_cache:
            cached = self._negotiation_cache[cache_key]
            # Cache valid for 5 minutes
            if time.time() - cached.selected_suite.created_at < 300 if cached.selected_suite else False:
                return cached
        
        # Store device capabilities
        self._device_capabilities[device_id] = device_algos
        
        # Try requested suite first
        if requested_suite_id:
            requested_suite = self._suites.get(requested_suite_id)
            if requested_suite and not requested_suite.is_deprecated:
                if self._algo_compatible(requested_suite, device_algos):
                    result = NegotiationResult(
                        success=True,
                        selected_suite=requested_suite,
                        fallback_used=False,
                        reason="Requested suite compatible",
                        supported_algos=device_algos
                    )
                    self._negotiation_cache[cache_key] = result
                    return result
        
        # Find best compatible suite
        active_suite = self.get_active_suite()
        if self._algo_compatible(active_suite, device_algos):
            result = NegotiationResult(
                success=True,
                selected_suite=active_suite,
                fallback_used=False,
                reason="Active suite compatible",
                supported_algos=device_algos
            )
            self._negotiation_cache[cache_key] = result
            return result
        
        # Try fallback chain
        fallback_id = active_suite.fallback_suite_id
        while fallback_id:
            fallback_suite = self._suites.get(fallback_id)
            if fallback_suite and self._algo_compatible(fallback_suite, device_algos):
                result = NegotiationResult(
                    success=True,
                    selected_suite=fallback_suite,
                    fallback_used=True,
                    reason=f"Fallback to {fallback_id}",
                    supported_algos=device_algos
                )
                self._negotiation_cache[cache_key] = result
                return result
            fallback_id = fallback_suite.fallback_suite_id if fallback_suite else None
        
        # No compatible suite found
        result = NegotiationResult(
            success=False,
            selected_suite=None,
            fallback_used=False,
            reason="No compatible suite found",
            supported_algos=device_algos
        )
        self._negotiation_cache[cache_key] = result
        return result
    
    def _algo_compatible(
        self,
        suite: CryptoSuite,
        device_algos: List[CryptoAlgorithm]
    ) -> bool:
        """Check if device supports all required algorithms in suite."""
        required = [suite.signature_algo, suite.hash_algo]
        if suite.kem_algo:
            required.append(suite.kem_algo)
        
        return all(algo in device_algos for algo in required)
    
    def get_dual_signature_config(self) -> Tuple[CryptoSuite, Optional[CryptoSuite]]:
        """
        Get configuration for dual-signature mode (PQC + classical).
        
        Returns:
            Tuple of (primary_suite, legacy_suite) or (primary_suite, None)
        """
        primary = self.get_active_suite()
        
        # Find a legacy suite for dual-signing during migration
        legacy = None
        for suite in self._suites.values():
            if suite.is_deprecated and suite.fallback_suite_id == primary.suite_id:
                legacy = suite
                break
        
        return primary, legacy
    
    def export_suite_broadcast(self) -> Dict[str, Any]:
        """
        Export suite configuration for NDN broadcast.
        
        Returns:
            JSON-serializable dict for broadcast
        """
        return {
            "active_suite": self._active_suite_id,
            "available_suites": [s.to_dict() for s in self._suites.values()],
            "timestamp": time.time(),
            "dual_signature_enabled": True
        }
    
    def import_suite_broadcast(self, broadcast_data: Dict[str, Any]) -> bool:
        """
        Import suite configuration from NDN broadcast.
        
        Args:
            broadcast_data: Data received from NDN broadcast
            
        Returns:
            True if imported successfully
        """
        try:
            active_id = broadcast_data.get("active_suite")
            suites_data = broadcast_data.get("available_suites", [])
            
            for suite_data in suites_data:
                suite = CryptoSuite.from_dict(suite_data)
                self.register_suite(suite)
            
            if active_id and active_id in self._suites:
                self.set_active_suite(active_id)
            
            logger.info(f"Imported {len(suites_data)} suites from broadcast")
            return True
        except Exception as e:
            logger.error(f"Failed to import suite broadcast: {e}")
            return False
    
    def clear_negotiation_cache(self) -> None:
        """Clear the negotiation cache."""
        self._negotiation_cache.clear()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_suites": len(self._suites),
            "active_suite": self._active_suite_id,
            "cached_negotiations": len(self._negotiation_cache),
            "registered_devices": len(self._device_capabilities),
            "deprecated_suites": sum(1 for s in self._suites.values() if s.is_deprecated)
        }


# Convenience functions for direct use
_registry_instance: Optional[CryptoAgilityRegistry] = None


def get_registry() -> CryptoAgilityRegistry:
    """Get the global registry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = CryptoAgilityRegistry()
    return _registry_instance


def sign_data(data: bytes, suite_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Sign data using the specified or active suite.
    
    In production, this would call liboqs/pqcrypto bindings.
    This is a stub demonstrating the interface.
    """
    registry = get_registry()
    suite = registry.get_suite(suite_id) if suite_id else registry.get_active_suite()
    
    if not suite:
        raise ValueError(f"Suite not found: {suite_id}")
    
    # Hash the data
    if suite.hash_algo == CryptoAlgorithm.BLAKE3:
        try:
            import blake3
            digest = blake3.blake3(data).digest()
        except ImportError:
            # Fallback to BLAKE2b if blake3 not available
            digest = hashlib.blake2b(data, digest_size=32).digest()
    elif suite.hash_algo == CryptoAlgorithm.SHA3_256:
        digest = hashlib.sha3_256(data).digest()
    else:
        digest = hashlib.sha256(data).digest()
    
    # In production: call PQC signing library
    # For now, return metadata about what would be signed
    return {
        "suite_id": suite.suite_id,
        "algorithm": suite.signature_algo.value,
        "hash": digest.hex(),
        "signature_placeholder": f"<{suite.signature_algo.value}_signature>",
        "timestamp": time.time()
    }


def verify_signature(
    data: bytes,
    signature: bytes,
    suite_id: str,
    public_key: bytes
) -> bool:
    """
    Verify a signature using the specified suite.
    
    In production, this would call liboqs/pqcrypto bindings.
    """
    registry = get_registry()
    suite = registry.get_suite(suite_id)
    
    if not suite:
        logger.error(f"Suite not found: {suite_id}")
        return False
    
    # In production: call PQC verification library
    # For now, return True for valid-looking placeholders
    if signature.startswith(b"<") and signature.endswith(b">"):
        logger.debug(f"Placeholder signature verified for {suite_id}")
        return True
    
    return False
