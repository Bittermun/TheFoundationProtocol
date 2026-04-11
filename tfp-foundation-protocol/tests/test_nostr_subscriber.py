"""
Tests for NostrSubscriber.

Covers:
- offline mode lifecycle (start/stop, no network calls)
- _handle_message parsing for all NIP-01 message types
- on_event callback invocation and exception isolation
- in-memory event log (get_received / clear_received)
- mocked WebSocket connect-subscribe-receive cycle
"""

import json
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from tfp_client.lib.bridges.nostr_bridge import TFP_CONTENT_KIND
from tfp_client.lib.bridges.nostr_subscriber import NostrSubscriber, _SUB_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(content_hash: str = "a" * 64) -> Dict[str, Any]:
    return {
        "id": "e" * 64,
        "pubkey": "p" * 64,
        "created_at": 1_700_000_000,
        "kind": TFP_CONTENT_KIND,
        "tags": [["t", "tfp"]],
        "content": json.dumps({"hash": content_hash, "title": "Test"}),
        "sig": "s" * 128,
    }


def _event_msg(content_hash: str = "a" * 64) -> str:
    return json.dumps(["EVENT", _SUB_ID, _make_event(content_hash)])


# ---------------------------------------------------------------------------
# Lifecycle (offline mode — no network)
# ---------------------------------------------------------------------------

class TestLifecycleOffline:
    def test_not_running_before_start(self):
        sub = NostrSubscriber(offline=True)
        assert not sub.is_running()

    def test_offline_thread_exits_immediately(self):
        sub = NostrSubscriber(offline=True)
        sub.start()
        time.sleep(0.15)
        # Thread should have exited after _run_loop returned due to offline=True
        assert not sub.is_running()

    def test_stop_noop_when_not_started(self):
        sub = NostrSubscriber(offline=True)
        sub.stop()  # must not raise

    def test_double_start_does_not_spawn_extra_thread(self):
        sub = NostrSubscriber(offline=False)
        sub._stop_event.set()  # prevent real connection attempt
        sub.start()
        thread_id = id(sub._thread)
        sub.start()  # second call while alive
        assert id(sub._thread) == thread_id
        sub.stop()


# ---------------------------------------------------------------------------
# _handle_message: event parsing
# ---------------------------------------------------------------------------

class TestHandleMessage:
    def test_tfp_event_triggers_callback(self):
        received = []
        sub = NostrSubscriber(offline=True, on_event=received.append)
        sub._handle_message(_event_msg())
        assert len(received) == 1
        assert received[0]["kind"] == TFP_CONTENT_KIND

    def test_tfp_event_stored_in_received(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message(_event_msg("b" * 64))
        assert len(sub.get_received()) == 1
        assert sub.get_received()[0]["kind"] == TFP_CONTENT_KIND

    def test_non_tfp_kind_ignored(self):
        received = []
        sub = NostrSubscriber(offline=True, on_event=received.append)
        event = _make_event()
        event["kind"] = 1  # regular text note
        sub._handle_message(json.dumps(["EVENT", _SUB_ID, event]))
        assert received == []
        assert sub.get_received() == []

    def test_eose_message_does_not_trigger_callback(self):
        received = []
        sub = NostrSubscriber(offline=True, on_event=received.append)
        sub._handle_message(json.dumps(["EOSE", _SUB_ID]))
        assert received == []

    def test_notice_message_does_not_trigger_callback(self):
        received = []
        sub = NostrSubscriber(offline=True, on_event=received.append)
        sub._handle_message(json.dumps(["NOTICE", "rate limited"]))
        assert received == []

    def test_malformed_json_ignored(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message("{not valid json!!}")
        assert sub.get_received() == []

    def test_empty_list_ignored(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message("[]")
        assert sub.get_received() == []

    def test_non_list_json_ignored(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message('{"msg": "hello"}')
        assert sub.get_received() == []

    def test_event_with_non_dict_payload_ignored(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message(json.dumps(["EVENT", _SUB_ID, "not-a-dict"]))
        assert sub.get_received() == []

    def test_multiple_events_all_logged(self):
        sub = NostrSubscriber(offline=True)
        for i in range(5):
            sub._handle_message(_event_msg(f"{i:064d}"))
        assert len(sub.get_received()) == 5

    def test_callback_exception_does_not_crash_subscriber(self):
        def bad_callback(_evt):
            raise RuntimeError("callback exploded")

        sub = NostrSubscriber(offline=True, on_event=bad_callback)
        sub._handle_message(_event_msg())
        # Event must still be stored even though callback raised
        assert len(sub.get_received()) == 1

    def test_get_received_returns_copy(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message(_event_msg())
        copy1 = sub.get_received()
        copy1.clear()
        assert len(sub.get_received()) == 1  # original unaffected

    def test_clear_received(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message(_event_msg())
        sub.clear_received()
        assert sub.get_received() == []


# ---------------------------------------------------------------------------
# Default callback (no-op)
# ---------------------------------------------------------------------------

class TestDefaultCallback:
    def test_no_on_event_does_not_raise(self):
        sub = NostrSubscriber(offline=True)
        sub._handle_message(_event_msg())
        assert len(sub.get_received()) == 1


# ---------------------------------------------------------------------------
# Mocked WebSocket: connect → subscribe → receive → stop
# ---------------------------------------------------------------------------

class TestMockedWebSocket:
    def test_req_message_sent_on_connect(self):
        sub = NostrSubscriber(on_event=lambda e: None)
        sub._stop_event.set()  # stop immediately after first recv attempt

        mock_ws = MagicMock()
        mock_ws.__enter__ = lambda s: s
        mock_ws.__exit__ = MagicMock(return_value=False)
        mock_ws.recv = MagicMock(side_effect=TimeoutError())
        mock_ws.send = MagicMock()

        with patch("websockets.sync.client.connect", return_value=mock_ws):
            sub._connect_and_listen()

        # The first send() should be the REQ subscription message
        first_call_args = mock_ws.send.call_args_list[0][0][0]
        msg = json.loads(first_call_args)
        assert msg[0] == "REQ"
        assert msg[1] == _SUB_ID
        assert msg[2]["kinds"] == [TFP_CONTENT_KIND]

    def test_event_delivered_via_mocked_ws(self):
        received = []
        sub = NostrSubscriber(on_event=received.append)

        call_count = [0]

        def fake_recv(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _event_msg()
            sub._stop_event.set()
            raise TimeoutError()

        mock_ws = MagicMock()
        mock_ws.__enter__ = lambda s: s
        mock_ws.__exit__ = MagicMock(return_value=False)
        mock_ws.recv = fake_recv
        mock_ws.send = MagicMock()

        with patch("websockets.sync.client.connect", return_value=mock_ws):
            sub._stop_event.clear()
            sub._connect_and_listen()

        assert len(received) == 1
        assert received[0]["kind"] == TFP_CONTENT_KIND

    def test_websockets_not_installed_falls_back_gracefully(self):
        sub = NostrSubscriber()
        sub._stop_event.set()

        with patch.dict(
            "sys.modules",
            {
                "websockets": None,
                "websockets.sync": None,
                "websockets.sync.client": None,
            },
        ):
            sub._connect_and_listen()  # must not raise

    def test_close_message_sent_on_stop(self):
        sub = NostrSubscriber(on_event=lambda e: None)

        def fake_recv(timeout=None):
            sub._stop_event.set()
            raise TimeoutError()

        mock_ws = MagicMock()
        mock_ws.__enter__ = lambda s: s
        mock_ws.__exit__ = MagicMock(return_value=False)
        mock_ws.recv = fake_recv
        mock_ws.send = MagicMock()

        with patch("websockets.sync.client.connect", return_value=mock_ws):
            sub._stop_event.clear()
            sub._connect_and_listen()

        # Last send() should be the CLOSE message
        last_call_args = mock_ws.send.call_args_list[-1][0][0]
        msg = json.loads(last_call_args)
        assert msg[0] == "CLOSE"
        assert msg[1] == _SUB_ID
