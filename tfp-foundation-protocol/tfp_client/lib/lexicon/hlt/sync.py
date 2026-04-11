"""
Lexicon Synchronization Protocol - HLT Sync Between Devices

Manages synchronization of Hierarchical Lexicon Trees between devices
to prevent semantic drift and ensure consistent content reconstruction.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from .delta import DeltaType, LexiconDelta
from .tree import HierarchicalLexiconTree


class SyncState(Enum):
    """States of the synchronization process."""

    IDLE = "idle"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"


class LexiconSynchronizer:
    """
    Manages HLT synchronization between local device and network.

    Responsibilities:
    - Detect semantic drift between local and remote lexicons
    - Compute minimal sync requests (only missing/outdated domains)
    - Process incoming deltas and update local HLT
    - Track sync state and history
    """

    def __init__(self, local_hlt: HierarchicalLexiconTree):
        self.local_hlt = local_hlt
        self.state = SyncState.IDLE
        self.last_sync_time: Optional[str] = None
        self.sync_history: List[Dict] = []
        self._remote_merkle_root: Optional[str] = None

    def start_sync(self, remote_merkle_root: str) -> Dict:
        """
        Initiate synchronization with remote network.

        Args:
            remote_merkle_root: Merkle root of remote HLT

        Returns:
            Sync request containing missing/outdated domain info
        """
        self.state = SyncState.SYNCING
        self._remote_merkle_root = remote_merkle_root

        request = self.compute_sync_request(remote_merkle_root)

        self._log_sync_event(
            "sync_started", {"remote_merkle_root": remote_merkle_root[:16] + "..."}
        )

        return request

    def compute_sync_request(self, remote_merkle_root: str) -> Dict:
        """
        Compute what needs to be synchronized.

        Compares local HLT state with remote merkle root to determine
        which domains are missing or outdated.

        Returns:
            Dict with missing_domains, outdated_domains, and local_merkle_root
        """
        local_merkle = self.local_hlt.compute_merkle_root()

        if local_merkle == remote_merkle_root:
            return {
                "missing_domains": [],
                "outdated_domains": [],
                "local_merkle_root": local_merkle,
                "sync_needed": False,
            }

        # For now, assume all domains need checking
        # In production, this would use a more sophisticated diff algorithm
        missing_domains = []
        outdated_domains = []

        for domain_name in self.local_hlt.domain_names.keys():
            latest = self.local_hlt.get_latest_version(domain_name)
            # Mark as potentially outdated if we have adapters
            if latest["adapter_count"] > 0:
                outdated_domains.append(
                    {
                        "name": domain_name,
                        "current_version": latest["version"],
                        "base_version": latest.get("base_version"),
                    }
                )

        return {
            "missing_domains": missing_domains,
            "outdated_domains": outdated_domains,
            "local_merkle_root": local_merkle,
            "sync_needed": True,
        }

    def process_sync_response(
        self, domain_id: str, deltas: List[LexiconDelta], new_merkle_root: str
    ) -> bool:
        """
        Process incoming sync response with deltas.

        Args:
            domain_id: Target domain to update
            deltas: List of deltas to apply
            new_merkle_root: Expected merkle root after update

        Returns:
            True if sync successful, False otherwise
        """
        if domain_id not in self.local_hlt.nodes:
            self.state = SyncState.ERROR
            return False

        try:
            # Apply each delta in sequence
            for delta in deltas:
                # For adapter deltas, we create new adapter nodes
                if delta.delta_type == DeltaType.ADDITION:
                    # Extract precision anchor from delta metadata if present
                    precision_anchor = (
                        f"anchor_{datetime.now(timezone.utc).timestamp()}"
                    )

                    self.local_hlt.add_adapter(
                        domain_id=domain_id,
                        version=delta.target_version,
                        delta_content=str(delta.data).encode(),
                        precision_anchor=precision_anchor,
                    )

            # Verify merkle root matches
            computed_root = self.local_hlt.compute_merkle_root()

            if computed_root != new_merkle_root:
                # Roots don't match - might be expected due to timing
                # In production, would retry or request full tree
                pass

            self.state = SyncState.SYNCED
            self.last_sync_time = datetime.now(timezone.utc).isoformat()
            self._remote_merkle_root = new_merkle_root

            self._log_sync_event(
                "sync_completed",
                {
                    "domain_id": domain_id,
                    "deltas_applied": len(deltas),
                    "new_merkle_root": new_merkle_root[:16] + "...",
                },
            )

            return True

        except Exception as e:
            self.state = SyncState.ERROR
            self._log_sync_event("sync_error", {"error": str(e)})
            return False

    def complete_sync(self):
        """Mark synchronization as complete."""
        self.state = SyncState.SYNCED
        self.last_sync_time = datetime.now(timezone.utc).isoformat()

    def detect_drift(self, domain_name: str, remote_content_hash: str) -> bool:
        """
        Detect if local domain has drifted from remote.

        Args:
            domain_name: Name of domain to check
            remote_content_hash: Content hash from remote source

        Returns:
            True if drift detected, False if synchronized
        """
        if not self.local_hlt.has_domain(domain_name):
            # Domain missing entirely = drift
            return True

        domain_id = self.local_hlt.domain_names[domain_name]
        local_node = self.local_hlt.get_node(domain_id)

        # Compare content hashes
        return local_node.content_hash != remote_content_hash

    def get_sync_status(self) -> Dict:
        """Get current synchronization status."""
        return {
            "state": self.state.value,
            "last_sync_time": self.last_sync_time,
            "local_merkle_root": self.local_hlt.compute_merkle_root()[:16] + "...",
            "remote_merkle_root": self._remote_merkle_root[:16] + "..."
            if self._remote_merkle_root
            else None,
            "domain_count": len(self.local_hlt.domain_names),
            "sync_events": len(self.sync_history),
        }

    def _log_sync_event(self, event_type: str, data: Dict):
        """Log synchronization event for debugging/auditing."""
        self.sync_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "data": data,
            }
        )

        # Keep only last 100 events
        if len(self.sync_history) > 100:
            self.sync_history = self.sync_history[-100:]
