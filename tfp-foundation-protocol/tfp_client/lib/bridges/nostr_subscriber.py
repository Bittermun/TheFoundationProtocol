# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
NostrSubscriber - NIP-01 Nostr event subscriber for TFP content discovery.

Listens to a Nostr relay for TFP events of the following kinds:
- **kind 30078** (``TFP_CONTENT_KIND``) — HLT Merkle-root gossip
- **kind 30079** (``TFP_SEARCH_INDEX_KIND``) — semantic search index summary
- **kind 30080** (``TFP_CONTENT_ANNOUNCE_KIND``) — content-availability announcements

For each received event the ``on_event`` callback is invoked in the
subscriber thread.  The raw event dict (NIP-01 format) is also appended to an
in-memory log accessible via :meth:`get_received`.

This completes the NostrBridge round-trip:

    NostrBridge (publisher) ─── relay ──> NostrSubscriber (receiver)
    "Announce content/HLT"                "Update tag index / HLT"

The subscriber runs in a background daemon thread and reconnects automatically
if the relay connection drops.

Usage::

    def on_tfp_event(event: dict) -> None:
        payload = json.loads(event["content"])
        tag_index.add(payload["hash"], payload.get("title", ""))

    sub = NostrSubscriber(relay_url="wss://relay.damus.io", on_event=on_tfp_event)
    sub.start()
    # ... later ...
    sub.stop()

Offline mode (no relay required; useful for testing)::

    sub = NostrSubscriber(offline=True, on_event=my_callback)
    sub.start()   # thread exits immediately; callback can be triggered via _handle_message
"""

import collections
import json
import logging
import random
import threading
from typing import Any, Callable, Dict, List, Optional

from tfp_client.lib.bridges.nostr_bridge import (
    TFP_CONTENT_KIND,
    TFP_CONTENT_ANNOUNCE_KIND,
    TFP_SEARCH_INDEX_KIND,
)

logger = logging.getLogger(__name__)

# NIP-01 subscription identifier used in REQ / CLOSE messages
_SUB_ID = "tfp-content-discovery"

# Default NIP-01 filter: HLT gossip (30078), search-index summaries (30079),
# content-availability announcements (30080), and supply gossip (30081).
_DEFAULT_FILTER: Dict[str, Any] = {
    "kinds": [
        TFP_CONTENT_KIND,
        TFP_SEARCH_INDEX_KIND,
        TFP_CONTENT_ANNOUNCE_KIND,
        30081,  # TFP_SUPPLY_GOSSIP_KIND
    ]
}


class NostrSubscriber:
    """
    Background subscriber that listens for TFP content announcements on a Nostr relay.

    Subscribes to three TFP event kinds by default:
    - **30078** (``TFP_CONTENT_KIND``) — HLT Merkle-root gossip
    - **30079** (``TFP_SEARCH_INDEX_KIND``) — semantic search index summary
    - **30080** (``TFP_CONTENT_ANNOUNCE_KIND``) — content-availability announcements

    For each received event the ``on_event`` callback is invoked in the
    subscriber thread.  The raw event dict (NIP-01 format) is also appended to an
    in-memory log accessible via :meth:`get_received`.

    Args:
        relay_url: WebSocket URL of the Nostr relay.
        on_event: Callback invoked for each valid TFP event dict received.
        filters: NIP-01 filter dict (default: ``{"kinds": [30078, 30079, 30080]}``).
        reconnect_delay: Initial seconds to wait before reconnecting after an error.
        max_reconnect_delay: Maximum seconds to wait between reconnection attempts.
        backoff_factor: Multiplier for exponential backoff (default: 2.0).
        offline: If ``True``, skip all network calls (useful for unit tests).
    """

    def __init__(
        self,
        relay_url: str = "wss://relay.damus.io",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        filters: Optional[Dict[str, Any]] = None,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
        backoff_factor: float = 2.0,
        offline: bool = False,
    ):
        self.relay_url = relay_url
        self._on_event: Callable[[Dict[str, Any]], None] = on_event or (lambda _: None)
        self._filters: Dict[str, Any] = (
            filters if filters is not None else dict(_DEFAULT_FILTER)
        )
        self._initial_reconnect_delay = reconnect_delay
        self._current_reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._backoff_factor = backoff_factor
        self.offline = offline

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Bounded event log: deque evicts oldest entries when full so that a
        # relay flooding the subscriber cannot exhaust heap memory.
        self._received: collections.deque = collections.deque(maxlen=10_000)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background subscriber thread (no-op if already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="nostr-subscriber"
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the subscriber to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        """Return ``True`` if the subscriber thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def get_received(self) -> List[Dict[str, Any]]:
        """Return a copy of all TFP events received so far."""
        return list(self._received)

    def clear_received(self) -> None:
        """Clear the in-memory event log."""
        self._received.clear()

    # ------------------------------------------------------------------
    # Internal: run loop and message handling
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main loop: connect, subscribe, receive; reconnect on error."""
        if self.offline:
            logger.debug("NostrSubscriber: offline mode, skipping network")
            return

        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
                # Reset backoff on successful connection
                self._reset_backoff()
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "NostrSubscriber: relay error (%s), reconnecting in %.1fs",
                    exc,
                    self._current_reconnect_delay,
                )
                self._stop_event.wait(timeout=self._current_reconnect_delay)
                # Exponential backoff with jitter
                self._increase_backoff()

    def _reset_backoff(self) -> None:
        """Reset reconnection delay to initial value after successful connection."""
        self._current_reconnect_delay = self._initial_reconnect_delay

    def _increase_backoff(self) -> None:
        """Increase reconnection delay exponentially (deterministic)."""
        # Calculate next delay with exponential backoff
        next_delay = self._current_reconnect_delay * self._backoff_factor
        # Cap at maximum delay
        self._current_reconnect_delay = min(next_delay, self._max_reconnect_delay)

    def _connect_and_listen(self) -> None:
        """Connect to relay, send REQ, and process incoming messages until stopped."""
        try:
            import websockets.sync.client as _ws_sync  # websockets >= 11
        except ImportError:
            logger.debug(
                "NostrSubscriber: websockets not installed; cannot connect to relay"
            )
            self._stop_event.wait(timeout=self._current_reconnect_delay)
            return

        req_msg = json.dumps(["REQ", _SUB_ID, self._filters], separators=(",", ":"))
        with _ws_sync.connect(self.relay_url, open_timeout=10) as ws:
            ws.send(req_msg)
            logger.debug("NostrSubscriber: subscribed to %s", self.relay_url)
            # Reset backoff immediately after successful connection
            self._reset_backoff()

            while not self._stop_event.is_set():
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                self._handle_message(raw)

            # Graceful NIP-01 CLOSE before disconnecting
            try:
                ws.send(json.dumps(["CLOSE", _SUB_ID], separators=(",", ":")))
            except Exception:
                pass

    def _handle_message(self, raw: str) -> None:
        """Parse a NIP-01 message and invoke the callback for TFP EVENT messages."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(msg, list) or len(msg) < 2:
            return

        msg_type = msg[0]
        if msg_type == "EVENT" and len(msg) >= 3:
            event_dict = msg[2]
            if not isinstance(event_dict, dict):
                return
            subscribed_kinds = set(self._filters.get("kinds", []))
            if subscribed_kinds and event_dict.get("kind") not in subscribed_kinds:
                return

            # Note: Timestamp/replay validation is handled by the server's
            # _check_replay_window when events are processed. We deliver all
            # syntactically valid events to allow the server to make the decision.
            self._received.append(event_dict)
            try:
                self._on_event(event_dict)
            except Exception as exc:
                logger.warning("NostrSubscriber: on_event callback raised: %s", exc)

        elif msg_type == "EOSE":
            logger.debug("NostrSubscriber: EOSE (end of stored events)")

        elif msg_type == "NOTICE":
            notice = msg[1] if len(msg) > 1 else ""
            # NOTICE messages often indicate errors like "invalid event"
            # Log at warning level to make them more visible
            if "invalid" in notice.lower() or "error" in notice.lower():
                logger.warning(
                    "NostrSubscriber: relay notice (may indicate event rejection): %s",
                    notice,
                )
            else:
                logger.info("NostrSubscriber: relay notice: %s", notice)
