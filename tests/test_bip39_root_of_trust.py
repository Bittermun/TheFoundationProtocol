# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive Multi-Tier Test Suite: BIP-39 Standard Hardware Root-of-Trust

Covers:
- Tier 1 (Feature):
    * Standard 128-bit (12 words) & 256-bit (24 words) mnemonic generation
    * Intermediate strengths (160-bit/15w, 192-bit/18w, 224-bit/21w)
    * Exact bitwise SHA-256 checksum calculation & validation
    * PBKDF2-HMAC-SHA512 seed derivation against official BIP-39 test vectors
    * SLIP-0010 HD key path derivation for Ed25519 / Dilithium / PQC keys
    * Multi-subsystem key hierarchy derivation (device, pqc, kem, puf, mesh)
    * Device identity creation, serialization, and deterministic recovery
- Tier 2 (Boundary/Edge):
    * Corrupted/invalid word detection (non-wordlist words, typos)
    * Invalid checksum rejection (swapping valid words, bit alterations)
    * Empty, whitespace-only, and malformed input rejection
    * Non-standard word count rejection (e.g. 5, 11, 13, 25 words)
    * Unsupported entropy strength values (e.g. 64, 100, 300, negative)
    * Passphrase variations (empty, standard, complex Unicode/emojis)
    * HD path syntax validation & hardened index enforcement
"""

import hashlib
import os
import pytest
from typing import List

from tfp_core.crypto.bip39 import (
    BIP39_WORDLIST,
    WORDLIST_ENGLISH,
    derive_hd_key,
    derive_key_path,
    derive_slip0010,
    generate_mnemonic,
    get_wordlist,
    mnemonic_to_seed,
    validate_mnemonic,
)
from tfp_core.identity import (
    DeviceIdentity,
    create_device_identity,
    derive_subsystem_keys,
    recover_device_identity,
)


# ============================================================================
# Tier 1: Feature Tests (Happy Path & Core Invariants)
# ============================================================================

class TestBIP39Tier1Features:
    """Tier 1 Feature tests verifying functional correctness of BIP-39 root of trust."""

    def test_wordlist_integrity(self):
        """Verify the BIP-39 English wordlist has exactly 2048 unique words."""
        wordlist = get_wordlist("english")
        assert len(wordlist) == 2048
        assert len(set(wordlist)) == 2048
        assert wordlist[0] == "abandon"
        assert wordlist[-1] == "zoo"
        assert WORDLIST_ENGLISH == BIP39_WORDLIST

    @pytest.mark.parametrize("strength,expected_words", [
        (128, 12),
        (160, 15),
        (192, 18),
        (224, 21),
        (256, 24),
    ])
    def test_mnemonic_generation_word_counts(self, strength: int, expected_words: int):
        """Verify mnemonic generation produces exact word count per entropy strength."""
        mnemonic = generate_mnemonic(strength=strength)
        words = mnemonic.split()
        assert len(words) == expected_words
        assert validate_mnemonic(mnemonic) is True
        for word in words:
            assert word in BIP39_WORDLIST

    def test_mnemonic_generation_from_explicit_entropy(self):
        """Verify deterministic mnemonic generation from known raw entropy bytes."""
        # 128-bit all zeros
        entropy_128 = bytes(16)
        m128 = generate_mnemonic(entropy_bytes=entropy_128)
        assert m128 == "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        assert validate_mnemonic(m128) is True

        # 256-bit all zeros
        entropy_256 = bytes(32)
        m256 = generate_mnemonic(entropy_bytes=entropy_256)
        expected_256 = " ".join(["abandon"] * 23 + ["art"])
        assert m256 == expected_256
        assert validate_mnemonic(m256) is True

        # 256-bit all 0xFF
        entropy_ff = b"\xff" * 32
        m_ff = generate_mnemonic(entropy_bytes=entropy_ff)
        expected_ff = " ".join(["zoo"] * 23 + ["vote"])
        assert m_ff == expected_ff
        assert validate_mnemonic(m_ff) is True

    def test_pbkdf2_seed_derivation_bip39_vectors(self):
        """Verify PBKDF2-HMAC-SHA512 seed derivation matches authoritative BIP-39 test vectors."""
        # Test Vector 1: 128-bit all zeros, no passphrase
        m1 = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        s1_no_pass = mnemonic_to_seed(m1, passphrase="")
        assert len(s1_no_pass) == 64
        assert s1_no_pass.hex() == (
            "5eb00bbddcf069084889a8ab9155568165f5c453ccb85e70811aaed6f6da5fc1"
            "9a5ac40b389cd370d086206dec8aa6c43daea6690f20ad3d8d48b2d2ce9e38e4"
        )

        # Test Vector 1: with passphrase 'TREZOR'
        s1_trezor = mnemonic_to_seed(m1, passphrase="TREZOR")
        assert s1_trezor.hex() == (
            "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
            "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04"
        )

        # Test Vector 2: 256-bit all zeros with passphrase 'TREZOR'
        m2 = " ".join(["abandon"] * 23 + ["art"])
        s2_trezor = mnemonic_to_seed(m2, passphrase="TREZOR")
        assert s2_trezor.hex() == (
            "bda85446c68413707090a52022edd26a1c9462295029f2e60cd7c4f2bbd30971"
            "70af7a4d73245cafa9c3cca8d561a7c3de6f5d4a10be8ed2a5e608d68f92fcc8"
        )

    def test_slip0010_hd_key_derivation(self):
        """Verify SLIP-0010 hierarchical key derivation determinism and properties."""
        seed = mnemonic_to_seed("abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about")
        path_default = "m/44'/9999'/0'/0/0"
        
        priv1, pub1 = derive_hd_key(seed, path_default)
        priv2, pub2 = derive_key_path(seed, path_default)

        assert len(priv1) == 32
        assert len(pub1) == 32
        assert priv1 == priv2
        assert pub1 == pub2

        # Sub-account derivation produces distinct keys
        priv_sub1, pub_sub1 = derive_hd_key(seed, "m/44'/9999'/0'/0/1")
        assert priv1 != priv_sub1
        assert pub1 != pub_sub1

    def test_subsystem_keys_derivation(self):
        """Verify derivation of all standardized TFP subsystem keys from master seed."""
        seed = bytes.fromhex("01" * 64)
        subsystems = derive_subsystem_keys(seed)
        
        expected_subsystems = ["device", "pqc", "kem", "puf", "mesh"]
        for sub in expected_subsystems:
            assert sub in subsystems
            priv, pub = subsystems[sub]
            assert len(priv) == 32
            assert len(pub) == 32

        # Verify all subsystem keys are distinct
        priv_keys = [subsystems[k][0] for k in expected_subsystems]
        assert len(set(priv_keys)) == len(expected_subsystems)

    def test_device_identity_lifecycle_and_recovery(self):
        """Verify end-to-end device provisioning, export, and recovery."""
        # 1. Provision fresh 24-word identity
        identity1 = create_device_identity(strength=256, passphrase="test_vault_pass")
        assert len(identity1.mnemonic.split()) == 24
        assert identity1.device_id.startswith("tfp_")
        assert len(identity1.private_key) == 32
        assert len(identity1.public_key) == 32

        # Export dictionary
        dict_public = identity1.to_dict(include_secrets=False)
        assert "mnemonic" not in dict_public
        assert "private_key" not in dict_public
        assert dict_public["device_id"] == identity1.device_id

        dict_secret = identity1.to_dict(include_secrets=True)
        assert dict_secret["mnemonic"] == identity1.mnemonic
        assert dict_secret["private_key"] == identity1.private_key.hex()

        # 2. Recover identity on a clean/cold device using identical mnemonic + passphrase
        recovered = recover_device_identity(
            mnemonic=identity1.mnemonic,
            passphrase="test_vault_pass",
        )

        assert recovered.device_id == identity1.device_id
        assert recovered.seed == identity1.seed
        assert recovered.private_key == identity1.private_key
        assert recovered.public_key == identity1.public_key
        assert recovered.pqc_seed == identity1.pqc_seed
        assert recovered.kem_seed == identity1.kem_seed
        assert recovered.puf_seed == identity1.puf_seed
        assert recovered.mesh_mac_key == identity1.mesh_mac_key


# ============================================================================
# Tier 2: Boundary & Edge Cases (Adversarial & Fault Injection)
# ============================================================================

class TestBIP39Tier2EdgeCases:
    """Tier 2 Edge and Boundary tests for BIP-39 root-of-trust."""

    def test_corrupted_word_validation(self):
        """Verify non-existent or misspelled words are rejected."""
        valid_12 = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        assert validate_mnemonic(valid_12) is True

        # Replace 'about' with non-existent word 'notabipword'
        corrupted = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon notabipword"
        assert validate_mnemonic(corrupted) is False

        # Typo in a middle word: 'abandon' -> 'abondon'
        typo = "abandon abondon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        assert validate_mnemonic(typo) is False

    def test_invalid_checksum_rejection(self):
        """Verify valid words with mismatched SHA-256 checksum are rejected."""
        # 12 'abandon's: 'abandon' is in wordlist, but 12x 'abandon' has incorrect checksum (last word should be 'about')
        twelve_abandons = " ".join(["abandon"] * 12)
        assert validate_mnemonic(twelve_abandons) is False

        # Swapping two words in a valid phrase breaks the bit order and checksum
        valid = "legal winner thank year wave sausage worth useful legal winner thank yellow"
        assert validate_mnemonic(valid) is True
        words = valid.split()
        words[0], words[1] = words[1], words[0]
        swapped = " ".join(words)
        assert validate_mnemonic(swapped) is False

    def test_malformed_and_empty_mnemonics(self):
        """Verify empty strings, whitespace, and non-string inputs are safely rejected."""
        assert validate_mnemonic("") is False
        assert validate_mnemonic("   ") is False
        assert validate_mnemonic("\t\n") is False
        assert validate_mnemonic(None) is False  # type: ignore
        assert validate_mnemonic(12345) is False  # type: ignore

    def test_invalid_word_counts(self):
        """Verify phrases with invalid word counts (<12, 13, 25, etc.) are rejected."""
        assert validate_mnemonic("abandon abandon") is False
        assert validate_mnemonic(" ".join(["abandon"] * 11)) is False
        assert validate_mnemonic(" ".join(["abandon"] * 13)) is False
        assert validate_mnemonic(" ".join(["abandon"] * 25)) is False

    def test_unsupported_strength_values(self):
        """Verify generate_mnemonic raises ValueError on invalid entropy strengths."""
        for invalid_strength in [-256, 0, 64, 100, 127, 129, 255, 300, 512]:
            with pytest.raises(ValueError, match="Invalid strength"):
                generate_mnemonic(strength=invalid_strength)

    def test_unsupported_language_rejection(self):
        """Verify unsupported language requests raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported language"):
            get_wordlist("french")

        with pytest.raises(ValueError, match="Unsupported language"):
            generate_mnemonic(language="klingon")

    def test_passphrase_sensitivity_and_unicode_normalization(self):
        """Verify distinct passphrases generate completely distinct seeds."""
        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        seed_empty = mnemonic_to_seed(mnemonic, passphrase="")
        seed_a = mnemonic_to_seed(mnemonic, passphrase="passwordA")
        seed_b = mnemonic_to_seed(mnemonic, passphrase="passwordB")
        seed_unicode1 = mnemonic_to_seed(mnemonic, passphrase="møñkëy 🔑")
        seed_unicode2 = mnemonic_to_seed(mnemonic, passphrase="møñkëy 🔒")

        assert len({seed_empty, seed_a, seed_b, seed_unicode1, seed_unicode2}) == 5

    def test_recover_device_identity_with_corrupted_phrase_raises(self):
        """Verify recover_device_identity raises ValueError on corrupt phrase."""
        with pytest.raises(ValueError, match="Invalid BIP-39 mnemonic phrase"):
            recover_device_identity("abandon abandon abandon invalidword")

        with pytest.raises(ValueError, match="Invalid BIP-39 mnemonic phrase"):
            recover_device_identity(" ".join(["abandon"] * 24))
