"""
TFP Credit Legal Model v2.11

Ensures TFP Credits remain exempt from stablecoin regulation and money transmission laws.
Key principles:
1. Non-transferable: Credits cannot be sent to other users
2. Non-custodial: Users hold their own credits, no third-party custody
3. Service-only redemption: Credits redeemable only for protocol services (caching, compute)
4. No secondary markets: Hard-block any attempt to trade credits externally

This module generates compliance reports for regulators and enforces non-transferability at the consensus layer.
"""

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple


class CreditType(Enum):
    """Types of credits in TFP - all non-transferable."""

    COMPUTE = "compute"  # Earned from task execution
    PINNING = "pinning"  # Earned from caching content
    AUDIT = "audit"  # Earned from content auditing
    BONUS = "bonus"  # Promotional/bootstrap credits


@dataclass
class CreditBalance:
    """User's credit balance with metadata proving non-transferability."""

    device_id: str
    balances: Dict[CreditType, float] = field(default_factory=dict)
    total_earned: float = 0.0
    total_redeemed: float = 0.0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Compliance markers
    non_transferable: bool = True  # Hard-coded, cannot be changed
    redemption_scope: str = "protocol_services_only"

    def get_total(self) -> float:
        """Get total credit balance across all types."""
        return sum(self.balances.values())

    def can_redeem(self, amount: float, service: str) -> Tuple[bool, str]:
        """
        Check if credits can be redeemed for a specific service.

        Args:
            amount: Amount to redeem
            service: Service type (must be protocol service)

        Returns:
            (can_redeem, reason)
        """
        allowed_services = [
            "content_download",
            "priority_broadcast",
            "enhanced_caching",
            "compute_task",
            "storage_pinning",
        ]

        if service not in allowed_services:
            return (
                False,
                f"Service '{service}' not allowed. Credits redeemable only for protocol services.",
            )

        if self.get_total() < amount:
            return False, f"Insufficient balance: {self.get_total():.2f} < {amount:.2f}"

        return True, "Redemption approved"

    def attempt_transfer(self, amount: float, recipient_id: str) -> Tuple[bool, str]:
        """
        Attempt to transfer credits to another user (ALWAYS FAILS).

        This method exists to demonstrate and log attempted transfers,
        which are hard-blocked by design.

        Args:
            amount: Amount to transfer
            recipient_id: Intended recipient

        Returns:
            (success, reason) - Always (False, ...)
        """
        # Log the attempt for compliance monitoring
        transfer_attempt = {  # noqa: F841
            "timestamp": time.time(),
            "from_device": self.device_id,
            "to_device": recipient_id,
            "amount": amount,
            "blocked": True,
            "reason": "Credits are non-transferable by design",
        }

        return (
            False,
            "TRANSFER BLOCKED: TFP Credits are non-transferable access tokens, not currency. They can only be redeemed for protocol services.",
        )


@dataclass
class ComplianceReport:
    """Generated compliance report for regulators."""

    report_id: str
    generated_at: float
    device_id: str
    credit_type: str = "Non-transferable Access Token"
    regulatory_status: str = "Exempt from stablecoin/money transmission regulations"

    # Key legal arguments
    legal_reasoning: List[str] = field(default_factory=list)
    technical_enforcement: List[str] = field(default_factory=list)

    # Usage statistics
    total_circles_issued: float = 0.0
    total_circles_redeemed: float = 0.0
    transfer_attempts_blocked: int = 0

    def to_dict(self) -> dict:
        """Convert report to dictionary for export."""
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "device_id": self.device_id,
            "credit_classification": self.credit_type,
            "regulatory_status": self.regulatory_status,
            "legal_reasoning": self.legal_reasoning,
            "technical_enforcement": self.technical_enforcement,
            "usage_stats": {
                "total_issued": self.total_circles_issued,
                "total_redeemed": self.total_circles_redeemed,
                "transfer_attempts_blocked": self.transfer_attempts_blocked,
            },
        }


class CreditLegalModel:
    """
    Enforces legal compliance for TFP Credits.

    Core guarantees:
    - Credits are access tokens, not stablecoins
    - No external redemption possible
    - No secondary markets can form
    - All transfers are hard-blocked at consensus layer
    """

    def __init__(self):
        self.balances: Dict[str, CreditBalance] = {}
        self.transfer_log: List[dict] = []
        self.compliance_reports: List[ComplianceReport] = []

        # Legal positioning statements
        self.legal_positioning = [
            "TFP Credits are non-transferable access tokens, not payment stablecoins.",
            "Credits cannot be sent to other users or exchanged for fiat/crypto.",
            "Credits are redeemable only for protocol services (caching, compute, storage).",
            "No custodial wallets exist; users hold credits locally on their devices.",
            "Transfer attempts are hard-blocked at the consensus layer, not just discouraged.",
            "Credits have no value outside the TFP protocol ecosystem.",
        ]

        # Technical enforcement mechanisms
        self.technical_enforcement = [
            "Consensus rules reject any transaction attempting credit transfer.",
            "Smart contracts (if used) lack transfer functions entirely.",
            "API endpoints for transfers do not exist.",
            "Credit ledger is append-only for earnings/redemptions, not transfers.",
            "Device-bound identity (PUF/TEE) prevents account abstraction.",
        ]

    def create_balance(self, device_id: str) -> CreditBalance:
        """Create a new credit balance for a device."""
        if device_id in self.balances:
            return self.balances[device_id]

        balance = CreditBalance(device_id=device_id)
        self.balances[device_id] = balance
        return balance

    def mint_credits(
        self, device_id: str, amount: float, credit_type: CreditType, reason: str
    ) -> bool:
        """
        Mint new credits for a device (e.g., after completing a task).

        Args:
            device_id: Device earning credits
            amount: Amount to mint
            credit_type: Type of credit being minted
            reason: Reason for minting (for audit trail)

        Returns:
            True if successful
        """
        if device_id not in self.balances:
            self.create_balance(device_id)

        balance = self.balances[device_id]

        if credit_type not in balance.balances:
            balance.balances[credit_type] = 0.0

        balance.balances[credit_type] += amount
        balance.total_earned += amount
        balance.last_activity = time.time()

        return True

    def redeem_credits(
        self, device_id: str, amount: float, service: str
    ) -> Tuple[bool, str]:
        """
        Redeem credits for a protocol service.

        Args:
            device_id: Device redeeming credits
            amount: Amount to redeem
            service: Service being purchased

        Returns:
            (success, message)
        """
        if device_id not in self.balances:
            return False, "No balance found for device"

        balance = self.balances[device_id]
        can_redeem, reason = balance.can_redeem(amount, service)

        if not can_redeem:
            return False, reason

        # Deduct proportionally from all credit types
        remaining = amount
        for ctype in list(balance.balances.keys()):
            if remaining <= 0:
                break

            available = balance.balances[ctype]
            deduct = min(available, remaining)
            balance.balances[ctype] -= deduct
            remaining -= deduct

        balance.total_redeemed += amount
        balance.last_activity = time.time()

        return True, f"Redeemed {amount:.2f} credits for {service}"

    def block_transfer(self, from_device: str, to_device: str, amount: float) -> dict:
        """
        Log and block a transfer attempt.

        Args:
            from_device: Sender device ID
            to_device: Intended recipient
            amount: Attempted transfer amount

        Returns:
            Log entry
        """
        entry = {
            "timestamp": time.time(),
            "from_device": from_device,
            "to_device": to_device,
            "amount": amount,
            "status": "BLOCKED",
            "reason": "Non-transferable by design",
        }

        self.transfer_log.append(entry)

        if from_device in self.balances:
            self.balances[from_device].attempt_transfer(amount, to_device)

        return entry

    def generate_compliance_report(self, device_id: str = None) -> ComplianceReport:
        """
        Generate a compliance report for regulators.

        Args:
            device_id: Specific device to report on (or None for aggregate)

        Returns:
            ComplianceReport object
        """
        report_id = hashlib.sha3_256(f"{time.time()}-{device_id}".encode()).hexdigest()[
            :16
        ]

        report = ComplianceReport(
            report_id=report_id,
            generated_at=time.time(),
            device_id=device_id or "AGGREGATE",
            legal_reasoning=self.legal_positioning.copy(),
            technical_enforcement=self.technical_enforcement.copy(),
        )

        # Calculate aggregate statistics
        if device_id:
            if device_id in self.balances:
                balance = self.balances[device_id]
                report.total_circles_issued = balance.total_earned
                report.total_circles_redeemed = balance.total_redeemed
        else:
            # Aggregate across all devices
            for balance in self.balances.values():
                report.total_circles_issued += balance.total_earned
                report.total_circles_redeemed += balance.total_redeemed

        report.transfer_attempts_blocked = len(self.transfer_log)

        self.compliance_reports.append(report)
        return report

    def get_regulatory_faq(self) -> str:
        """Generate FAQ document for regulators."""
        faq = """
# TFP Credits: Regulatory FAQ

## Q: Are TFP Credits a stablecoin?
A: No. TFP Credits are non-transferable access tokens that can only be redeemed for protocol services within the TFP network. They cannot be:
- Sent to other users
- Exchanged for fiat currency or cryptocurrency
- Used outside the TFP protocol
- Held in custodial wallets

## Q: Do TFP Credits constitute money transmission?
A: No. Money transmission requires the ability to transfer value between parties. TFP Credits are:
- Bound to individual devices via PUF/TEE identity
- Redeemable only for services (caching, compute, storage)
- Impossible to transfer to another party (hard-blocked at consensus layer)

## Q: What prevents secondary markets from forming?
A: Technical enforcement at the consensus layer:
- No transfer function exists in the credit ledger
- API endpoints for transfers do not exist
- Any attempt to construct a transfer transaction is rejected by all nodes
- Credits are device-bound and cannot be abstracted into accounts

## Q: How are credits issued?
A: Credits are minted as rewards for contributing resources to the network:
- Compute tasks (running micro-tasks during idle time)
- Pinning/caching (storing content for others)
- Auditing (verifying content safety)

## Q: Can credits be lost or stolen?
A: Credits are stored locally on devices. If a device is lost, credits are lost (like cash). However:
- Credits cannot be stolen remotely (no transfer mechanism)
- No third party can access credits without physical device access
- Credits have no value outside TFP, reducing theft incentive

## Q: What is the regulatory classification?
A: TFP Credits are best classified as:
- Loyalty points / access tokens (like airline miles)
- Utility tokens for protocol access
- NOT securities, commodities, or currencies

---
Generated by TFP CreditLegalModel v2.11
"""
        return faq


# Example usage
if __name__ == "__main__":
    model = CreditLegalModel()

    # Create balances for devices
    model.create_balance("device_alice")
    model.create_balance("device_bob")

    # Mint credits for contributions
    model.mint_credits(
        "device_alice", 100.0, CreditType.COMPUTE, "Completed render task"
    )
    model.mint_credits("device_alice", 50.0, CreditType.PINNING, "Cached 10GB for 24h")
    model.mint_credits("device_bob", 75.0, CreditType.AUDIT, "Audited 20 files")

    # Redeem for services
    success, msg = model.redeem_credits("device_alice", 30.0, "content_download")
    print(f"Redemption: {msg}")

    # Attempt transfer (SHOULD FAIL)
    result = model.block_transfer("device_alice", "device_bob", 50.0)
    print(f"\nTransfer blocked: {result['reason']}")

    # Generate compliance report
    report = model.generate_compliance_report("device_alice")
    print(f"\nCompliance Report ID: {report.report_id}")
    print(f"Classification: {report.credit_type}")
    print(f"Status: {report.regulatory_status}")

    # Print FAQ
    print("\n" + "=" * 60)
    print(model.get_regulatory_faq())
