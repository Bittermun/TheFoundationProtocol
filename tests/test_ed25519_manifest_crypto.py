# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import base64
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_core.governance.manifest import GovernanceManifest
from tfp_core.audit.artifact_signer import ArtifactSigner


class TestGovernanceManifestEd25519:
    """Test suite verifying genuine Ed25519 signing for GovernanceManifest."""

    def test_sign_and_verify_ed25519(self):
        manifest = GovernanceManifest()
        priv_key = ed25519.Ed25519PrivateKey.generate()
        sig_info = manifest.sign_manifest_ed25519(priv_key)

        assert sig_info["signature_algorithm"] == "Ed25519"
        assert len(sig_info["signature"]) == 128  # 64 bytes in hex
        assert len(sig_info["public_key"]) == 64  # 32 bytes in hex

        manifest_data = manifest.generate_manifest()
        manifest_data["signature_algorithm"] = "Ed25519"
        manifest_data["public_key"] = sig_info["public_key"]

        # Valid verification
        is_valid = manifest.verify_integrity(
            manifest_data,
            expected_signature=sig_info["signature"],
            public_key=sig_info["public_key"],
        )
        assert is_valid is True

    def test_ed25519_tampering_detected(self):
        manifest = GovernanceManifest()
        priv_key = ed25519.Ed25519PrivateKey.generate()
        sig_info = manifest.sign_manifest_ed25519(priv_key)

        manifest_data = manifest.generate_manifest()
        manifest_data["signature_algorithm"] = "Ed25519"
        manifest_data["public_key"] = sig_info["public_key"]

        # Tamper with manifest content
        manifest_data["maintainers"].append({"role": "Attacker", "name": "Eve"})

        is_valid = manifest.verify_integrity(
            manifest_data,
            expected_signature=sig_info["signature"],
            public_key=sig_info["public_key"],
        )
        assert is_valid is False

    def test_ed25519_wrong_key_rejected(self):
        manifest = GovernanceManifest()
        priv_key1 = ed25519.Ed25519PrivateKey.generate()
        priv_key2 = ed25519.Ed25519PrivateKey.generate()
        pub2_hex = priv_key2.public_key().public_bytes_raw().hex()

        sig_info = manifest.sign_manifest_ed25519(priv_key1)
        manifest_data = manifest.generate_manifest()

        is_valid = manifest.verify_integrity(
            manifest_data,
            expected_signature=sig_info["signature"],
            public_key=pub2_hex,
        )
        assert is_valid is False


class TestArtifactSignerEd25519:
    """Test suite verifying genuine Ed25519 artifact signing."""

    def test_sign_and_verify_artifact(self):
        signer = ArtifactSigner(mode="ed25519")
        data = b"CRITICAL_BINARY_PAYLOAD_V4_CORE"

        bundle = signer.sign(data)
        assert bundle is not None
        assert bundle["algorithm"] == "ed25519"
        assert bundle["mock"] is False
        assert "public_key" in bundle
        assert "signature" in bundle

        # Valid verification
        assert signer.verify(data, bundle) is True

    def test_artifact_tampering_rejected(self):
        signer = ArtifactSigner(mode="ed25519")
        data = b"ORIGINAL_DATA"
        bundle = signer.sign(data)

        # Alter binary payload
        tampered_data = b"MODIFIED_DATA"
        assert signer.verify(tampered_data, bundle) is False

    def test_corrupted_signature_rejected(self):
        signer = ArtifactSigner(mode="ed25519")
        data = b"DATA_TO_SIGN"
        bundle = signer.sign(data)

        # Corrupt signature string
        corrupt_sig = list(bundle["signature"])
        corrupt_sig[5] = "A" if corrupt_sig[5] != "A" else "B"
        corrupt_bundle = dict(bundle)
        corrupt_bundle["signature"] = "".join(corrupt_sig)

        assert signer.verify(data, corrupt_bundle) is False
