import copy
import hashlib
from typing import Dict, Optional


class HierarchicalLexiconTree:
    def __init__(self):
        self._state: Dict[str, bytes] = {}
        self._base_hash: Optional[str] = None

    def set_base(self, base_pin_hash: str, data: bytes):
        self._base_hash = base_pin_hash
        self._state = {"base": data}

    def apply_delta(self, base_pin_hash: str, lora_int4_delta: bytes) -> bool:
        if self._base_hash != base_pin_hash:
            return False
        expected_hash = hashlib.sha3_256(
            self._state.get("base", b"") + lora_int4_delta
        ).hexdigest()
        backup = copy.deepcopy(self._state)
        try:
            self._state["delta_" + expected_hash[:8]] = lora_int4_delta
            self._base_hash = expected_hash
            return True
        except Exception:
            self._state = backup
            return False

    def sync_via_ndn(
        self, interest_prefix: str, ndn_adapter=None, raptorq_adapter=None
    ):
        if ndn_adapter:
            interest = ndn_adapter.create_interest(interest_prefix)
            data = ndn_adapter.express_interest(interest)
            if raptorq_adapter:
                decoded = raptorq_adapter.decode([data.content])
                return decoded
        return b""

    @property
    def current_hash(self) -> Optional[str]:
        return self._base_hash
