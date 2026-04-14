# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hybrid Wallet - Dual-balance wallet (compute + pinning credits)

Implements the hybrid economic model for Bridge 3:
- 50% compute/PoSI credits (from proof-of-compute)
- 50% archival pinning credits (from DWCC rewards)

Wallets track both credit types separately and allow combined spending.
"""

import dataclasses
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .dwcc_calculator import DWCCCalculator, SemanticValueTier
from .ledger import CreditLedger, Receipt


@dataclasses.dataclass
class WalletBalance:
    """Dual-balance tracking for a wallet."""

    compute_credits: float = 0.0
    pinning_credits: float = 0.0

    def total(self) -> float:
        """Get total combined credits."""
        return self.compute_credits + self.pinning_credits

    def to_dict(self) -> Dict[str, float]:
        """Serialize to dictionary."""
        return {
            "compute_credits": self.compute_credits,
            "pinning_credits": self.pinning_credits,
            "total": self.total(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "WalletBalance":
        """Deserialize from dictionary."""
        return cls(
            compute_credits=data.get("compute_credits", 0.0),
            pinning_credits=data.get("pinning_credits", 0.0),
        )


@dataclasses.dataclass
class TransactionRecord:
    """Record of a credit transaction."""

    tx_id: str
    timestamp: float
    tx_type: str  # 'mint_compute', 'mint_pinning', 'spend', 'transfer'
    amount: float
    credit_type: str  # 'compute', 'pinning', 'mixed'
    balance_after: WalletBalance
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "tx_id": self.tx_id,
            "timestamp": self.timestamp,
            "tx_type": self.tx_type,
            "amount": self.amount,
            "credit_type": self.credit_type,
            "balance_after": self.balance_after.to_dict(),
            "metadata": self.metadata,
        }


class HybridWallet:
    """
    Hybrid wallet managing both compute and pinning credits.

    Implements the 50/50 economic model:
    - Compute credits earned via PoSI/compute proofs
    - Pinning credits earned via DWCC archival rewards

    Both credit types can be spent, but pinning credits may have
    restrictions on what they can purchase (e.g., only storage).
    """

    def __init__(self, wallet_id: str):
        """
        Initialize hybrid wallet.

        Args:
            wallet_id: Unique identifier for this wallet
        """
        self.wallet_id = wallet_id
        self._compute_ledger = CreditLedger()
        self._pinning_balance: float = 0.0
        self._transactions: list[TransactionRecord] = []
        self._dwcc_tracker = DWCCCalculator()

    def mint_compute_credits(self, credits: int, proof_hash: bytes) -> Receipt:
        """
        Mint compute credits from proof-of-compute.

        Args:
            credits: Amount to mint
            proof_hash: Hash of compute proof

        Returns:
            Receipt for the minting operation
        """
        receipt = self._compute_ledger.mint(credits, proof_hash)

        # Record transaction
        self._record_transaction(
            tx_type="mint_compute",
            amount=float(credits),
            credit_type="compute",
            metadata={"proof_hash": proof_hash.hex()},
        )

        return receipt

    def mint_pinning_credits(self, dwcc_rewards: Dict[str, float]) -> float:
        """
        Mint pinning credits from DWCC rewards.

        Args:
            dwcc_rewards: Dict mapping content_hash → reward amount

        Returns:
            Total pinning credits minted
        """
        total = sum(dwcc_rewards.values())

        if total > 0:
            self._pinning_balance += total

            self._record_transaction(
                tx_type="mint_pinning",
                amount=total,
                credit_type="pinning",
                metadata={"rewards": dwcc_rewards},
            )

        return total

    def spend(
        self,
        amount: float,
        credit_type: str = "mixed",
        receipt: Optional[Receipt] = None,
    ) -> bool:
        """
        Spend credits from the wallet.

        Args:
            amount: Amount to spend
            credit_type: 'compute', 'pinning', or 'mixed'
            receipt: Optional receipt for compute credit authorization

        Returns:
            True if spend succeeded

        Raises:
            ValueError: If insufficient balance or invalid parameters
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        if credit_type == "compute":
            if receipt is None:
                raise ValueError("Receipt required for compute credit spend")
            self._compute_ledger.spend(int(amount), receipt)
        elif credit_type == "pinning":
            if self._pinning_balance < amount:
                raise ValueError("Insufficient pinning credits")
            self._pinning_balance -= amount
        elif credit_type == "mixed":
            # Try to spend from compute first, then pinning
            compute_available = self._compute_ledger.balance
            if compute_available >= amount:
                # Need a receipt for full amount
                if receipt:
                    self._compute_ledger.spend(int(amount), receipt)
                else:
                    # Fall back to pinning if no receipt
                    if self._pinning_balance < amount:
                        raise ValueError("Insufficient mixed credits")
                    self._pinning_balance -= amount
            else:
                # Spend all compute, rest from pinning
                if receipt:
                    self._compute_ledger.spend(compute_available, receipt)
                remaining = amount - compute_available
                if self._pinning_balance < remaining:
                    raise ValueError("Insufficient mixed credits")
                self._pinning_balance -= remaining
        else:
            raise ValueError(f"Invalid credit type: {credit_type}")

        self._record_transaction(
            tx_type="spend",
            amount=amount,
            credit_type=credit_type,
            metadata={"receipt_present": receipt is not None},
        )

        return True

    def transfer(
        self, recipient_id: str, amount: float, credit_type: str = "mixed"
    ) -> Tuple["HybridWallet", TransactionRecord]:
        """
        Transfer credits to another wallet.

        Note: In production, this would require cryptographic signatures
        and blockchain-style consensus. This is a simplified simulation.

        Args:
            recipient_id: ID of recipient wallet
            amount: Amount to transfer
            credit_type: Type of credits to transfer

        Returns:
            Tuple of (new_recipient_wallet, transaction_record)
        """
        # Spend from this wallet
        self.spend(amount, credit_type)

        # Create recipient wallet with transferred amount
        recipient = HybridWallet(recipient_id)

        if credit_type in ("compute", "mixed"):
            # Simulate compute credit transfer
            fake_proof = hashlib.sha3_256(f"transfer_{amount}".encode()).digest()
            recipient.mint_compute_credits(int(amount * 0.5), fake_proof)

        if credit_type in ("pinning", "mixed"):
            # Simulate pinning credit transfer
            recipient._pinning_balance += amount * 0.5

        return recipient

    def get_balance(self) -> WalletBalance:
        """Get current wallet balance."""
        return WalletBalance(
            compute_credits=float(self._compute_ledger.balance),
            pinning_credits=self._pinning_balance,
        )

    def track_content_request(
        self, content_hash: str, semantic_tier: Optional[SemanticValueTier] = None
    ) -> None:
        """
        Track a content request for DWCC calculation.

        Args:
            content_hash: Hash of requested content
            semantic_tier: Optional semantic importance
        """
        self._dwcc_tracker.track_request(content_hash, semantic_tier)

    def process_dwcc_epoch(self, epoch_hours: float = 1.0) -> float:
        """
        Process DWCC epoch and mint pinning credits.

        Args:
            epoch_hours: Duration of epoch

        Returns:
            Total pinning credits minted
        """
        rewards = self._dwcc_tracker.process_epoch(epoch_hours)
        return self.mint_pinning_credits(rewards)

    def _record_transaction(
        self,
        tx_type: str,
        amount: float,
        credit_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a transaction."""
        tx_id = hashlib.sha3_256(
            f"{self.wallet_id}_{datetime.now(timezone.utc).timestamp()}_{tx_type}_{amount}".encode()
        ).hexdigest()[:16]

        record = TransactionRecord(
            tx_id=tx_id,
            timestamp=datetime.now(timezone.utc).timestamp(),
            tx_type=tx_type,
            amount=amount,
            credit_type=credit_type,
            balance_after=self.get_balance(),
            metadata=metadata or {},
        )

        self._transactions.append(record)

    def get_transaction_history(self, limit: int = 100) -> list[dict]:
        """Get recent transaction history."""
        return [tx.to_dict() for tx in self._transactions[-limit:]]

    def get_statistics(self) -> Dict[str, Any]:
        """Get wallet statistics."""
        balance = self.get_balance()
        return {
            "wallet_id": self.wallet_id,
            "balance": balance.to_dict(),
            "transaction_count": len(self._transactions),
            "dwcc_stats": self._dwcc_tracker.get_statistics(),
        }
