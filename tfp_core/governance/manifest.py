"""
TFP Governance Manifest
Defines maintainer status, license, contribution guidelines, and accountability structure.
Addresses: "Who maintains this?" question for NGOs, enterprises, and contributors.
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional


class GovernanceManifest:
    """
    Immutable governance manifest that answers critical adoption questions.
    Signed and versioned for transparency.
    """

    def __init__(self):
        self.manifest_version = "3.1.0"
        self.created_at = datetime.utcnow().isoformat() + "Z"

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
            "license": "MIT",
            "contribution_guidelines": "https://github.com/Bittermun/Scholo/blob/main/CONTRIBUTING.md",
            "code_of_conduct": "https://github.com/Bittermun/Scholo/blob/main/CODE_OF_CONDUCT.md",
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
            "succession_plan": "Multi-sig control of critical repos; community fork rights guaranteed by MIT license",
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

    def sign_manifest(self, private_key: Optional[str] = None) -> str:
        """
        Generate cryptographic signature of manifest for integrity verification.
        In production, use PGP or Ed25519 key. For now, SHA3-256 hash as placeholder.
        """
        manifest_json = json.dumps(self.generate_manifest(), sort_keys=True)
        signature = hashlib.sha3_256(manifest_json.encode()).hexdigest()
        return signature

    def verify_integrity(self, manifest_data: Dict, expected_signature: str) -> bool:
        """Verify manifest hasn't been tampered with."""
        manifest_json = json.dumps(manifest_data, sort_keys=True)
        computed_signature = hashlib.sha3_256(manifest_json.encode()).hexdigest()
        return computed_signature == expected_signature

    def save_to_file(self, filepath: str = "GOVERNANCE_MANIFEST.json") -> None:
        """Save manifest to file with signature."""
        manifest = self.generate_manifest()
        manifest["signature"] = self.sign_manifest()
        manifest["signature_algorithm"] = "SHA3-256 (placeholder for PGP)"

        with open(filepath, "w") as f:
            json.dump(manifest, f, indent=2)

        print(f"✓ Governance manifest saved to {filepath}")
        print(f"  Signature: {manifest['signature'][:16]}...")

    def get_adoption_readiness_score(self) -> Dict[str, any]:
        """
        Self-assessment of adoption readiness based on governance maturity.
        Used for NGO/enterprise evaluations.
        """
        criteria = {
            "clear_maintainer": len(self.maintainers) > 0,
            "open_license": self.contribution_model["license"] == "MIT",
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
    print("TFP GOVERNANCE MANIFEST v3.1")
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
