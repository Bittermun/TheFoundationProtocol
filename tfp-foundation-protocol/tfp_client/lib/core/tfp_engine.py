import hashlib

from ..ndn.adapter import NDNAdapter
from ..fountain.adapter import RaptorQAdapter
from ..zkp.adapter import ZKPAdapter
from ..lexicon.adapter import LexiconAdapter, Content
from ..credit.ledger import CreditLedger, Receipt
from ..security.symbolic_preprocessor.preprocessor import SymbolicPreprocessor
from ..identity.puf_enclave.enclave import PUFEnclave


class SecurityError(Exception):
    """Raised when a security gate rejects an operation."""


class TFPClient:
    def __init__(
        self,
        ndn=None,
        raptorq=None,
        zkp=None,
        lexicon=None,
        ledger=None,
        preprocessor=None,
        puf=None,
        puf_expected_seed: bytes = None,
    ):
        self.ndn = ndn or NDNAdapter()
        self.raptorq = raptorq or RaptorQAdapter()
        self.zkp = zkp or ZKPAdapter()
        self.lexicon = lexicon or LexiconAdapter()
        self.ledger = ledger or CreditLedger()
        self.preprocessor = preprocessor
        self.puf = puf
        self._puf_expected_seed = puf_expected_seed
        self._spends = []
        self._earned_receipts = []

    def request_content(self, root_hash: str, zkp_proof=None, recipe: dict = None) -> Content:
        # Security gate: validate recipe before any decode work
        if recipe is not None and self.preprocessor is not None:
            ok, _ = self.preprocessor.validate(recipe)
            if not ok:
                raise SecurityError("recipe validation failed")

        # Security gate: verify caller-supplied ZKP proof before fetching content
        if zkp_proof is not None:
            public_input = hashlib.sha3_256(root_hash.encode()).digest()
            if not self.zkp.verify_proof(zkp_proof, public_input):
                raise SecurityError("ZKP proof verification failed")

        interest = self.ndn.create_interest(root_hash)
        data = self.ndn.express_interest(interest)
        shards = [data.content]
        file_bytes = self.raptorq.decode(shards)
        content = self.lexicon.reconstruct(file_bytes)

        # Spend a previously-earned credit
        if not self._earned_receipts:
            raise ValueError("no earned credits to spend; call submit_compute_task first")
        earn_receipt = self._earned_receipts.pop(0)
        self.ledger.spend(1, earn_receipt)
        self._spends.append(earn_receipt)
        return content

    def submit_compute_task(self, task_recipe_hash: str) -> Receipt:
        # Security gate: verify PUF identity before minting credits
        if self.puf is not None:
            identity = self.puf.get_identity()
            expected_seed = (
                self._puf_expected_seed
                if self._puf_expected_seed is not None
                else self.puf.seed
            )
            if not PUFEnclave.verify_identity(identity, expected_seed):
                raise SecurityError("Sybil detection: PUF identity mismatch")

        proof_hash = hashlib.sha3_256(task_recipe_hash.encode()).digest()
        receipt = self.ledger.mint(10, proof_hash)
        self._earned_receipts.append(receipt)
        return receipt

    def prove_access(self, root_hash: str, private_claim: bytes) -> bytes:
        return self.zkp.generate_proof(circuit="access_to_hash", private=private_claim)
