import hashlib

from ..ndn.adapter import NDNAdapter
from ..fountain.adapter import RaptorQAdapter
from ..zkp.adapter import ZKPAdapter
from ..lexicon.adapter import LexiconAdapter, Content
from ..credit.ledger import CreditLedger, Receipt


class TFPClient:
    def __init__(self, ndn=None, raptorq=None, zkp=None, lexicon=None, ledger=None):
        self.ndn = ndn or NDNAdapter()
        self.raptorq = raptorq or RaptorQAdapter()
        self.zkp = zkp or ZKPAdapter()
        self.lexicon = lexicon or LexiconAdapter()
        self.ledger = ledger or CreditLedger()
        self._spends = []

    def request_content(self, root_hash: str, zkp_proof=None) -> Content:
        interest = self.ndn.create_interest(root_hash)
        data = self.ndn.express_interest(interest)
        shards = [data.content]
        file_bytes = self.raptorq.decode(shards)
        content = self.lexicon.reconstruct(file_bytes)
        proof_hash = hashlib.sha3_256(root_hash.encode()).digest()
        receipt = self.ledger.mint(1, proof_hash)
        self._spends.append(receipt)
        return content

    def submit_compute_task(self, task_recipe_hash: str) -> Receipt:
        proof_hash = hashlib.sha3_256(task_recipe_hash.encode()).digest()
        receipt = self.ledger.mint(10, proof_hash)
        return receipt

    def prove_access(self, root_hash: str, private_claim: bytes) -> bytes:
        return self.zkp.generate_proof(circuit="access_to_hash", private=private_claim)
