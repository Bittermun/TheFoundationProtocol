# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Identity Management - v3.2.1

Secure identity storage with encryption, backup, and recovery.
Replaces plaintext ~/.tfp/identity.json with encrypted storage.
"""

import datetime
import json
import hashlib
import secrets
import time as _time
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class IdentityError(Exception):
    """Base exception for identity operations."""

    pass


class IdentityEncryptionError(IdentityError):
    """Raised when encryption/decryption fails."""

    pass


class IdentityBackupError(IdentityError):
    """Raised when backup operations fail."""

    pass


def _get_identity_dir() -> Path:
    """Get the identity directory path (~/.tfp/)."""
    return Path.home() / ".tfp"


def _get_identity_path() -> Path:
    """Get the encrypted identity file path."""
    return _get_identity_dir() / "identity.enc"


def _get_backup_dir() -> Path:
    """Get the backup directory path."""
    return _get_identity_dir() / "backups"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive encryption key from passphrase using PBKDF2."""
    if not CRYPTO_AVAILABLE:
        raise IdentityEncryptionError("cryptography library not installed")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
        backend=default_backend(),
    )
    return kdf.derive(passphrase.encode())


def _encrypt_identity(data: Dict[str, Any], passphrase: str) -> bytes:
    """Encrypt identity data with AES-256-GCM."""
    if not CRYPTO_AVAILABLE:
        raise IdentityEncryptionError("cryptography library not installed")

    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_key(passphrase, salt)

    aesgcm = AESGCM(key)
    plaintext = json.dumps(data, indent=2).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    # Format: salt(16) + nonce(12) + ciphertext
    return salt + nonce + ciphertext


def _decrypt_identity(encrypted_data: bytes, passphrase: str) -> Dict[str, Any]:
    """Decrypt identity data."""
    if not CRYPTO_AVAILABLE:
        raise IdentityEncryptionError("cryptography library not installed")

    if len(encrypted_data) < 28:
        raise IdentityEncryptionError("invalid encrypted data format")

    salt = encrypted_data[:16]
    nonce = encrypted_data[16:28]
    ciphertext = encrypted_data[28:]

    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())
    except Exception as e:
        raise IdentityEncryptionError(f"decryption failed: {e}")


def generate_mnemonic() -> str:
    """Generate a simple recovery mnemonic (word-based)."""
    wordlist = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
        "romeo",
        "sierra",
        "tango",
        "uniform",
        "victor",
        "whiskey",
        "xray",
        "yankee",
        "zulu",
        "anchor",
        "beacon",
        "compass",
        "dynamo",
        "eclipse",
        "falcon",
    ]
    indices = [secrets.randbelow(len(wordlist)) for _ in range(12)]
    return " ".join(wordlist[i] for i in indices)


def mnemonic_to_seed(mnemonic: str) -> bytes:
    """Convert mnemonic to seed for deterministic identity generation."""
    return hashlib.sha256(mnemonic.encode()).digest()


def load_or_create_identity(
    device_id: str, passphrase: Optional[str] = None, mnemonic: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load device identity or create a new one.

    Args:
        device_id: Unique device identifier
        passphrase: Encryption passphrase (required for new identities)
        mnemonic: Recovery mnemonic (optional, generated if not provided)

    Returns:
        Dictionary with device_id and puf_entropy

    Raises:
        IdentityError: If passphrase required but not provided
        IdentityEncryptionError: If decryption fails
    """
    identity_dir = _get_identity_dir()
    identity_dir.mkdir(parents=True, exist_ok=True)

    identity_path = _get_identity_path()

    # Try to load existing identity
    if identity_path.exists():
        if passphrase is None:
            raise IdentityError(
                "Encrypted identity found. Please provide passphrase "
                "or use 'tfp identity recover' to restore from backup."
            )

        try:
            encrypted_data = identity_path.read_bytes()
            identities = _decrypt_identity(encrypted_data, passphrase)

            if device_id in identities:
                entry = identities[device_id]
                return {
                    "device_id": device_id,
                    "puf_entropy": bytes.fromhex(entry["puf_entropy_hex"]),
                }
        except IdentityEncryptionError:
            raise IdentityError("Incorrect passphrase or corrupted identity file.")

    # Create new identity
    if passphrase is None:
        raise IdentityError(
            "New identity requires a passphrase for encryption. "
            "Use --passphrase or set TFP_IDENTITY_PASSPHRASE env var."
        )

    # Generate or use provided mnemonic
    if mnemonic is None:
        mnemonic = generate_mnemonic()
        print("\n⚠️  BACKUP YOUR RECOVERY MNEMONIC ⚠️")
        print("Write this down and store it securely:\n")
        print(f"  {mnemonic}")
        print("\nThis is the ONLY way to recover your identity if lost.\n")

    # Generate PUF entropy
    puf_entropy = secrets.token_bytes(32)

    # Store identity
    identities = {}
    if identity_path.exists():
        try:
            encrypted_data = identity_path.read_bytes()
            identities = _decrypt_identity(encrypted_data, passphrase)
        except IdentityError:
            pass  # Start fresh if decryption fails

    identities[device_id] = {
        "puf_entropy_hex": puf_entropy.hex(),
        "mnemonic_hash": hashlib.sha256(mnemonic.encode()).hexdigest()[:8],
        "created_at": _time.time(),
    }

    # Encrypt and save
    encrypted_data = _encrypt_identity(identities, passphrase)
    identity_path.write_bytes(encrypted_data)
    identity_path.chmod(0o600)  # Owner read/write only

    # Create backup
    _create_backup(identity_path, passphrase)

    return {"device_id": device_id, "puf_entropy": puf_entropy}


def _create_backup(identity_path: Path, passphrase: str) -> None:
    """Create timestamped backup of identity file."""
    backup_dir = _get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"identity_{timestamp}.enc"

    try:
        backup_path.write_bytes(identity_path.read_bytes())
        backup_path.chmod(0o600)

        # Keep only last 5 backups
        backups = sorted(backup_dir.glob("identity_*.enc"))
        for old_backup in backups[:-5]:
            old_backup.unlink()

    except Exception as e:
        raise IdentityBackupError(f"backup failed: {e}")


def recover_identity(
    mnemonic: str, device_id: str, new_passphrase: str
) -> Dict[str, Any]:
    """
    Recover identity from mnemonic.

    Note: This generates a NEW identity with the same mnemonic-derived seed.
    Credits from the old identity cannot be recovered (by design - credits are
    bound to the original PUF entropy).

    Args:
        mnemonic: Recovery mnemonic phrase
        device_id: Device ID to recover
        new_passphrase: New passphrase for encryption

    Returns:
        New identity dictionary
    """
    # Derive seed from mnemonic
    seed = mnemonic_to_seed(mnemonic)

    # Use seed to generate deterministic PUF entropy
    puf_entropy = hashlib.sha256(seed + device_id.encode()).digest()

    # Store new identity
    identities = {
        device_id: {
            "puf_entropy_hex": puf_entropy.hex(),
            "recovered_from_mnemonic": True,
            "recovered_at": _time.time(),
        }
    }

    identity_path = _get_identity_path()
    encrypted_data = _encrypt_identity(identities, new_passphrase)
    identity_path.write_bytes(encrypted_data)
    identity_path.chmod(0o600)

    print(f"✓ Identity recovered for device: {device_id}")
    print("⚠️  Note: Credits from previous identity are NOT recoverable.")

    return {"device_id": device_id, "puf_entropy": puf_entropy}


def export_identity(passphrase: str, output_path: Optional[str] = None) -> str:
    """
    Export encrypted identity to file for backup.

    Args:
        passphrase: Current passphrase
        output_path: Output file path (default: ~/.tfp/backups/export_TIMESTAMP.enc)

    Returns:
        Path to exported file
    """
    identity_path = _get_identity_path()

    if not identity_path.exists():
        raise IdentityError("No identity file found")

    # Verify passphrase by decrypting
    encrypted_data = identity_path.read_bytes()
    _decrypt_identity(encrypted_data, passphrase)

    # Export to backup dir
    if output_path is None:
        backup_dir = _get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(backup_dir / f"export_{timestamp}.enc")

    Path(output_path).write_bytes(encrypted_data)
    Path(output_path).chmod(0o600)

    return output_path


def change_passphrase(old_passphrase: str, new_passphrase: str) -> None:
    """Change the identity encryption passphrase."""
    identity_path = _get_identity_path()

    if not identity_path.exists():
        raise IdentityError("No identity file found")

    # Decrypt with old passphrase
    encrypted_data = identity_path.read_bytes()
    identities = _decrypt_identity(encrypted_data, old_passphrase)

    # Re-encrypt with new passphrase
    new_encrypted = _encrypt_identity(identities, new_passphrase)
    identity_path.write_bytes(new_encrypted)

    print("✓ Passphrase changed successfully")
