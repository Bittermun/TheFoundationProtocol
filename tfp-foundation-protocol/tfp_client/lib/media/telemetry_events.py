# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Protocol Telemetry & Real-Time Event Bus for TFP v4.0.

Streams granular, micro-events (FastCDC chunking, Merkle verification,
Fountain droplet transmission/drops, and GF(2) matrix pivot progress)
to local dashboards, terminal TUIs, and visualizers with zero network overhead.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
import json
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Set


# Core Protocol Event Types
EVENT_CDC_CHUNK = "cdc_chunk"           # FastCDC cut point identified
EVENT_MERKLE_NODE = "merkle_node"       # Merkle tree node hashed or verified
EVENT_DROPLET_EMIT = "droplet_emit"     # Broadcaster generated droplet
EVENT_DROPLET_RECV = "droplet_recv"     # Receiver ingested droplet (or dropped)
EVENT_MATRIX_PIVOT = "matrix_pivot"     # GF(2) Gaussian elimination pivot update
EVENT_CHUNK_SOLVED = "chunk_solved"     # Rank K reached; chunk reconstructed
EVENT_SLIDE_RENDER = "slide_render"     # Presentation template rendered


@dataclass(frozen=True)
class TelemetryEvent:
    """A single immutable protocol lifecycle event."""

    event_type: str
    timestamp_ms: float
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.event_type,
            "t": round(self.timestamp_ms, 2),
            "data": self.data,
        })


class TelemetryEventBus:
    """
    High-throughput, non-blocking telemetry event bus.
    Maintains a circular history buffer and fans out events to async queues
    and sync callbacks.
    """

    _instance: Optional[TelemetryEventBus] = None
    _lock = threading.Lock()

    def __init__(self, history_size: int = 500):
        self.history_size = history_size
        self._history: Deque[TelemetryEvent] = deque(maxlen=history_size)
        self._callbacks: Set[Callable[[TelemetryEvent], None]] = set()
        self._async_queues: Set[asyncio.Queue] = set()
        self._sync_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TelemetryEventBus:
        """Get singleton event bus instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def emit(self, event_type: str, **data) -> TelemetryEvent:
        """Emit an event to all active listeners and record in history."""
        event = TelemetryEvent(
            event_type=event_type,
            timestamp_ms=time.time() * 1000.0,
            data=data,
        )

        with self._sync_lock:
            self._history.append(event)
            # Notify synchronous callbacks
            for cb in list(self._callbacks):
                try:
                    cb(event)
                except Exception:
                    pass

            # Notify async queues
            for q in list(self._async_queues):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

        return event

    def subscribe(self, callback: Callable[[TelemetryEvent], None]):
        """Subscribe a synchronous callback."""
        with self._sync_lock:
            self._callbacks.add(callback)

    def unsubscribe(self, callback: Callable[[TelemetryEvent], None]):
        """Unsubscribe a synchronous callback."""
        with self._sync_lock:
            self._callbacks.discard(callback)

    def create_async_subscription(self) -> asyncio.Queue:
        """Create an asyncio queue receiving real-time events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._sync_lock:
            self._async_queues.add(q)
        return q

    def remove_async_subscription(self, q: asyncio.Queue):
        """Remove an asyncio subscription queue."""
        with self._sync_lock:
            self._async_queues.discard(q)

    def get_recent_events(self, count: int = 100) -> List[TelemetryEvent]:
        """Return the most recent N events from the circular buffer."""
        with self._sync_lock:
            return list(self._history)[-count:]

    def clear(self):
        """Reset the history buffer."""
        with self._sync_lock:
            self._history.clear()
