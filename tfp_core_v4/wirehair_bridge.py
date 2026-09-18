# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
C-ABI ctypes Bridge for catid/wirehair (RFC 6330 / O(N) Rateless Fountain Code)

Provides zero-overhead native SIMD fountain encoding and decoding for modest devices.
If the native shared library (wirehair.dll / libwirehair.so / libwirehair.dylib)
is not found in the search path or TFP_WIREHAIR_LIB, falls back to the internal codec
while exposing `wirehair_is_available() -> bool` to make acceleration state explicit.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import platform
from pathlib import Path
from typing import Optional

log = logging.getLogger("tfp.wirehair")

# Wirehair error codes from wirehair.h
WIREHAIR_RESULT_SUCCESS = 0
WIREHAIR_RESULT_MORE_INPUT_NEEDED = 1

_LIB_WIREHAIR: Optional[ctypes.CDLL] = None
_INIT_ATTEMPTED: bool = False


def _find_wirehair_lib() -> Optional[str]:
    """Search for the wirehair shared library across environment, repo, and system paths."""
    # 1. Check explicit environment override
    env_path = os.environ.get("TFP_WIREHAIR_LIB")
    if env_path and Path(env_path).is_file():
        return env_path

    # 2. Check local repo build / artifact paths
    repo_root = Path(__file__).resolve().parent.parent
    system_name = platform.system().lower()
    
    if "windows" in system_name:
        lib_names = ["wirehair.dll", "libwirehair.dll"]
    elif "darwin" in system_name:
        lib_names = ["libwirehair.dylib", "libwirehair.so"]
    else:
        lib_names = ["libwirehair.so"]

    search_dirs = [
        repo_root / "build",
        repo_root / ".dist_verify" / "native",
        Path(__file__).resolve().parent,
    ]

    for d in search_dirs:
        for name in lib_names:
            candidate = d / name
            if candidate.is_file():
                return str(candidate)

    # 3. System library search
    return ctypes.util.find_library("wirehair")


def init_wirehair() -> bool:
    """Initialize the Wirehair library if available."""
    global _LIB_WIREHAIR, _INIT_ATTEMPTED
    if _INIT_ATTEMPTED:
        return _LIB_WIREHAIR is not None

    _INIT_ATTEMPTED = True
    lib_path = _find_wirehair_lib()
    if not lib_path:
        log.debug("Native wirehair library not found; using vectorized Python fallback.")
        return False

    try:
        lib = ctypes.CDLL(lib_path)
        # int wirehair_init(void)
        lib.wirehair_init_.argtypes = []
        lib.wirehair_init_.restype = ctypes.c_int
        
        result = lib.wirehair_init_()
        if result == WIREHAIR_RESULT_SUCCESS:
            _LIB_WIREHAIR = lib
            log.info("Native wirehair SIMD fountain codec initialized from %s", lib_path)
            return True
        else:
            log.warning("wirehair_init() failed with code %d", result)
            return False
    except Exception as exc:
        log.warning("Failed to load native wirehair library: %s", exc)
        return False


def wirehair_is_available() -> bool:
    """Return True if native Wirehair C-ABI library is loaded and operational."""
    return init_wirehair()
