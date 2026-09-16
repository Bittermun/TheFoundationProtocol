# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Hybrid Wallet - Dual-balance wallet (compute + pinning credits)

Implements the hybrid economic model for Bridge 3:
- 50% compute/PoSI credits (from proof-of-compute)
- 50% archival pinning credits (from DWCC rewards)

Wallets track both credit types separately and allow combined spending.
"""

import copy
import dataclasses
import hashlib
import math
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
        self._compute_receipts: list[Receipt] = []
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
        self._compute_receipts.append(receipt)

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
            dwcc_rewards: Dict mapping content_hash â†’ reward amount

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
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Amount must be positive and finite")

        compute_debit = 0
        pinning_debit = 0.0
        if credit_type == "compute":
            if receipt is None:
                raise ValueError("Receipt required for compute credit spend")
            if amount != int(amount):
                raise ValueError("Compute credits must be whole units")
            compute_debit = int(amount)
        elif credit_type == "pinning":
            pinning_debit = amount
        elif credit_type == "mixed":
            # Without a receipt, only pinning credits are authorized.
            if receipt is not None:
                compute_debit = min(self._compute_ledger.balance, int(amount))
            pinning_debit = amount - compute_debit
        else:
            raise ValueError(f"Invalid credit type: {credit_type}")

        if self._pinning_balance < pinning_debit:
            raise ValueError(f"Insufficient {credit_type} credits")
        # Validate and spend on detached state. A failed receipt or insufficient
        # balance must leave both source balances unchanged.
        ledger = copy.deepcopy(self._compute_ledger)
        change = None
        if compute_debit:
            change = ledger.spend_with_change(compute_debit, receipt)
        self._compute_ledger = ledger
        self._compute_receipts = [r for r in self._compute_receipts if ledger.verify_spend(r)]
        if change is not None:
            self._compute_receipts.append(change)
        self._pinning_balance -= pinning_debit

        self._record_transaction(
            tx_type="spend",
            amount=amount,
            credit_type=credit_type,
            metadata={"receipt_present": receipt is not None},
        )

        return True

    def transfer(
        self, recipient_id: str, amount: float, credit_type: str = "mixed",
        receipt: Optional[Receipt] = None,
    ) -> Tuple["HybridWallet", TransactionRecord]:
        """Simulate a local transfer and return the recipient and sender record.

        Compute spending requires a valid receipt. Each credited balance equals
        the corresponding source debit; no conversion or new value is created.
        This creates a new wallet, not a durable transfer to an existing peer.
        It does not provide signatures or distributed consensus.
        """
        if not recipient_id or recipient_id == self.wallet_id:
            raise ValueError("Recipient must identify a different wallet")
        staged = copy.deepcopy(self)
        before = staged.get_balance()
        staged.spend(amount, credit_type, receipt)
        after = staged.get_balance()
        recipient = HybridWallet(recipient_id)
        compute_amount = int(before.compute_credits - after.compute_credits)
        pinning_amount = before.pinning_credits - after.pinning_credits
        if compute_amount:
            simulation_proof = hashlib.sha3_256(
                f"local-transfer:{self.wallet_id}:{recipient_id}:{compute_amount}".encode()
            ).digest()
            recipient.mint_compute_credits(compute_amount, simulation_proof)
        if pinning_amount:
            recipient.mint_pinning_credits({"local-transfer": pinning_amount})
        staged._record_transaction(
            tx_type="transfer", amount=amount, credit_type=credit_type,
            metadata={"recipient_id": recipient_id, "local_simulation": True},
        )
        self._compute_ledger = staged._compute_ledger
        self._compute_receipts = staged._compute_receipts
        self._pinning_balance = staged._pinning_balance
        self._transactions = staged._transactions
        return recipient, self._transactions[-1]

    def get_compute_receipts(self) -> list[Receipt]:
        """Return usable local authorizations, including partial-spend change."""
        return [r for r in self._compute_receipts if self._compute_ledger.verify_spend(r)]

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
