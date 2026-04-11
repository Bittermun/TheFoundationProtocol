"""
Gateway Scheduler - Broadcast slot scheduling with credit-based bidding

Receives aggregated demand from mesh nodes, calculates bids,
and schedules broadcast slots based on demand and credits.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from tfp_client.lib.publish.mesh_aggregator import MeshAggregator


@dataclass
class BroadcastSlot:
    """A scheduled broadcast slot."""

    slot_id: int
    epoch: int  # Time epoch (e.g., hour number)
    content_hash: str
    bid_amount: int  # Credits bid
    demand_score: float
    status: str = "scheduled"  # scheduled, broadcasted, cancelled
    scheduled_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "epoch": self.epoch,
            "content_hash": self.content_hash,
            "bid_amount": self.bid_amount,
            "demand_score": self.demand_score,
            "status": self.status,
            "scheduled_at": self.scheduled_at,
        }


class GatewayScheduler:
    """
    Schedules broadcast slots based on demand and credit bids.

    Usage:
        scheduler = GatewayScheduler()
        scheduler.receive_aggregated_demand(demand_data)
        bid = scheduler.calculate_bid(hash_hex, demand_score)
        slot = scheduler.schedule_broadcast_slot(hash_hex, bid, epoch)
        schedule = scheduler.get_schedule(epoch)
    """

    def __init__(self, base_credit_rate: int = 100, max_slots_per_epoch: int = 10):
        """
        Initialize gateway scheduler.

        Args:
            base_credit_rate: Base credit cost per slot (default 100)
            max_slots_per_epoch: Maximum slots per epoch (default 10)
        """
        self._base_credit_rate = base_credit_rate
        self._max_slots_per_epoch = max_slots_per_epoch
        self._slots: Dict[int, List[BroadcastSlot]] = defaultdict(
            list
        )  # epoch -> slots
        self._pending_bids: Dict[str, Dict[str, Any]] = {}  # hash -> bid info
        self._next_slot_id: int = 0
        self._current_load: Dict[int, float] = defaultdict(
            float
        )  # epoch -> load factor

    def receive_aggregated_demand(self, demand_data: bytes) -> Dict[str, Any]:
        """
        Receive aggregated demand from mesh aggregator.

        Args:
            demand_data: Serialized demand data from MeshAggregator.export_for_gateway()

        Returns:
            Deserialized demand dict
        """
        import json

        data = json.loads(demand_data.decode("utf-8"))

        # Store pending bids for each content
        if "demand" in data:
            for hash_hex, info in data["demand"].items():
                self._pending_bids[hash_hex] = {
                    "demand_score": info.get("demand_score", 0.0),
                    "request_count": info.get("request_count", 0),
                    "metadata": info.get("metadata", {}),
                    "region": data.get("region", "unknown"),
                    "received_at": time.time(),
                }

        return data

    def calculate_bid(
        self,
        content_hash: str,
        demand_score: float,
        content_size: int = 0,
        current_load: float = 0.0,
    ) -> int:
        """
        Calculate credit bid for a content item.

        Formula:
            base_bid = demand_score * base_credit_rate
            size_penalty = content_size / 1_000_000  # 1 credit per MB
            load_multiplier = 1.0 / (1.0 + current_load)
            final_bid = base_bid * (1 + size_penalty) * load_multiplier

        Args:
            content_hash: Content identifier
            demand_score: Normalized demand score (0.0 to 1.0)
            content_size: Size in bytes (optional, affects bid)
            current_load: Current scheduler load factor (0.0 = idle, 1.0 = full)

        Returns:
            Credit bid amount (integer)
        """
        # Base bid from demand
        base_bid = demand_score * self._base_credit_rate

        # Size penalty (larger content costs more)
        size_penalty = content_size / 1_000_000  # Normalize to MB

        # Load multiplier (reduce bids when busy to prevent overload)
        load_multiplier = 1.0 / (1.0 + current_load)

        # Calculate final bid
        final_bid = int(base_bid * (1 + size_penalty) * load_multiplier)

        # Minimum bid of 1 credit
        return max(1, final_bid)

    def schedule_broadcast_slot(
        self, content_hash: str, bid: int, epoch: int
    ) -> Optional[BroadcastSlot]:
        """
        Schedule a broadcast slot for content.

        Args:
            content_hash: Content hash to schedule
            bid: Credit bid amount
            epoch: Time epoch for scheduling

        Returns:
            BroadcastSlot if scheduled, None if slot limit reached
        """
        # Check slot limit
        if len(self._slots[epoch]) >= self._max_slots_per_epoch:
            return None

        # Get demand score from pending bids
        demand_score = 0.0
        if content_hash in self._pending_bids:
            demand_score = self._pending_bids[content_hash].get("demand_score", 0.0)

        # Create slot
        slot = BroadcastSlot(
            slot_id=self._next_slot_id,
            epoch=epoch,
            content_hash=content_hash,
            bid_amount=bid,
            demand_score=demand_score,
        )

        self._slots[epoch].append(slot)
        self._next_slot_id += 1

        # Update load factor
        self._current_load[epoch] = len(self._slots[epoch]) / self._max_slots_per_epoch

        return slot

    def schedule_from_demand(
        self, epoch: int, max_slots: Optional[int] = None
    ) -> List[BroadcastSlot]:
        """
        Automatically schedule top demand content for an epoch.

        Sorts pending bids by demand score and schedules top items.

        Args:
            epoch: Time epoch to schedule
            max_slots: Override max slots for this call (default: self._max_slots_per_epoch)

        Returns:
            List of scheduled BroadcastSlot objects
        """
        if max_slots is None:
            max_slots = self._max_slots_per_epoch

        # Sort pending bids by demand score
        sorted_bids = sorted(
            self._pending_bids.items(), key=lambda x: x[1]["demand_score"], reverse=True
        )

        scheduled = []
        slots_available = max_slots - len(self._slots[epoch])

        for hash_hex, bid_info in sorted_bids[:slots_available]:
            # Calculate bid
            credit_bid = self.calculate_bid(hash_hex, bid_info["demand_score"])

            # Schedule slot
            slot = self.schedule_broadcast_slot(hash_hex, credit_bid, epoch)
            if slot:
                scheduled.append(slot)
                # Remove from pending
                del self._pending_bids[hash_hex]

        return scheduled

    def get_schedule(self, epoch: int) -> List[Dict[str, Any]]:
        """
        Get broadcast schedule for an epoch.

        Args:
            epoch: Time epoch

        Returns:
            List of slot dicts, sorted by slot_id
        """
        slots = self._slots.get(epoch, [])
        return sorted([s.to_dict() for s in slots], key=lambda x: x["slot_id"])

    def get_slot(self, epoch: int, slot_id: int) -> Optional[Dict[str, Any]]:
        """
        Get specific slot details.

        Args:
            epoch: Time epoch
            slot_id: Slot identifier

        Returns:
            Slot dict or None if not found
        """
        for slot in self._slots.get(epoch, []):
            if slot.slot_id == slot_id:
                return slot.to_dict()
        return None

    def cancel_slot(self, epoch: int, slot_id: int) -> bool:
        """
        Cancel a scheduled slot.

        Args:
            epoch: Time epoch
            slot_id: Slot to cancel

        Returns:
            True if cancelled, False if not found
        """
        for slot in self._slots.get(epoch, []):
            if slot.slot_id == slot_id:
                slot.status = "cancelled"
                return True
        return False

    def mark_broadcasted(self, epoch: int, slot_id: int) -> bool:
        """
        Mark a slot as broadcasted.

        Args:
            epoch: Time epoch
            slot_id: Slot to mark

        Returns:
            True if marked, False if not found
        """
        for slot in self._slots.get(epoch, []):
            if slot.slot_id == slot_id:
                slot.status = "broadcasted"
                return True
        return False

    def get_epoch_load(self, epoch: int) -> float:
        """
        Get load factor for an epoch.

        Args:
            epoch: Time epoch

        Returns:
            Load factor (0.0 to 1.0)
        """
        return self._current_load.get(epoch, 0.0)

    def get_available_slots(self, epoch: int) -> int:
        """
        Get number of available slots in an epoch.

        Args:
            epoch: Time epoch

        Returns:
            Number of available slots
        """
        used = len(self._slots.get(epoch, []))
        return max(0, self._max_slots_per_epoch - used)

    def clear_epoch(self, epoch: int) -> int:
        """
        Clear all slots for an epoch (after broadcast completion).

        Args:
            epoch: Time epoch to clear

        Returns:
            Number of cleared slots
        """
        count = len(self._slots.get(epoch, []))
        if epoch in self._slots:
            del self._slots[epoch]
        if epoch in self._current_load:
            del self._current_load[epoch]
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        total_slots = sum(len(slots) for slots in self._slots.values())
        broadcasted = sum(
            1
            for slots in self._slots.values()
            for slot in slots
            if slot.status == "broadcasted"
        )

        return {
            "total_slots_scheduled": total_slots,
            "total_broadcasted": broadcasted,
            "pending_bids": len(self._pending_bids),
            "epochs_with_slots": list(self._slots.keys()),
            "avg_load": sum(self._current_load.values()) / len(self._current_load)
            if self._current_load
            else 0.0,
        }

    def export_schedule(self, epoch: int) -> bytes:
        """
        Export schedule for transmission.

        Args:
            epoch: Time epoch

        Returns:
            Serialized schedule (JSON bytes)
        """
        import json

        schedule = self.get_schedule(epoch)
        return json.dumps(
            {"epoch": epoch, "slots": schedule, "load": self.get_epoch_load(epoch)}
        ).encode("utf-8")

    @classmethod
    def import_schedule(cls, data: bytes) -> Dict[str, Any]:
        """
        Import schedule data.

        Args:
            data: Serialized schedule

        Returns:
            Deserialized schedule dict
        """
        import json

        return json.loads(data.decode("utf-8"))

    def schedule_from_aggregator(
        self,
        aggregator: "MeshAggregator",
        epoch: int,
        max_slots: Optional[int] = None,
    ) -> List[BroadcastSlot]:
        """
        Schedule broadcast slots using live demand signals from a MeshAggregator.

        Pulls top-demand content items directly from ``aggregator.get_top_demand()``,
        loads them into the pending bid queue, then schedules slots for the given
        epoch in demand-score order (highest demand gets a slot first).

        After scheduling, demand counters for the scheduled items are reset in the
        aggregator so they are not double-counted in the next scheduling cycle.

        Args:
            aggregator: MeshAggregator with current demand signals.
            epoch: Time epoch to schedule slots for.
            max_slots: Override max slots per epoch (default: self._max_slots_per_epoch).

        Returns:
            List of scheduled BroadcastSlot objects, ordered by demand score descending.
        """
        limit = max_slots if max_slots is not None else self._max_slots_per_epoch
        top_demand = aggregator.get_top_demand(limit=limit)

        for entry in top_demand:
            hash_hex = entry["hash"]
            self._pending_bids[hash_hex] = {
                "demand_score": entry["demand_score"],
                "request_count": entry["request_count"],
                "metadata": entry["metadata"],
                "region": aggregator._region,
                "received_at": time.time(),
            }

        scheduled = self.schedule_from_demand(epoch, max_slots)

        # Reset demand for scheduled items to avoid double-counting
        for slot in scheduled:
            aggregator.reset_demand(slot.content_hash)

        return scheduled
