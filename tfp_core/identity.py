# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Standard Device Identity & Hardware Root-of-Trust

Integrates standardized BIP-39 mnemonic generation, checksum validation,
PBKDF2 seed derivation, and SLIP-0010 multi-subsystem HD key derivation.
"""

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any, Dict, Optional, Tuple

from tfp_core.crypto.bip39 import (
    derive_hd_key,
    generate_mnemonic,
    mnemonic_to_seed,
    validate_mnemonic,
)


@dataclass
class DeviceIdentity:
    """Canonical device identity anchored in a BIP-39 hardware root-of-trust."""

    device_id: str
    mnemonic: str
    seed: bytes
    private_key: bytes
    public_key: bytes
    hd_path: str = "m/44'/9999'/0'/0/0"
    pqc_seed: bytes = field(default_factory=bytes)
    kem_seed: bytes = field(default_factory=bytes)
    puf_seed: bytes = field(default_factory=bytes)
    mesh_mac_key: bytes = field(default_factory=bytes)
    created_at: float = field(default_factory=time.time)

    def to_dict(self, include_secrets: bool = False) -> Dict[str, Any]:
        """Convert identity to dictionary representation."""
        data: Dict[str, Any] = {
            "device_id": self.device_id,
            "public_key": self.public_key.hex(),
            "hd_path": self.hd_path,
            "created_at": self.created_at,
        }
        if include_secrets:
            data.update({
                "mnemonic": self.mnemonic,
                "seed": self.seed.hex(),
                "private_key": self.private_key.hex(),
                "pqc_seed": self.pqc_seed.hex(),
                "kem_seed": self.kem_seed.hex(),
                "puf_seed": self.puf_seed.hex(),
                "mesh_mac_key": self.mesh_mac_key.hex(),
            })
        return data


def derive_subsystem_keys(seed: bytes) -> Dict[str, Tuple[bytes, bytes]]:
    """
    Derive all standardized subsystem keys from master seed via SLIP-0010:
    - Master / Device Identity: m/44'/9999'/0'/0/0
    - PQC Dilithium Root Key:   m/44'/9999'/0'/1/0
    - Key Encapsulation KEM:    m/44'/9999'/0'/2/0
    - PUF Hardware Enclave:     m/44'/9999'/0'/3/0
    - Mesh Hop Transport MAC:   m/44'/9999'/0'/4/0
    """
    paths = {
        "device": "m/44'/9999'/0'/0/0",
        "pqc": "m/44'/9999'/0'/1/0",
        "kem": "m/44'/9999'/0'/2/0",
        "puf": "m/44'/9999'/0'/3/0",
        "mesh": "m/44'/9999'/0'/4/0",
    }
    keys = {}
    for name, path in paths.items():
        keys[name] = derive_hd_key(seed, path)
    return keys


def create_device_identity(
    device_id: Optional[str] = None,
    strength: int = 256,
    passphrase: str = "",
) -> DeviceIdentity:
    """
    Provision a new device identity anchored in a BIP-39 root-of-trust.

    Args:
        device_id: Optional explicit device ID string (defaults to tfp_pubkey_hash).
        strength: Entropy strength (128 for 12 words, 256 for 24 words).
        passphrase: Optional BIP-39 passphrase salt extension.

    Returns:
        DeviceIdentity instance with full subsystem keys.
    """
    mnemonic = generate_mnemonic(strength=strength)
    seed = mnemonic_to_seed(mnemonic, passphrase=passphrase)
    subsystems = derive_subsystem_keys(seed)

    dev_priv, dev_pub = subsystems["device"]
    pqc_priv, _ = subsystems["pqc"]
    kem_priv, _ = subsystems["kem"]
    puf_priv, _ = subsystems["puf"]
    mesh_priv, _ = subsystems["mesh"]

    if device_id is None:
        device_id = f"tfp_{hashlib.sha256(dev_pub).hexdigest()[:16]}"

    return DeviceIdentity(
        device_id=device_id,
        mnemonic=mnemonic,
        seed=seed,
        private_key=dev_priv,
        public_key=dev_pub,
        hd_path="m/44'/9999'/0'/0/0",
        pqc_seed=pqc_priv,
        kem_seed=kem_priv,
        puf_seed=puf_priv,
        mesh_mac_key=mesh_priv,
    )


def recover_device_identity(
    mnemonic: str,
    device_id: Optional[str] = None,
    passphrase: str = "",
) -> DeviceIdentity:
    """
    Recover a device identity from an existing BIP-39 mnemonic phrase.

    Args:
        mnemonic: BIP-39 mnemonic phrase (12 or 24 words).
        device_id: Optional explicit device ID string.
        passphrase: Optional BIP-39 passphrase salt.

    Returns:
        DeviceIdentity instance.

    Raises:
        ValueError: If mnemonic is invalid or checksum fails.
    """
    if not validate_mnemonic(mnemonic):
        raise ValueError("Invalid BIP-39 mnemonic phrase or checksum failure")

    seed = mnemonic_to_seed(mnemonic, passphrase=passphrase)
    subsystems = derive_subsystem_keys(seed)

    dev_priv, dev_pub = subsystems["device"]
    pqc_priv, _ = subsystems["pqc"]
    kem_priv, _ = subsystems["kem"]
    puf_priv, _ = subsystems["puf"]
    mesh_priv, _ = subsystems["mesh"]

    if device_id is None:
        device_id = f"tfp_{hashlib.sha256(dev_pub).hexdigest()[:16]}"

    return DeviceIdentity(
        device_id=device_id,
        mnemonic=mnemonic,
        seed=seed,
        private_key=dev_priv,
        public_key=dev_pub,
        hd_path="m/44'/9999'/0'/0/0",
        pqc_seed=pqc_priv,
        kem_seed=kem_priv,
        puf_seed=puf_priv,
        mesh_mac_key=mesh_priv,
    )
