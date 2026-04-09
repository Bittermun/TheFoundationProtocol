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

    def verify_spend(self, receipt: Receipt) -> bool:
        return receipt.chain_hash in self._chain

    @property
    def balance(self) -> int:
        return self._balance

    @property
    def chain(self) -> List[bytes]:
        return list(self._chain)
