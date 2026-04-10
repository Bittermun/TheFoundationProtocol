"""
TFP Crypto Export Gate v2.11

Ensures compliance with export control regulations (EAR, Wassenaar Arrangement).
Detects device jurisdiction and negotiates appropriate crypto suites.

Key features:
- Privacy-preserving jurisdiction detection (no PII logging)
- Automatic crypto suite downgrading in sanctioned/restricted regions
- Fallback to globally permissible primitives (SHA3, BLAKE3, SPHINCS+)
- Local-only operation (no jurisdiction data leaves device)
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum


class JurisdictionCategory(Enum):
    """Jurisdiction categories for crypto export control."""
    UNRESTRICTED = "unrestricted"  # Full PQC suite allowed
    RESTRICTED = "restricted"  # Some algorithms disabled
    SANCTIONED = "sanctioned"  # Only baseline primitives allowed
    UNKNOWN = "unknown"  # Default to most restrictive


# Cryptographic primitives by export category
CRYPTO_SUITE_UNRESTRICTED = {
    'signatures': ['Dilithium5', 'Falcon', 'SPHINCS+'],
    'key_exchange': ['ML-KEM-768', 'ML-KEM-1024'],
    'hashing': ['SHA3-256', 'BLAKE3', 'SHAKE256'],
    'aead': ['AES-256-GCM', 'ChaCha20-Poly1305']
}

CRYPTO_SUITE_RESTRICTED = {
    'signatures': ['Dilithium5', 'SPHINCS+'],  # Falcon removed (patent/export issues)
    'key_exchange': ['ML-KEM-768'],  # Only baseline Kyber
    'hashing': ['SHA3-256', 'BLAKE3'],
    'aead': ['ChaCha20-Poly1305']  # AES may require export license
}

CRYPTO_SUITE_SANCTIONED = {
    'signatures': ['SPHINCS+'],  # Stateless, no export restrictions
    'key_exchange': [],  # No key exchange; use pre-shared or broadcast-only
    'hashing': ['SHA3-256', 'BLAKE3'],  # Public domain algorithms
    'aead': ['ChaCha20-Poly1305']
}


@dataclass
class JurisdictionHeuristic:
    """Privacy-preserving jurisdiction detection result."""
    category: JurisdictionCategory
    confidence: float  # 0.0 to 1.0
    detection_method: str  # 'gps_coarse', 'network_prefix', 'user_declared', 'default'
    timestamp: float = field(default_factory=time.time)
    
    # Privacy guarantees
    pii_logged: bool = False
    location_precision: str = "country-level or coarser"
    data_retention: str = "ephemeral (session only)"
    
    def is_expired(self, max_age_seconds: float = 3600) -> bool:
        """Check if heuristic result is stale."""
        return (time.time() - self.timestamp) > max_age_seconds


@dataclass
class NegotiatedSuite:
    """Result of crypto suite negotiation."""
    suite_name: str
    algorithms: Dict[str, List[str]]
    jurisdiction_category: JurisdictionCategory
    fallback_used: bool = False
    warnings: List[str] = field(default_factory=list)


class CryptoExportGate:
    """
    Manages crypto export compliance for TFP devices.
    
    Core guarantees:
    - No PII logged during jurisdiction detection
    - Automatic fallback to safe primitives
    - Local-only operation
    - Graceful degradation (listen-only mode if compliance fails)
    """
    
    def __init__(self):
        self.current_heuristic: Optional[JurisdictionHeuristic] = None
        self.negotiated_suite: Optional[NegotiatedSuite] = None
        self.compliance_log: List[dict] = []
        
        # Pre-defined jurisdiction mappings (coarse-grained, privacy-preserving)
        # In production, this would be loaded from a signed NDN broadcast
        self.unrestricted_countries = {
            'US', 'CA', 'GB', 'DE', 'FR', 'JP', 'AU', 'NZ', 'KR', 'TW',
            'IN', 'BR', 'MX', 'ZA', 'SG', 'HK', 'IL', 'NO', 'SE', 'FI',
            'DK', 'NL', 'BE', 'CH', 'AT', 'IE', 'PT', 'ES', 'IT', 'PL',
            'CZ', 'GR', 'TR', 'TH', 'MY', 'PH', 'ID', 'VN'
        }
        
        self.restricted_countries = {
            'RU', 'BY', 'UA', 'KZ', 'AZ', 'GE', 'AM', 'MD', 'RS', 'BA',
            'ME', 'MK', 'AL', 'BG', 'RO', 'HU', 'SK', 'HR', 'SI', 'LT',
            'LV', 'EE', 'FI'  # Some EU countries have additional restrictions
        }
        
        self.sanctioned_countries = {
            'CN', 'KP', 'IR', 'SY', 'CU', 'VE', 'SD', 'MM', 'ZW', 'LY'
        }
    
    def detect_jurisdiction(
        self,
        gps_coarse: str = None,  # e.g., "US", "EU", or None
        network_prefix: str = None,  # e.g., IP prefix country code
        user_declared: str = None,  # User's self-declared country
        force_default: bool = False
    ) -> JurisdictionHeuristic:
        """
        Detect jurisdiction using privacy-preserving heuristics.
        
        Args:
            gps_coarse: Coarse GPS location (country code only, no coordinates)
            network_prefix: Network-derived country code
            user_declared: User's declared country
            force_default: Skip detection, use UNKNOWN
            
        Returns:
            JurisdictionHeuristic with category and confidence
        """
        if force_default:
            self.current_heuristic = JurisdictionHeuristic(
                category=JurisdictionCategory.UNKNOWN,
                confidence=0.0,
                detection_method='default'
            )
            return self.current_heuristic
        
        # Priority: user_declared > gps_coarse > network_prefix > default
        detected_country = None
        method = 'default'
        confidence = 0.0
        
        if user_declared and len(user_declared) == 2:
            detected_country = user_declared.upper()
            method = 'user_declared'
            confidence = 0.9
        elif gps_coarse and len(gps_coarse) == 2:
            detected_country = gps_coarse.upper()
            method = 'gps_coarse'
            confidence = 0.85
        elif network_prefix and len(network_prefix) == 2:
            detected_country = network_prefix.upper()
            method = 'network_prefix'
            confidence = 0.75
        
        # Determine category
        if detected_country:
            if detected_country in self.unrestricted_countries:
                category = JurisdictionCategory.UNRESTRICTED
            elif detected_country in self.restricted_countries:
                category = JurisdictionCategory.RESTRICTED
            elif detected_country in self.sanctioned_countries:
                category = JurisdictionCategory.SANCTIONED
            else:
                # Unknown country, default to restricted
                category = JurisdictionCategory.RESTRICTED
                confidence *= 0.5
        else:
            category = JurisdictionCategory.UNKNOWN
            confidence = 0.0
        
        self.current_heuristic = JurisdictionHeuristic(
            category=category,
            confidence=confidence,
            detection_method=method
        )
        
        # Log compliance event (no PII)
        self._log_compliance_event('jurisdiction_detected', {
            'category': category.value,
            'method': method,
            'confidence': confidence,
            'timestamp': time.time()
        })
        
        return self.current_heuristic
    
    def negotiate_suite(self, requested_algorithms: Dict[str, List[str]] = None) -> NegotiatedSuite:
        """
        Negotiate crypto suite based on jurisdiction.
        
        Args:
            requested_algorithms: Algorithms requested by application
            
        Returns:
            NegotiatedSuite with approved algorithms
        """
        if not self.current_heuristic:
            # Auto-detect with defaults if not already done
            self.detect_jurisdiction()
        
        # Select base suite by category
        category = self.current_heuristic.category
        
        if category == JurisdictionCategory.UNRESTRICTED:
            base_suite = CRYPTO_SUITE_UNRESTRICTED.copy()
            suite_name = "UNRESTRICTED_PQC_FULL"
        elif category == JurisdictionCategory.RESTRICTED:
            base_suite = CRYPTO_SUITE_RESTRICTED.copy()
            suite_name = "RESTRICTED_PQC_BASELINE"
        elif category == JurisdictionCategory.SANCTIONED:
            base_suite = CRYPTO_SUITE_SANCTIONED.copy()
            suite_name = "SANCTIONED_MINIMAL"
        else:  # UNKNOWN
            base_suite = CRYPTO_SUITE_SANCTIONED.copy()
            suite_name = "UNKNOWN_FALLBACK"
            self.current_heuristic.category = JurisdictionCategory.SANCTIONED
        
        warnings = []
        fallback_used = False
        
        # Check if requested algorithms are available
        if requested_algorithms:
            for algo_type, requested in requested_algorithms.items():
                if algo_type not in base_suite:
                    continue
                
                available = set(base_suite[algo_type])
                missing = set(requested) - available
                
                if missing:
                    warnings.append(
                        f"Requested {algo_type} algorithms not available in jurisdiction: {missing}"
                    )
                    fallback_used = True
        
        # Special handling for sanctioned regions
        if category == JurisdictionCategory.SANCTIONED:
            warnings.append(
                "Operating in sanctioned region. Only baseline cryptographic primitives available."
            )
            if base_suite['key_exchange']:
                warnings.append(
                    "Key exchange disabled. Use pre-shared keys or broadcast-only mode."
                )
        
        self.negotiated_suite = NegotiatedSuite(
            suite_name=suite_name,
            algorithms=base_suite,
            jurisdiction_category=self.current_heuristic.category,
            fallback_used=fallback_used,
            warnings=warnings
        )
        
        return self.negotiated_suite
    
    def get_approved_algorithm(self, algo_type: str, preferred: str = None) -> Optional[str]:
        """
        Get an approved algorithm for a specific type.
        
        Args:
            algo_type: Type of algorithm ('signatures', 'key_exchange', 'hashing', 'aead')
            preferred: Preferred algorithm name (if available)
            
        Returns:
            Approved algorithm name or None
        """
        if not self.negotiated_suite:
            self.negotiate_suite()
        
        available = self.negotiated_suite.algorithms.get(algo_type, [])
        
        if not available:
            return None
        
        if preferred and preferred in available:
            return preferred
        
        return available[0]  # Return first (most preferred) available
    
    def is_compliant(self) -> Tuple[bool, str]:
        """
        Check if current configuration is compliant.
        
        Returns:
            (is_compliant, reason)
        """
        if not self.current_heuristic:
            return False, "Jurisdiction not detected"
        
        if not self.negotiated_suite:
            return False, "Crypto suite not negotiated"
        
        if self.current_heuristic.category == JurisdictionCategory.UNKNOWN:
            return True, "Using fallback minimal suite (compliant but limited)"
        
        return True, f"Compliant for {self.current_heuristic.category.value} jurisdiction"
    
    def enter_listen_only_mode(self) -> dict:
        """
        Enter listen-only mode when compliance cannot be established.
        
        In this mode:
        - Device can receive and verify content
        - Device cannot sign or transmit
        - Only hash verification (SHA3/BLAKE3) is used
        
        Returns:
            Mode configuration
        """
        mode_config = {
            'mode': 'LISTEN_ONLY',
            'can_receive': True,
            'can_transmit': False,
            'can_sign': False,
            'allowed_algorithms': {
                'hashing': ['SHA3-256', 'BLAKE3'],
                'verification': ['SPHINCS+']  # For verifying existing signatures
            },
            'reason': 'Compliance check failed or jurisdiction unknown',
            'timestamp': time.time()
        }
        
        self._log_compliance_event('listen_only_mode_entered', mode_config)
        
        return mode_config
    
    def _log_compliance_event(self, event_type: str, details: dict) -> None:
        """Log compliance event (no PII)."""
        entry = {
            'event_type': event_type,
            'details': details,
            'timestamp': time.time(),
            'pii_logged': False
        }
        self.compliance_log.append(entry)
        
        # Keep log bounded
        if len(self.compliance_log) > 1000:
            self.compliance_log = self.compliance_log[-1000:]
    
    def generate_compliance_report(self) -> dict:
        """Generate compliance report for audit."""
        return {
            'timestamp': time.time(),
            'jurisdiction': self.current_heuristic.category.value if self.current_heuristic else 'UNKNOWN',
            'detection_method': self.current_heuristic.detection_method if self.current_heuristic else 'NONE',
            'negotiated_suite': self.negotiated_suite.suite_name if self.negotiated_suite else 'NONE',
            'approved_algorithms': self.negotiated_suite.algorithms if self.negotiated_suite else {},
            'warnings': self.negotiated_suite.warnings if self.negotiated_suite else [],
            'events_logged': len(self.compliance_log),
            'pii_logged': False,
            'compliance_status': self.is_compliant()[0]
        }


# Example usage
if __name__ == '__main__':
    gate = CryptoExportGate()
    
    # Scenario 1: Unrestricted region (e.g., US)
    print("=== Scenario 1: United States ===")
    heuristic = gate.detect_jurisdiction(gps_coarse='US')
    suite = gate.negotiate_suite()
    print(f"Jurisdiction: {heuristic.category.value} ({heuristic.confidence:.0%} confidence)")
    print(f"Suite: {suite.suite_name}")
    print(f"Signatures: {suite.algorithms['signatures']}")
    print(f"Key Exchange: {suite.algorithms['key_exchange']}")
    
    # Scenario 2: Sanctioned region (e.g., Iran)
    print("\n=== Scenario 2: Iran (Sanctioned) ===")
    gate2 = CryptoExportGate()
    heuristic2 = gate2.detect_jurisdiction(gps_coarse='IR')
    suite2 = gate2.negotiate_suite()
    print(f"Jurisdiction: {heuristic2.category.value}")
    print(f"Suite: {suite2.suite_name}")
    print(f"Signatures: {suite2.algorithms['signatures']}")
    print(f"Key Exchange: {suite2.algorithms['key_exchange']}")
    print(f"Warnings: {suite2.warnings}")
    
    # Scenario 3: Unknown/default
    print("\n=== Scenario 3: Unknown (Default) ===")
    gate3 = CryptoExportGate()
    heuristic3 = gate3.detect_jurisdiction(force_default=True)
    suite3 = gate3.negotiate_suite()
    print(f"Jurisdiction: {heuristic3.category.value}")
    print(f"Suite: {suite3.suite_name}")
    
    # Enter listen-only mode
    print("\n=== Listen-Only Mode ===")
    mode = gate3.enter_listen_only_mode()
    print(f"Mode: {mode['mode']}")
    print(f"Can Transmit: {mode['can_transmit']}")
    
    # Generate compliance report
    print("\n=== Compliance Report ===")
    report = gate.generate_compliance_report()
    print(f"Status: {'COMPLIANT' if report['compliance_status'] else 'NON-COMPLIANT'}")
    print(f"PII Logged: {report['pii_logged']}")
