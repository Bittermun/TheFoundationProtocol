import hashlib
import os
import hmac
import dataclasses


@dataclasses.dataclass
class PUFIdentity:
    puf_entropy: bytes    # 32 bytes
    rf_fingerprint: bytes  # 16 bytes
    threshold_sig: bytes   # 64 bytes


class PUFEnclave:
    def __init__(self, seed: bytes = None):
        self._seed = seed or os.urandom(32)

    def get_identity(self) -> PUFIdentity:
        puf_entropy = hashlib.sha3_256(self._seed + b"puf").digest()      # 32 bytes
        rf_fingerprint = hashlib.md5(self._seed + b"rf").digest()          # 16 bytes
        threshold_sig = hashlib.sha3_512(self._seed + b"threshold").digest()  # 64 bytes
        return PUFIdentity(
            puf_entropy=puf_entropy,
            rf_fingerprint=rf_fingerprint,
            threshold_sig=threshold_sig,
        )

    def sign_posi_proof(self, proof: bytes) -> bytes:
        nonce = os.urandom(16)
        sig = hmac.new(self._seed, proof + nonce, hashlib.sha3_256).digest()
        return sig + nonce

    @staticmethod
    def verify_identity(identity: PUFIdentity, expected_seed: bytes) -> bool:
        expected = hashlib.sha3_256(expected_seed + b"puf").digest()
        return hmac.compare_digest(identity.puf_entropy, expected)
