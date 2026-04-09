from typing import List


class RaptorQAdapter:
    """Mock RaptorQ adapter — swap for nanorq/libRaptorQ bindings."""

    def encode(self, data: bytes, redundancy: float = 0.05) -> List[bytes]:
        k = max(1, len(data) // 128)
        shards = []
        for i in range(k + int(k * redundancy) + 1):
            shard = data[i * 128:(i + 1) * 128] or data[-128:]
            shards.append(shard)
        return shards

    def decode(self, shards: List[bytes], k: int = None) -> bytes:
        if not shards:
            raise ValueError("No shards to decode")
        return b"".join(shards[:k] if k else shards)
