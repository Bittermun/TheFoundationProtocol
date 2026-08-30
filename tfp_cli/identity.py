# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP CLI Identity Interface
"""

import sys
from pathlib import Path

# Add project root and legacy paths if needed
_root = Path(__file__).resolve().parent.parent
_legacy = _root / "tfp-foundation-protocol"
if str(_legacy) not in sys.path:
    sys.path.insert(0, str(_legacy))


try:
    from tfp_cli.identity import (
        IdentityBackupError,
        IdentityEncryptionError,
        IdentityError,
        change_passphrase,
        export_identity,
        load_or_create_identity,
        recover_identity,
    )
except ImportError:
    pass

__all__ = [
    "IdentityBackupError",
    "IdentityEncryptionError",
    "IdentityError",
    "change_passphrase",
    "export_identity",
    "load_or_create_identity",
    "recover_identity",
]
