# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
C-ABI ctypes Bridge for catid/wirehair (RFC 6330 / O(N) Rateless Fountain Code)

Provides zero-overhead native SIMD fountain encoding and decoding.
When the native shared library (wirehair.dll / libwirehair.so / libwirehair.dylib)
is present, leverages AVX2/NEON vector instructions.
When absent, transparently falls back to the high-performance pure-Python
FountainCodec engine with zero API deviation.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import math
import os
from pathlib import Path
import platform
import random
from typing import Dict, List, Optional, Tuple, Union

from .fountain import (
    FountainCodec,
    FountainDroplet,
    _sample_soliton_degree,
)

log = logging.getLogger("tfp.wirehair")

# Wirehair result constants
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
        # Setup signatures:
        # int wirehair_init(void)
        if hasattr(lib, "wirehair_init_"):
            init_func = lib.wirehair_init_
        elif hasattr(lib, "wirehair_init"):
            init_func = lib.wirehair_init
        else:
            return False

        init_func.argtypes = []
        init_func.restype = ctypes.c_int

        result = init_func()
        if result == WIREHAIR_RESULT_SUCCESS:
            _LIB_WIREHAIR = lib
            _configure_wirehair_signatures(lib)
            log.info("Native wirehair SIMD fountain codec initialized from %s", lib_path)
            return True
        else:
            log.warning("wirehair_init() failed with code %d", result)
            return False
    except Exception as exc:
        log.warning("Failed to load native wirehair library: %s", exc)
        return False


def _configure_wirehair_signatures(lib: ctypes.CDLL):
    """Configure ctypes signatures for native Wirehair C-ABI functions."""
    # WirehairCodec wirehair_encoder_create(WirehairCodec, const void*, uint64_t, uint32_t)
    if hasattr(lib, "wirehair_encoder_create"):
        lib.wirehair_encoder_create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint32]
        lib.wirehair_encoder_create.restype = ctypes.c_void_p

    # uint32_t wirehair_encode(WirehairCodec, uint32_t, void*, uint32_t, uint32_t*)
    if hasattr(lib, "wirehair_encode"):
        lib.wirehair_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.wirehair_encode.restype = ctypes.c_uint32

    # WirehairCodec wirehair_decoder_create(WirehairCodec, uint64_t, uint32_t)
    if hasattr(lib, "wirehair_decoder_create"):
        lib.wirehair_decoder_create.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32]
        lib.wirehair_decoder_create.restype = ctypes.c_void_p

    # uint32_t wirehair_decode(WirehairCodec, uint32_t, const void*, uint32_t)
    if hasattr(lib, "wirehair_decode"):
        lib.wirehair_decode.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]
        lib.wirehair_decode.restype = ctypes.c_uint32

    # uint32_t wirehair_recover(WirehairCodec, void*, uint64_t)
    if hasattr(lib, "wirehair_recover"):
        lib.wirehair_recover.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint64]
        lib.wirehair_recover.restype = ctypes.c_uint32

    # void wirehair_free(WirehairCodec)
    if hasattr(lib, "wirehair_free"):
        lib.wirehair_free.argtypes = [ctypes.c_void_p]
        lib.wirehair_free.restype = None


def wirehair_is_available() -> bool:
    """Return True if native Wirehair C-ABI library is loaded and operational."""
    return init_wirehair()


class AcceleratedFountainCodec:
    """
    Unified high-performance Fountain Codec.
    Uses native Wirehair SIMD instructions if available, otherwise seamlessly
    falls back to the vectorized GF(2) pure-Python engine.
    """

    def __init__(
        self,
        symbol_size: int = 512,
        root_hash: Optional[Union[str, bytes]] = None,
        session_nonce: Optional[Union[str, bytes]] = None,
        prefer_native: bool = True,
    ):
        self.symbol_size = symbol_size
        self.root_hash = root_hash
        self.session_nonce = session_nonce
        self.prefer_native = prefer_native
        self._python_codec = FountainCodec(
            symbol_size=symbol_size,
            root_hash=root_hash,
            session_nonce=session_nonce,
        )

    @property
    def is_accelerated(self) -> bool:
        """True if using native SIMD acceleration, False if pure Python."""
        return self.prefer_native and wirehair_is_available()

    def encode(
        self,
        data: bytes,
        redundancy: float = 0.50,
        root_hash: Optional[Union[str, bytes]] = None,
        session_nonce: Optional[Union[str, bytes]] = None,
    ) -> Tuple[List[FountainDroplet], int, int]:
        """
        Encode payload into fountain droplets.
        Delegates to native SIMD Wirehair if loaded, or pure-Python codec.
        """
        if not data:
            return [], 0, 0

        # When native is available and loaded
        if self.is_accelerated and _LIB_WIREHAIR is not None:
            try:
                return self._encode_native(data, redundancy)
            except Exception as e:
                log.warning("Native Wirehair encode failed (%s); falling back to Python.", e)

        return self._python_codec.encode(
            data,
            redundancy=redundancy,
            root_hash=root_hash,
            session_nonce=session_nonce,
        )

    def _encode_native(
        self,
        data: bytes,
        redundancy: float,
    ) -> Tuple[List[FountainDroplet], int, int]:
        """Internal native encoder via C ctypes bridge."""
        lib = _LIB_WIREHAIR
        orig_len = len(data)
        k = math.ceil(orig_len / self.symbol_size)
        total_droplets = max(k, math.ceil(k * (1.0 + redundancy)))

        codec_ptr = lib.wirehair_encoder_create(None, data, orig_len, self.symbol_size)
        if not codec_ptr:
            raise RuntimeError("Failed to create Wirehair encoder")

        try:
            droplets = []
            out_len = ctypes.c_uint32(0)
            buf = ctypes.create_string_buffer(self.symbol_size)

            for block_id in range(total_droplets):
                res = lib.wirehair_encode(
                    codec_ptr,
                    block_id,
                    buf,
                    self.symbol_size,
                    ctypes.byref(out_len),
                )
                if res != WIREHAIR_RESULT_SUCCESS:
                    continue

                payload = bytes(buf.raw[:out_len.value])
                # Generate indices for compatibility
                if block_id < k:
                    degree = 1
                    indices = [block_id]
                else:
                    rng = random.Random(block_id)
                    degree = _sample_soliton_degree(k, rng)
                    indices = sorted(rng.sample(range(k), degree))

                droplets.append(
                    FountainDroplet(
                        seed=block_id,
                        degree=degree,
                        indices=indices,
                        payload=payload,
                    )
                )
            return droplets, k, orig_len
        finally:
            lib.wirehair_free(codec_ptr)

    def decode(
        self,
        droplets: List[FountainDroplet],
        k: int,
        orig_len: int,
        pre_validate: Optional[bool] = None,
    ) -> bytes:
        """
        Decode original payload from received droplets.
        Delegates to native SIMD Wirehair if loaded, or pure-Python codec.
        """
        if self.is_accelerated and _LIB_WIREHAIR is not None:
            try:
                return self._decode_native(droplets, k, orig_len)
            except Exception as e:
                log.warning("Native Wirehair decode failed (%s); falling back to Python.", e)

        return self._python_codec.decode(
            droplets,
            k=k,
            orig_len=orig_len,
            pre_validate=pre_validate,
        )

    def _decode_native(
        self,
        droplets: List[FountainDroplet],
        k: int,
        orig_len: int,
    ) -> bytes:
        """Internal native decoder via C ctypes bridge."""
        lib = _LIB_WIREHAIR
        codec_ptr = lib.wirehair_decoder_create(None, orig_len, self.symbol_size)
        if not codec_ptr:
            raise RuntimeError("Failed to create Wirehair decoder")

        try:
            for d in droplets:
                res = lib.wirehair_decode(codec_ptr, d.seed, d.payload, len(d.payload))
                if res == WIREHAIR_RESULT_SUCCESS:
                    # Successfully received enough to recover!
                    out_buf = ctypes.create_string_buffer(orig_len)
                    rec_res = lib.wirehair_recover(codec_ptr, out_buf, orig_len)
                    if rec_res == WIREHAIR_RESULT_SUCCESS:
                        return bytes(out_buf.raw[:orig_len])

            raise ValueError(f"Need more droplets to decode (k={k})")
        finally:
            lib.wirehair_free(codec_ptr)
