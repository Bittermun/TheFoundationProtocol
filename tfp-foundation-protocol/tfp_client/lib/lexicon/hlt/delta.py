"""
Lexicon Delta Encoding - Efficient Updates for HLT

Delta encoding allows efficient transmission of lexicon updates by sending
only the changes (additions, modifications, deletions) rather than full lexicons.
"""

import dataclasses
import datetime
import hashlib
import json
from enum import Enum
from typing import Dict, List, Union

_utcnow = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()


class DeltaType(Enum):
    """Types of delta operations."""

    ADDITION = "addition"  # New terms added
    MODIFICATION = "modification"  # Existing terms modified
    DELETION = "deletion"  # Terms removed


@dataclasses.dataclass
class LexiconDelta:
    """
    Represents a delta update to a lexicon.

    Compact representation of changes between lexicon versions.
    """

    delta_type: DeltaType
    source_version: str
    target_version: str
    data: Union[Dict[str, str], List[str]]
    timestamp: str = dataclasses.field(default_factory=_utcnow)

    def to_dict(self) -> Dict:
        """Serialize delta to dictionary."""
        return {
            "delta_type": self.delta_type.value,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_bytes(self) -> bytes:
        """Serialize delta to compact bytes."""
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_dict(cls, data: Dict) -> "LexiconDelta":
        """Deserialize delta from dictionary."""
        return cls(
            delta_type=DeltaType(data["delta_type"]),
            source_version=data["source_version"],
            target_version=data["target_version"],
            data=data["data"],
            timestamp=data.get("timestamp", _utcnow()),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "LexiconDelta":
        """Deserialize delta from bytes."""
        return cls.from_dict(json.loads(data.decode("utf-8")))

    def apply(self, state: Dict[str, str]) -> Dict[str, str]:
        """
        Apply this delta to a lexicon state.

        Args:
            state: Current lexicon state (term -> definition mapping)

        Returns:
            Updated lexicon state
        """
        result = state.copy()

        if self.delta_type == DeltaType.ADDITION:
            # Add new terms
            if isinstance(self.data, dict):
                result.update(self.data)

        elif self.delta_type == DeltaType.MODIFICATION:
            # Modify existing terms
            if isinstance(self.data, dict):
                for term, changes in self.data.items():
                    if isinstance(changes, dict) and "new" in changes:
                        result[term] = changes["new"]
                    else:
                        result[term] = changes

        elif self.delta_type == DeltaType.DELETION:
            # Remove terms
            if isinstance(self.data, list):
                for term in self.data:
                    result.pop(term, None)

        return result

    def compute_hash(self) -> str:
        """Compute SHA3-256 hash of delta for verification."""
        data = self.to_bytes()
        return hashlib.sha3_256(data).hexdigest()
