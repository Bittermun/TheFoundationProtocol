import hashlib

from ..compute.task_executor import (
    ExecutionResult,
    TaskExecutionError,
    TaskSpec,
    execute_task,
)
from ..credit.ledger import CreditLedger, Receipt, SupplyCapError
from ..fountain.adapter import RaptorQAdapter
from ..identity.puf_enclave.enclave import PUFEnclave
from ..lexicon.adapter import Content, LexiconAdapter
from ..ndn.adapter import NDNAdapter
from ..zkp.adapter import ZKPAdapter


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

    def request_content(
        self, root_hash: str, zkp_proof=None, recipe: dict = None
    ) -> Content:
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
            raise ValueError(
                "no earned credits to spend; call submit_compute_task first"
            )
        earn_receipt = self._earned_receipts.pop(0)
        self.ledger.spend(1, earn_receipt)
        self._spends.append(earn_receipt)
        return content

    def submit_compute_task(self, task_recipe_hash: str) -> Receipt:
        """
        Mint credits for completing a compute task identified by its recipe hash.

        The caller is responsible for ensuring the task was actually executed and
        the result verified (e.g. via HABP consensus on the server side) before
        calling this method. The task_recipe_hash must be the SHA3-256 hex of the
        verified execution result so the proof is bound to real work.
        """
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
        try:
            receipt = self.ledger.mint(10, proof_hash)
        except SupplyCapError as exc:
            raise SecurityError(f"supply cap reached: {exc}") from exc
        self._earned_receipts.append(receipt)
        return receipt

    def execute_and_earn(
        self,
        spec: TaskSpec,
        credits: int = 10,
        timeout_s: float = 30.0,
    ) -> tuple[ExecutionResult, Receipt]:
        """
        Execute a real compute task, verify the result locally, then mint credits.

        This is the full proof-of-compute path:
          1. Execute the task (real computation)
          2. Verify result matches expected_output_hash
          3. Mint credits bound to the verified output hash

        Returns (ExecutionResult, Receipt).
        Raises TaskExecutionError if execution fails or result is wrong.
        Raises SecurityError if PUF check or supply cap fails.
        """
        result = execute_task(spec, timeout_s=timeout_s)
        if not result.verified_locally:
            raise TaskExecutionError(
                f"local verification failed for task {spec.task_id}: "
                f"got {result.output_hash}, expected {spec.expected_output_hash}"
            )

        # Security gate: verify PUF identity before minting
        if self.puf is not None:
            identity = self.puf.get_identity()
            expected_seed = (
                self._puf_expected_seed
                if self._puf_expected_seed is not None
                else self.puf.seed
            )
            if not PUFEnclave.verify_identity(identity, expected_seed):
                raise SecurityError("Sybil detection: PUF identity mismatch")

        # Proof hash = SHA3-256(task_id + output_hash): binds credit to real work
        proof_material = f"{spec.task_id}:{result.output_hash}".encode()
        proof_hash = hashlib.sha3_256(proof_material).digest()
        try:
            receipt = self.ledger.mint(credits, proof_hash)
        except SupplyCapError as exc:
            raise SecurityError(f"supply cap reached: {exc}") from exc
        self._earned_receipts.append(receipt)
        return result, receipt

    def prove_access(self, root_hash: str, private_claim: bytes) -> bytes:
        return self.zkp.generate_proof(circuit="access_to_hash", private=private_claim)
