import hashlib
import dataclasses
from typing import List

from tfp_client.lib.fountain.adapter import RaptorQAdapter
from tfp_broadcaster.src.multicast.adapter import MulticastAdapter
from tfp_broadcaster.src.ldm_semantic_mapper import LDMSemanticMapper


@dataclasses.dataclass
class TaskRecipe:
    task_type: str
    params_hash: str
    difficulty: int

    def to_bytes(self) -> bytes:
        return f"{self.task_type}:{self.params_hash}:{self.difficulty}".encode()

    @property
    def hash(self) -> str:
        return hashlib.sha3_256(self.to_bytes()).hexdigest()


class Broadcaster:
    def __init__(self, raptorq=None, multicast=None):
        self.raptorq = raptorq or RaptorQAdapter()
        self.multicast = multicast or MulticastAdapter()
        self._ldm = LDMSemanticMapper()

    def seed_content(self, file_bytes: bytes, metadata: dict = None, use_ldm: bool = False) -> dict:
        if not file_bytes:
            raise ValueError("Cannot seed empty content")
        root_hash = hashlib.sha3_256(file_bytes).hexdigest()
        shards = self.raptorq.encode(file_bytes, redundancy=0.05)
        self.multicast.transmit(shards)
        result = {
            "root_hash": root_hash,
            "status": "broadcasting",
            "shard_count": len(shards),
        }
        if use_ldm and metadata is not None:
            result["plp_assignment"] = self._ldm.map_to_plps(metadata)
        return result

    def broadcast_compute_task(self, recipe: TaskRecipe) -> dict:
        shards = self.raptorq.encode(recipe.to_bytes())
        self.multicast.transmit(shards)
        return {"task_hash": recipe.hash, "status": "dripped"}
