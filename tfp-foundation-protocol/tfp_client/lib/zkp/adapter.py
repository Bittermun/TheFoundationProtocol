import hashlib
import os


class ZKPAdapter:
    """Mock ZKP adapter — swap for mopro/EZKL bindings."""

    def generate_proof(self, circuit: str, private: bytes) -> bytes:
        nonce = os.urandom(16)
        return hashlib.sha3_256(private + nonce + circuit.encode()).digest()

    def verify_proof(self, proof: bytes, public_input: bytes) -> bool:
        return len(proof) == 32
