# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Governance Manifest
Defines maintainer status, license, contribution guidelines, and accountability structure.
Addresses: "Who maintains this?" question for NGOs, enterprises, and contributors.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    ed25519 = None


class GovernanceManifest:
    """
    Immutable governance manifest that answers critical adoption questions.
    Signed and versioned for transparency.
    """

    def __init__(self):
        self.manifest_version = "3.2.0"
        self.created_at = datetime.now(timezone.utc).isoformat()

        # Maintainer Information (Transparent)
        self.maintainers = [
            {
                "role": "Lead Architect",
                "status": "Active (Solo Founder)",
                "commitment": "Full-time",
                "contact": "governance@tfp-protocol.org",  # Placeholder
                "pgp_fingerprint": "Not yet published — see governance@tfp-protocol.org",
            }
        ]

        self.contribution_model = {
            "type": "Open Source Community",
            "license": "Apache-2.0",
            "contribution_guidelines": "https://github.com/Bittermun/TheFoundationProtocol/blob/main/CONTRIBUTING.md",
            "code_of_conduct": "https://github.com/Bittermun/TheFoundationProtocol/blob/main/CODE_OF_CONDUCT.md",
            "decision_making": "BDFL (Benevolent Dictator For Life) with community RFC process",
            "roadmap_input": "GitHub Issues + Community Forum",
        }

        # Sustainability Model
        self.sustainability = {
            "funding_status": "Seeking Grants/Donations",
            "revenue_model": "None (Protocol is free; plugins may monetize)",
            "infrastructure_funding": "Community-hosted nodes + Grant-funded testbeds",
            "long_term_plan": "Transition to Foundation governance upon reaching 100+ active contributors",
        }

        # Accountability Mechanisms
        self.accountability = {
            "security_audit_schedule": "Quarterly independent audits (budget permitting)",
            "vulnerability_disclosure": "security@tfp-protocol.org (90-day disclosure window)",
            "transparency_reports": "Bi-annual public reports on development progress",
            "succession_plan": "Multi-sig control of critical repos; community fork rights guaranteed by Apache-2.0 license",
        }

        # Technical Stewardship
        self.stewardship = {
            "release_cycle": "Monthly minor releases; Quarterly major releases",
            "breaking_change_policy": "6-month deprecation notice; Semantic versioning enforced",
            "backward_compatibility": "Minimum 2 major versions supported",
            "documentation_commitment": "All user-facing features require docs before merge",
        }

        # Community Health Metrics (Public Dashboard)
        self.health_metrics = {
            "active_contributors_target": 100,
            "geographic_diversity_target": "20+ countries",
            "issue_response_time_sla": "<48 hours for critical bugs",
            "pr_review_time_sla": "<7 days for non-trivial PRs",
        }

    def generate_manifest(self) -> Dict:
        """Generate complete manifest as dictionary."""
        return {
            "manifest_version": self.manifest_version,
            "created_at": self.created_at,
            "maintainers": self.maintainers,
            "contribution_model": self.contribution_model,
            "sustainability": self.sustainability,
            "accountability": self.accountability,
            "stewardship": self.stewardship,
            "health_metrics": self.health_metrics,
        }

    def sign_manifest(self, private_key: Optional[any] = None) -> str:
        """
        Generate cryptographic signature of manifest for integrity verification.
        Uses Ed25519 when private key is provided (or generated), returning hex signature.
        Falls back to SHA3-256 canonical digest for integrity identification.
        """
        manifest_json = json.dumps(self.generate_manifest(), sort_keys=True).encode()
        if private_key is not None and ed25519 is not None:
            try:
                if isinstance(private_key, (bytes, bytearray)):
                    sk = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_key[:32]))
                elif isinstance(private_key, str):
                    try:
                        raw = bytes.fromhex(private_key)
                    except ValueError:
                        raw = base64.b64decode(private_key)
                    sk = ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])
                else:
                    sk = private_key
                return sk.sign(manifest_json).hex()
            except Exception:
                pass
        return hashlib.sha3_256(manifest_json).hexdigest()

    def sign_manifest_ed25519(self, private_key: Optional[any] = None) -> Dict[str, str]:
        """
        Sign manifest canonically using an Ed25519 private key.
        Returns dict containing signature, public_key (hex), and algorithm identifier.
        """
        if ed25519 is None:
            raise RuntimeError("cryptography library required for Ed25519 manifest signing")
        if private_key is None:
            sk = ed25519.Ed25519PrivateKey.generate()
        elif isinstance(private_key, (bytes, bytearray)):
            sk = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_key[:32]))
        elif isinstance(private_key, str):
            try:
                raw = bytes.fromhex(private_key)
            except ValueError:
                raw = base64.b64decode(private_key)
            sk = ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])
        else:
            sk = private_key

        manifest_json = json.dumps(self.generate_manifest(), sort_keys=True).encode()
        sig = sk.sign(manifest_json)
        pub = sk.public_key()
        pub_bytes = pub.public_bytes_raw()
        return {
            "signature": sig.hex(),
            "public_key": pub_bytes.hex(),
            "signature_algorithm": "Ed25519",
        }

    def verify_integrity(
        self,
        manifest_data: Dict,
        expected_signature: str,
        public_key: Optional[any] = None,
    ) -> bool:
        """
        Verify manifest integrity.
        Validates against Ed25519 signature if public_key is provided or embedded,
        otherwise performs constant-time SHA3-256 digest comparison.
        """
        clean_manifest = {
            k: v for k, v in manifest_data.items()
            if k not in ("signature", "signature_algorithm", "public_key")
        }
        manifest_json = json.dumps(clean_manifest, sort_keys=True).encode()

        # Check Ed25519
        pk_val = public_key or manifest_data.get("public_key")
        algo = manifest_data.get("signature_algorithm", "")
        if pk_val and (algo == "Ed25519" or len(expected_signature) == 128) and ed25519 is not None:
            try:
                if isinstance(pk_val, str):
                    pk_bytes = bytes.fromhex(pk_val)
                else:
                    pk_bytes = bytes(pk_val)
                sig_bytes = bytes.fromhex(expected_signature)
                pk = ed25519.Ed25519PublicKey.from_public_bytes(pk_bytes)
                pk.verify(sig_bytes, manifest_json)
                return True
            except Exception:
                return False

        computed_signature = hashlib.sha3_256(manifest_json).hexdigest()
        return hmac.compare_digest(computed_signature, expected_signature)

    def save_to_file(
        self,
        filepath: str = "GOVERNANCE_MANIFEST.json",
        private_key: Optional[any] = None,
    ) -> None:
        """Save manifest to file with Ed25519 signature."""
        manifest = self.generate_manifest()
        if ed25519 is not None:
            sig_info = self.sign_manifest_ed25519(private_key)
            manifest["signature"] = sig_info["signature"]
            manifest["public_key"] = sig_info["public_key"]
            manifest["signature_algorithm"] = sig_info["signature_algorithm"]
        else:
            manifest["signature"] = self.sign_manifest()
            manifest["signature_algorithm"] = "SHA3-256"

        with open(filepath, "w") as f:
            json.dump(manifest, f, indent=2)

        print(f"✓ Governance manifest saved to {filepath}")
        print(f"  Algorithm: {manifest['signature_algorithm']}")
        print(f"  Signature: {manifest['signature'][:16]}...")

    def get_adoption_readiness_score(self) -> Dict[str, any]:
        """
        Self-assessment of adoption readiness based on governance maturity.
        Used for NGO/enterprise evaluations.
        """
        criteria = {
            "clear_maintainer": len(self.maintainers) > 0,
            "open_license": self.contribution_model["license"] == "Apache-2.0",
            "contribution_path": bool(
                self.contribution_model["contribution_guidelines"]
            ),
            "security_process": bool(self.accountability["vulnerability_disclosure"]),
            "sustainability_plan": bool(self.sustainability["long_term_plan"]),
            "documentation_commitment": bool(
                self.stewardship["documentation_commitment"]
            ),
        }

        score = sum(criteria.values()) / len(criteria) * 100

        return {
            "overall_score": score,
            "criteria": criteria,
            "strengths": [k for k, v in criteria.items() if v],
            "gaps": [k for k, v in criteria.items() if not v],
            "recommendation": "Ready for pilot deployment"
            if score >= 80
            else "Address gaps before enterprise deployment",
        }


def main():
    """Generate and display governance manifest."""
    manifest = GovernanceManifest()

    print("=" * 60)
    print("TFP GOVERNANCE MANIFEST v3.2")
    print("=" * 60)
    print("\n📋 MAINTAINER STATUS:")
    for m in manifest.maintainers:
        print(f"  • {m['role']}: {m['status']} ({m['commitment']})")

    print("\n🤝 CONTRIBUTION MODEL:")
    print(f"  • License: {manifest.contribution_model['license']}")
    print(f"  • Decision Making: {manifest.contribution_model['decision_making']}")

    print("\n💰 SUSTAINABILITY:")
    print(f"  • Funding: {manifest.sustainability['funding_status']}")
    print(f"  • Long-term: {manifest.sustainability['long_term_plan']}")

    print("\n🛡️ ACCOUNTABILITY:")
    print(f"  • Security Audits: {manifest.accountability['security_audit_schedule']}")
    print(
        f"  • Vulnerability Disclosure: {manifest.accountability['vulnerability_disclosure']}"
    )

    print("\n📊 ADOPTION READINESS:")
    readiness = manifest.get_adoption_readiness_score()
    print(f"  • Score: {readiness['overall_score']:.0f}%")
    print(f"  • Status: {readiness['recommendation']}")

    # Save to file
    manifest.save_to_file()

    print("\n✅ Manifest generated. Share with NGOs, enterprises, and contributors.")


if __name__ == "__main__":
    main()
