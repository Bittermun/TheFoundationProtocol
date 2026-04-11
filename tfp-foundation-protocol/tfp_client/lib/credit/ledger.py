import dataclasses
import hashlib
from typing import List

# Hard cap on total credits that may ever be minted across the network.
# Mirrors Bitcoin's scarcity model; enforced per-ledger and at the server level.
MAX_SUPPLY: int = 21_000_000


class SupplyCapError(Exception):
    """Raised when a mint would exceed the global MAX_SUPPLY."""


@dataclasses.dataclass
class Receipt:
    chain_hash: bytes
    credits: int


class CreditLedger:
    def __init__(
        self,
        chain: List[bytes] = None,
        balance: int = 0,
        total_minted: int = 0,
        network_total_minted: int = 0,
        max_supply: int = MAX_SUPPLY,
    ):
        self._chain: List[bytes] = list(chain) if chain else []
        self._balance: int = balance
        # Cumulative credits minted by *this* ledger (survives snapshots)
        self._total_minted: int = total_minted
        # Network-wide minted total (injected by server; used for cap enforcement)
        self._network_total_minted: int = network_total_minted
        self._max_supply: int = max_supply

    @classmethod
    def from_snapshot(
        cls,
        chain: List[bytes],
        balance: int,
        total_minted: int = 0,
        network_total_minted: int = 0,
        max_supply: int = MAX_SUPPLY,
    ) -> "CreditLedger":
        """Restore a ledger from a persisted chain + balance snapshot."""
        return cls(
            chain=chain,
            balance=balance,
            total_minted=total_minted,
            network_total_minted=network_total_minted,
            max_supply=max_supply,
        )

    def mint(self, credits: int, proof_hash: bytes) -> Receipt:
        if credits <= 0:
            raise ValueError("credits must be positive")
        projected = self._network_total_minted + credits
        if projected > self._max_supply:
            raise SupplyCapError(
                f"mint of {credits} would exceed supply cap "
                f"({self._network_total_minted}/{self._max_supply})"
            )
        prev = self._chain[-1] if self._chain else b"\x00" * 32
        block = hashlib.sha3_256(
            prev + proof_hash + credits.to_bytes(8, "big")
        ).digest()
        self._chain.append(block)
        self._balance += credits
        self._total_minted += credits
        self._network_total_minted += credits
        return Receipt(chain_hash=block, credits=credits)

    def set_network_total_minted(self, total: int) -> None:
        """Update the injected network total (called by server before mint)."""
        self._network_total_minted = total

    @property
    def total_minted(self) -> int:
        """Credits minted by this ledger instance."""
        return self._total_minted

    @property
    def network_total_minted(self) -> int:
        """Network-wide total minted (as last reported by server)."""
        return self._network_total_minted

    def spend(self, credits: int, receipt: Receipt) -> None:
        """Deduct `credits` from balance, authorised by an in-chain earn receipt.

        Raises:
            ValueError: if credits <= 0, the receipt is not in the chain,
                        or the balance is insufficient.
        """
        if credits <= 0:
            raise ValueError("credits must be positive")
        if not self.verify_spend(receipt):
            raise ValueError("invalid receipt: not in chain")
        if self._balance < credits:
            raise ValueError("insufficient balance")
        self._balance -= credits

    def verify_spend(self, receipt: Receipt) -> bool:
        return receipt.chain_hash in self._chain

    def export_merkle_root(self) -> bytes:
        """Build a binary Merkle tree over the chain blocks and return the root hash."""
        if not self._chain:
            return hashlib.sha3_256(b"").digest()
        nodes = list(self._chain)
        while len(nodes) > 1:
            next_level = []
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                right = nodes[i + 1] if i + 1 < len(nodes) else left
                next_level.append(hashlib.sha3_256(left + right).digest())
            nodes = next_level
        return nodes[0]

    def audit_trail(self) -> List[dict]:
        """Return the full chain as a list of {index, block_hash, hex} for remote auditing."""
        return [
            {"index": i, "block_hash": block, "hex": block.hex()}
            for i, block in enumerate(self._chain)
        ]

    @property
    def balance(self) -> int:
        return self._balance

    @property
    def chain(self) -> List[bytes]:
        return list(self._chain)
