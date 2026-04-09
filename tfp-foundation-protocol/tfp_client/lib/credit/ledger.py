import hashlib
import dataclasses
from typing import List


@dataclasses.dataclass
class Receipt:
    chain_hash: bytes
    credits: int


class CreditLedger:
    def __init__(self):
        self._chain: List[bytes] = []
        self._balance: int = 0

    def mint(self, credits: int, proof_hash: bytes) -> Receipt:
        if credits <= 0:
            raise ValueError("credits must be positive")
        prev = self._chain[-1] if self._chain else b'\x00' * 32
        block = hashlib.sha3_256(prev + proof_hash + credits.to_bytes(8, 'big')).digest()
        self._chain.append(block)
        self._balance += credits
        return Receipt(chain_hash=block, credits=credits)

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
            return hashlib.sha3_256(b'').digest()
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
