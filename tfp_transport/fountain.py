# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Transport Fountain & Anti-Pollution Layer

Integrates deterministic seed schedules, hop-level packet filtering, and
pre-elimination verification into the transport channel.
"""

from typing import Dict, Union

from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    LubyTransformCodec,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)


class TransportFountainChannel:
    """
    Transport-layer fountain channel with anti-pollution admission control.
    Filters Byzantine injected droplets before buffering for decoding.
    """

    def __init__(
        self,
        root_hash: Union[str, bytes],
        k_source_symbols: int,
        orig_len: int,
        symbol_size: int = 256,
        session_nonce: Union[str, bytes] = b"",
    ):
        self.root_hash = root_hash
        self.k = k_source_symbols
        self.orig_len = orig_len
        self.symbol_size = symbol_size
        self.session_nonce = session_nonce

        self.codec = FountainCodec(
            symbol_size=symbol_size,
            root_hash=root_hash,
            session_nonce=session_nonce,
            pre_validate=True,
        )
        self.received_droplets: Dict[int, FountainDroplet] = {}
        self.rejected_count: int = 0

    def admit_droplet(self, droplet: FountainDroplet) -> bool:
        """
        Evaluate and admit an incoming droplet if authentic and non-polluted.

        Returns:
            True if admitted, False if rejected by anti-pollution filter.
        """
        if len(droplet.payload) != self.symbol_size:
            self.rejected_count += 1
            return False

        is_valid = verify_droplet_seed_authenticity(
            droplet_seed=droplet.seed,
            root_hash=self.root_hash,
            session_nonce=self.session_nonce,
            total_source_blocks=self.k,
            degree=droplet.degree,
            indices=droplet.indices,
            symbol_size=self.symbol_size,
        )
        if not is_valid:
            self.rejected_count += 1
            return False

        self.received_droplets[droplet.seed] = droplet
        return True

    def can_decode(self) -> bool:
        """Check if enough valid droplets have been collected."""
        return len(self.received_droplets) >= self.k

    def decode(self) -> bytes:
        """Decode collected droplets into reconstructed payload."""
        return self.codec.decode(
            droplets=list(self.received_droplets.values()),
            k=self.k,
            orig_len=self.orig_len,
            pre_validate=True,
        )


__all__ = [
    "FountainCodec",
    "FountainDecoder",
    "FountainDroplet",
    "FountainEncoder",
    "LubyTransformCodec",
    "TransportFountainChannel",
    "derive_repair_seed_schedule",
    "verify_droplet_seed_authenticity",
]
