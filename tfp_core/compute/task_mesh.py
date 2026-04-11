"""
TFP Compute Mesh - P2P Micro-Task Coordination

Broadcasts task recipes via NDN, collects device bids, and schedules
execution during idle/charging windows. Pure coordination logic;
no central scheduler.
"""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class TaskRecipe:
    """Definition of a micro-task to be executed on the mesh."""

    task_id: str
    difficulty: int  # 1-10 scale
    input_hash: str  # SHA3-256 of input data
    output_schema: Dict  # Expected output structure
    deadline: float  # Unix timestamp
    credit_reward: int
    creator_sig: str  # Creator's signature


@dataclass
class DeviceBid:
    """Bid from a device to execute a task."""

    device_id: str
    task_id: str
    estimated_time: float  # Seconds to complete
    hardware_trust: float  # 0.0-1.0 (from HABP)
    current_load: float  # 0.0-1.0
    battery_level: int  # 0-100
    is_charging: bool
    timestamp: float
    signature: str


@dataclass
class ScheduledTask:
    """A task assigned to a device."""

    task_id: str
    device_id: str
    bid: DeviceBid
    scheduled_time: float
    status: str = "pending"  # pending, running, completed, failed, timeout
    result_hash: Optional[str] = None


class ComputeMesh:
    """
    P2P compute task coordinator.

    In production, NDN interests/announcements would replace
    the in-memory collections here.
    """

    def __init__(self):
        self._tasks: Dict[str, TaskRecipe] = {}
        self._bids: Dict[str, List[DeviceBid]] = defaultdict(list)
        self._scheduled: Dict[str, ScheduledTask] = {}
        self._callbacks: Dict[str, Callable] = {}  # task_id -> completion callback
        self._min_battery = 30  # Minimum battery % to accept tasks
        self._max_temp = 80  # Max temperature (C) to run tasks

    def broadcast_task(self, recipe: TaskRecipe) -> str:
        """
        Broadcast a task recipe to the mesh.

        In production: Publish via NDN /tfp/compute/task/{task_id}
        """
        self._tasks[recipe.task_id] = recipe
        self._bids[recipe.task_id] = []
        return recipe.task_id

    def submit_bid(self, bid: DeviceBid) -> bool:
        """
        Submit a bid to execute a task.

        In production: Announce via NDN /tfp/compute/bid/{task_id}/{device_id}
        """
        if bid.task_id not in self._tasks:
            return False

        task = self._tasks[bid.task_id]
        if time.time() > task.deadline:
            return False

        # Basic safety checks (detailed checks in device_safety)
        if bid.battery_level < self._min_battery:
            return False

        self._bids[bid.task_id].append(bid)
        return True

    def select_winner(self, task_id: str) -> Optional[ScheduledTask]:
        """
        Select the best bid for a task using multi-factor scoring.

        Scoring formula:
          score = hardware_trust × (1 - current_load) × charging_bonus × urgency_factor
        """
        if task_id not in self._tasks or task_id not in self._bids:
            return None

        task = self._tasks[task_id]
        bids = self._bids[task_id]

        if not bids:
            return None

        # Filter unsafe bids
        safe_bids = [
            b
            for b in bids
            if b.battery_level >= self._min_battery and b.hardware_trust > 0.5
        ]

        if not safe_bids:
            return None

        # Score each bid
        def score_bid(bid: DeviceBid) -> float:
            charging_bonus = 1.5 if bid.is_charging else 1.0
            load_penalty = 1.0 - (bid.current_load * 0.5)
            urgency = max(0.1, (task.deadline - time.time()) / 3600)  # Hours left
            urgency_factor = min(2.0, 1.0 / urgency) if urgency < 1.0 else 1.0

            return bid.hardware_trust * load_penalty * charging_bonus * urgency_factor

        best_bid = max(safe_bids, key=score_bid)

        scheduled = ScheduledTask(
            task_id=task_id,
            device_id=best_bid.device_id,
            bid=best_bid,
            scheduled_time=time.time(),
            status="pending",
        )

        self._scheduled[task_id] = scheduled
        return scheduled

    def register_callback(self, task_id: str, callback: Callable) -> None:
        """Register a callback for task completion."""
        self._callbacks[task_id] = callback

    def complete_task(self, task_id: str, result_hash: str, success: bool) -> bool:
        """Mark a task as completed and trigger callback."""
        if task_id not in self._scheduled:
            return False

        task = self._scheduled[task_id]
        task.status = "completed" if success else "failed"
        task.result_hash = result_hash if success else None

        if task_id in self._callbacks:
            try:
                self._callbacks[task_id](task)
            except Exception as e:
                # Log callback errors but don't let them break flow
                log.warning("Callback for task %s failed: %s", task_id, e)

        return True

    def get_task_status(self, task_id: str) -> Optional[str]:
        """Get current status of a task."""
        if task_id in self._scheduled:
            return self._scheduled[task_id].status
        elif task_id in self._tasks:
            return "bidding" if self._bids[task_id] else "awaiting_bids"
        return None

    def get_pending_tasks_count(self) -> int:
        """Get number of tasks awaiting scheduling."""
        return len([t for t in self._scheduled.values() if t.status == "pending"])


def generate_task_id(input_data: bytes, creator_id: str) -> str:
    """Generate a unique task ID from input and creator."""
    data = input_data + creator_id.encode() + str(time.time()).encode()
    return hashlib.sha3_256(data).hexdigest()[:16]
