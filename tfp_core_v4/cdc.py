# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
FastCDC (Content-Defined Chunking) Engine for TFP v4.0

Implements 64-bit random gear matrix rolling hashing with dual-mask normalization
as specified in USENIX ATC '16 to maximize deduplication efficiency.
"""

import hashlib
import hmac
from dataclasses import asdict, dataclass
from typing import Any

# 256-entry 64-bit random gear matrix for FastCDC
_GEAR_MATRIX_64 = [
    0x534B5A5C77A7A645, 0xA575B5F3779836B2, 0xCEAC51FE16245F1B, 0x82C7C4EB75B49386,
    0x4E557262AB367184, 0x367A6B8856BD8396, 0x4896D8D5A344E9AE, 0x6E6686C56114D3C5,
    0x3F653138A7311145, 0x93318F12B58189D2, 0x6B6A56E21568A57A, 0x2A153A95E7C52377,
    0x7A748A5415273C85, 0x51E2861214D1658E, 0x857B96D7856A15E8, 0xD4B889812A45C895,
    0x965A21D1E7B92A47, 0x768789C231456A82, 0x6D8E4295D312E571, 0x811568A452794356,
    0x9237A8C52613859A, 0x76395B8A725D89A1, 0x5E6291C28198C513, 0xD8B8C245618765A2,
    0x978B451296A51283, 0x34A5167A89B214C5, 0x127685D251A76295, 0x65A845C271963B51,
    0x4296C513689A4582, 0x5698C23719854A23, 0x759812543A678512, 0x985264A7129548E5,
    0xA7123985D6154823, 0x68512937A8456123, 0x192837465A89B523, 0x7564839215A67B23,
    0x3847562910A5B742, 0x9283746519283746, 0x5647382910A5B734, 0x18273645A9B8C7D6,
    0x6758493021A5B876, 0x4839201567A8B9C2, 0x2938475610A5B6C7, 0x9584736210A8B7C6,
    0x5463728190A5B6C7, 0x7869504132A5B8C7, 0x897A6B5C4D3E2F10, 0x123456789ABCDEF0,
    0x0FEDCBA987654321, 0x5A5A5A5AA5A5A5A5, 0x3C3C3C3CC3C3C3C3, 0x6969696996969696,
    0xA5A5A5A55A5A5A5A, 0xC3C3C3C33C3C3C3C, 0x9696969669696969, 0x0F0F0F0FF0F0F0F0,
    0xF0F0F0F00F0F0F0F, 0x33333333CCCCCCCC, 0xCCCCCCCC33333333, 0x55555555AAAAAAAA,
    0xAAAAAAAA55555555, 0x7777777788888888, 0x8888888877777777, 0x11111111EEEEEEEE,
    0xEEEEEEEE11111111, 0x22222222DDDDDDDD, 0xDDDDDDDD22222222, 0x44444444BBBBBBBB,
    0xBBBBBBBB44444444, 0x8888888877777777, 0x6666666699999999, 0x9999999966666666,
    0x1234567812345678, 0x8765432187654321, 0x2345678923456789, 0x9876543298765432,
    0x3456789A3456789A, 0xA9876543A9876543, 0x456789AB456789AB, 0xBA987654BA987654,
    0x56789ABC56789ABC, 0xCB987654CB987654, 0x6789ABCD6789ABCD, 0xDCBA9876DCBA9876,
    0x789ABCDE789ABCDE, 0xEDCBA987EDCBA987, 0x89ABCDEF89ABCDEF, 0xFEDCBA98FEDCBA98,
    0x9ABCDEF09ABCDEF0, 0x0FEDCBA90FEDCBA9, 0xABCDEF01ABCDEF01, 0x10FEDCBA10FEDCBA,
    0xBCDEF012BCDEF012, 0x210FEDCB210FEDCB, 0xCDEF0123CDEF0123, 0x3210FEDC3210FEDC,
    0xDEF01234DEF01234, 0x43210FED43210FED, 0xEF012345EF012345, 0x543210FE543210FE,
    0xF0123456F0123456, 0x6543210F6543210F, 0x0123456701234567, 0x7654321076543210,
    0x13579BDF13579BDF, 0xFDB97531FDB97531, 0x2468ACE02468ACE0, 0x0ECA86420ECA8642,
    0x3579BDF13579BDF1, 0x1FDB97531FDB9753, 0x468ACE02468ACE02, 0x20ECA86420ECA864,
    0x579BDF13579BDF13, 0x31FDB97531FDB975, 0x68ACE02468ACE024, 0x420ECA86420ECA86,
    0x79BDF13579BDF135, 0x531FDB97531FDB97, 0x8ACE02468ACE0246, 0x6420ECA86420ECA8,
    0x9BDF13579BDF1357, 0x7531FDB97531FDB9, 0xACE02468ACE02468, 0x86420ECA86420ECA,
    0xBDF13579BDF13579, 0x97531FDB97531FDB, 0xCE02468ACE02468A, 0xA86420ECA86420EC,
    0xDF13579BDF13579B, 0xB97531FDB97531FD, 0xE02468ACE02468AC, 0xCA86420ECA86420E,
    0xF13579BDF13579BD, 0xDB97531FDB97531F, 0x02468ACE02468ACE, 0xECA86420ECA86420,
    0x2357BD132357BD13, 0x31DB753231DB7532, 0x478ACE02478ACE02, 0x20ECA87420ECA874,
    0x617395BF617395BF, 0xFB593716FB593716, 0x8293A4B58293A4B5, 0x5B4A39285B4A3928,
    0xC1D2E3F4C1D2E3F4, 0x4F3E2D1C4F3E2D1C, 0xA0B1C2D3A0B1C2D3, 0x3D2C1B0A3D2C1B0A,
    0x5566778855667788, 0x8877665588776655, 0x99AABBCC99AABBCC, 0xCCBBAA99CCBBAA99,
    0x1122334411223344, 0x4433221144332211, 0x5566778855667788, 0x8877665588776655,
    0x9900112299001122, 0x2211009922110099, 0x3344556633445566, 0x6655443366554433,
    0x778899AA778899AA, 0xAA998877AA998877, 0xBBCCDDEEBBCCDDEE, 0xEEDDCCBBEEDDCCBB,
    0xFF001122FF001122, 0x221100FF221100FF, 0x3344556633445566, 0x6655443366554433,
    0x778899AA778899AA, 0xAA998877AA998877, 0xBBCCDDEEBBCCDDEE, 0xEEDDCCBBEEDDCCBB,
    0x1A2B3C4D1A2B3C4D, 0x4D3C2B1A4D3C2B1A, 0x5E6F7A8B5E6F7A8B, 0x8B7A6F5E8B7A6F5E,
    0x9C0D1E2F9C0D1E2F, 0x2F1E0D9C2F1E0D9C, 0x3A4B5C6D3A4B5C6D, 0x6D5C4B3A6D5C4B3A,
    0x7E8F9A0B7E8F9A0B, 0x0B9A8F7E0B9A8F7E, 0x1C2D3E4F1C2D3E4F, 0x4F3E2D1C4F3E2D1C,
    0x5A6B7C8D5A6B7C8D, 0x8D7C6B5A8D7C6B5A, 0x9E0F1A2B9E0F1A2B, 0x2B1A0F9E2B1A0F9E,
    0x3C4D5E6F3C4D5E6F, 0x6F5E4D3C6F5E4D3C, 0x7A8B9C0D7A8B9C0D, 0x0D9C8B7A0D9C8B7A,
    0x1E2F3A4B1E2F3A4B, 0x4B3A2F1E4B3A2F1E, 0x5C6D7E8F5C6D7E8F, 0x8F7E6D5C8F7E6D5C,
    0x9A0B1C2D9A0B1C2D, 0x2D1C0B9A2D1C0B9A, 0x3E4F5A6B3E4F5A6B, 0x6B5A4F3E6B5A4F3E,
    0x7C8D9E0F7C8D9E0F, 0x0F9E8D7C0F9E8D7C, 0x1A2B3C4D1A2B3C4D, 0x4D3C2B1A4D3C2B1A,
    0x5E6F7A8B5E6F7A8B, 0x8B7A6F5E8B7A6F5E, 0x9C0D1E2F9C0D1E2F, 0x2F1E0D9C2F1E0D9C,
    0x3A4B5C6D3A4B5C6D, 0x6D5C4B3A6D5C4B3A, 0x7E8F9A0B7E8F9A0B, 0x0B9A8F7E0B9A8F7E,
    0x1C2D3E4F1C2D3E4F, 0x4F3E2D1C4F3E2D1C, 0x5A6B7C8D5A6B7C8D, 0x8D7C6B5A8D7C6B5A,
    0x9E0F1A2B9E0F1A2B, 0x2B1A0F9E2B1A0F9E, 0x3C4D5E6F3C4D5E6F, 0x6F5E4D3C6F5E4D3C,
    0x7A8B9C0D7A8B9C0D, 0x0D9C8B7A0D9C8B7A, 0x1E2F3A4B1E2F3A4B, 0x4B3A2F1E4B3A2F1E,
    0x5C6D7E8F5C6D7E8F, 0x8F7E6D5C8F7E6D5C, 0x9A0B1C2D9A0B1C2D, 0x2D1C0B9A2D1C0B9A,
    0x3E4F5A6B3E4F5A6B, 0x6B5A4F3E6B5A4F3E, 0x7C8D9E0F7C8D9E0F, 0x0F9E8D7C0F9E8D7C,
    0x1122334455667788, 0x8877665544332211, 0x99AABBCCDDEEFF00, 0x00FFEEDDCCBBAA99,
    0x13579BDF02468ACE, 0xECA86420FDB97531, 0x2468ACE013579BDF, 0xFDB975310ECA8642,
    0x3141592653589793, 0x2384626433832795, 0x2718281828459045, 0x5926535897932384,
    0x6264338327950288, 0x4197169399375105, 0x8209749445923078, 0x1640628620899862,
    0x8034825342117067, 0x9821480865132823, 0x0664709384460955, 0x0582231725359408,
    0x1284756482930192, 0x9283746501928374, 0x7463524109283746, 0x6473829102938475,
]


@dataclass(frozen=True)
class ChunkRecipe:
    """Deterministic recipe manifest describing content assembly from discrete chunks."""

    root_hash: str
    total_size: int
    chunk_hashes: list[str]
    chunk_sizes: list[int]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compute_root_hash(self) -> str:
        """Calculate deterministic root hash over the sequence of chunk hashes."""
        hasher = hashlib.sha3_256()
        for h in self.chunk_hashes:
            hasher.update(h.encode("utf-8"))
        return hasher.hexdigest()

    def validate(self, expected_root: str | None = None) -> bool:
        """
        Validate structural integrity and hash identity:
        1. chunk_hashes and chunk_sizes lengths match
        2. sum(chunk_sizes) == total_size
        3. computed root hash over ordered chunk hashes matches self.root_hash (and expected_root if provided)
        """
        if len(self.chunk_hashes) != len(self.chunk_sizes):
            return False
        if sum(self.chunk_sizes) != self.total_size:
            return False
        computed = self.compute_root_hash()
        if not hmac.compare_digest(computed, self.root_hash):
            return False
        if expected_root is not None and not hmac.compare_digest(computed, expected_root):
            return False
        return True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChunkRecipe":
        rec = cls(
            root_hash=data["root_hash"],
            total_size=data["total_size"],
            chunk_hashes=list(data["chunk_hashes"]),
            chunk_sizes=list(data["chunk_sizes"]),
            metadata=dict(data.get("metadata", {})),
        )
        if not rec.validate(expected_root=rec.root_hash):
            raise ValueError(f"Invalid recipe data: chunk sequence does not match root_hash {rec.root_hash}")
        return rec


class ContentDefinedChunker:
    """FastCDC 64-bit normalized content-defined chunker."""

    def __init__(
        self,
        min_size: int = 512,
        max_size: int = 4096,
        target_size: int = 1024,
    ):
        if not (min_size <= target_size <= max_size):
            raise ValueError(f"Invalid size bounds: min={min_size} <= target={target_size} <= max={max_size}")
        self.min_size = min_size
        self.max_size = max_size
        self.target_size = target_size

        # Compute dual bitmasks for normalization
        bits = max(1, round(self._log2(target_size)))
        self.mask_s = (1 << (bits + 1)) - 1
        self.mask_l = (1 << (bits - 1)) - 1

    @staticmethod
    def _log2(n: int) -> float:
        import math
        return math.log2(n)

    def chunk(self, data: bytes) -> list[bytes]:
        """Partition arbitrary binary payload into FastCDC chunks."""
        if not data:
            return []

        n = len(data)
        if n <= self.min_size:
            return [data]

        chunks = []
        offset = 0
        uint64_max = 0xFFFFFFFFFFFFFFFF

        while offset < n:
            remaining = n - offset
            if remaining <= self.min_size:
                chunks.append(data[offset:])
                break

            chunk_start = offset
            scan_pos = chunk_start + self.min_size
            max_scan = min(chunk_start + self.max_size, n)
            mid_point = min(chunk_start + self.target_size, max_scan)

            rolling_hash = 0

            # 1. Warm up rolling hash on the minimum window
            for i in range(chunk_start, scan_pos):
                b = data[i]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[b]) & uint64_max

            # 2. Sub-target region: use tighter mask (mask_s)
            boundary_found = False
            while scan_pos < mid_point:
                b = data[scan_pos]
                rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[b]) & uint64_max
                if (rolling_hash & self.mask_s) == 0:
                    boundary_found = True
                    scan_pos += 1
                    break
                scan_pos += 1

            # 3. Post-target region: use looser mask (mask_l) if boundary not yet found
            if not boundary_found:
                while scan_pos < max_scan:
                    b = data[scan_pos]
                    rolling_hash = ((rolling_hash << 1) + _GEAR_MATRIX_64[b]) & uint64_max
                    if (rolling_hash & self.mask_l) == 0:
                        boundary_found = True
                        scan_pos += 1
                        break
                    scan_pos += 1

            chunk_bytes = data[chunk_start:scan_pos]
            chunks.append(chunk_bytes)
            offset = scan_pos

        return chunks

    def create_recipe(self, data: bytes, metadata: dict[str, Any] | None = None) -> tuple[ChunkRecipe, list[bytes]]:
        """Chunk payload, hash components with SHA3-256, and produce Recipe."""
        chunks = self.chunk(data)
        chunk_hashes = [hashlib.sha3_256(c).hexdigest() for c in chunks]
        chunk_sizes = [len(c) for c in chunks]

        # Calculate deterministic root hash over the sequence of chunk hashes
        hasher = hashlib.sha3_256()
        for h in chunk_hashes:
            hasher.update(h.encode("utf-8"))
        root_hash = hasher.hexdigest()

        recipe = ChunkRecipe(
            root_hash=root_hash,
            total_size=len(data),
            chunk_hashes=chunk_hashes,
            chunk_sizes=chunk_sizes,
            metadata=metadata or {},
        )
        return recipe, chunks

    @staticmethod
    def assemble(recipe: ChunkRecipe, chunk_map: dict[str, bytes]) -> bytes:
        """Bit-exact assembly of chunks according to recipe."""
        if not recipe.validate():
            raise ValueError(f"Invalid recipe: sequence of chunk hashes does not match root_hash {recipe.root_hash}")
        assembled = bytearray()
        for expected_hash, size in zip(recipe.chunk_hashes, recipe.chunk_sizes):
            if expected_hash not in chunk_map:
                raise KeyError(f"Missing required chunk: {expected_hash}")
            chunk = chunk_map[expected_hash]
            if len(chunk) != size:
                raise ValueError(f"Chunk size mismatch for {expected_hash}: expected {size}, got {len(chunk)}")
            actual_hash = hashlib.sha3_256(chunk).hexdigest()
            if not hmac.compare_digest(actual_hash, expected_hash):
                raise ValueError(f"Corrupted chunk data: hash mismatch for {expected_hash}")
            assembled.extend(chunk)
        return bytes(assembled)
