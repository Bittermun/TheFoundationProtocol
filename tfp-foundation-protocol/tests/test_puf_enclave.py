import os

from tfp_client.lib.identity.puf_enclave.enclave import PUFEnclave, PUFIdentity


def test_get_identity_returns_puf_identity():
    enclave = PUFEnclave()
    identity = enclave.get_identity()
    assert isinstance(identity, PUFIdentity)
    assert hasattr(identity, "puf_entropy")
    assert hasattr(identity, "rf_fingerprint")
    assert hasattr(identity, "threshold_sig")


def test_puf_entropy_is_32_bytes():
    enclave = PUFEnclave()
    identity = enclave.get_identity()
    assert len(identity.puf_entropy) == 32


def test_rf_fingerprint_is_16_bytes():
    enclave = PUFEnclave()
    identity = enclave.get_identity()
    assert len(identity.rf_fingerprint) == 16


def test_threshold_sig_is_64_bytes():
    enclave = PUFEnclave()
    identity = enclave.get_identity()
    assert len(identity.threshold_sig) == 64


def test_sign_posi_proof_returns_bytes():
    enclave = PUFEnclave()
    sig = enclave.sign_posi_proof(b"test_proof_bytes")
    assert isinstance(sig, bytes)
    assert len(sig) > 0


def test_reject_replay_attack():
    enclave = PUFEnclave()
    proof = b"same_proof_data"
    sig1 = enclave.sign_posi_proof(proof)
    sig2 = enclave.sign_posi_proof(proof)
    assert sig1 != sig2  # nonce ensures different signatures


def test_sybil_rejection():
    seed = os.urandom(32)
    enclave = PUFEnclave(seed=seed)
    identity = enclave.get_identity()
    # Verify with correct seed — should pass
    assert PUFEnclave.verify_identity(identity, seed) is True
    # Verify with wrong seed — should fail
    wrong_seed = os.urandom(32)
    assert PUFEnclave.verify_identity(identity, wrong_seed) is False
