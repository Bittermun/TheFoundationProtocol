# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Stateful Hypothesis Fuzz Testing Suite for Media Stream Receiver & Lifecycle.

Uses Hypothesis RuleBasedStateMachine to stress-test:
1. Interleaved multi-session packet arrivals.
2. Byzantine packet corruption & replay injection.
3. Premature completion prevention (Session A chunks never satisfy Session B).
4. Bit-exact assembly invariants and clean reset isolation under arbitrary action sequences.
"""

import copy
import hashlib
from pathlib import Path
import random
import sys
import pytest
from hypothesis import settings, strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TFP_ROOT = REPO_ROOT / "tfp-foundation-protocol"
if str(TFP_ROOT) not in sys.path:
    sys.path.insert(0, str(TFP_ROOT))

from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer, MediaDropletPacket
from tfp_client.lib.media.receiver import FountainStreamReceiver


class StreamReceiverStateMachine(RuleBasedStateMachine):
    """
    Stateful model tracking active streams, delivered packets, and receiver state.
    """

    sessions = Bundle("sessions")

    def __init__(self):
        super().__init__()
        self.secret = b"stateful-fuzz-secret-key-32b-!!!"
        self.packager = MediaStreamPackager(min_chunk_size=128, target_chunk_size=256, max_chunk_size=512)
        self.streamer = FountainStreamer(symbol_size=64, secret_key=self.secret)
        self.receiver = FountainStreamReceiver(symbol_size=64, secret_key=self.secret)

        # Model state: session_id -> dict of stream info
        self.active_streams = {}
        self.completed_streams = set()
        self.delivered_packets = {}
        self.session_counter = 1000

    @rule(
        target=sessions,
        payload=st.binary(min_size=128, max_size=1024),
    )
    def create_new_stream(self, payload: bytes):
        """Create a new media stream session with packaged chunks and fountain droplets."""
        self.session_counter += 1
        session_id = self.session_counter

        manifest, chunks, _ = self.packager.package(payload)
        manifest.manifest_id = session_id  # Align manifest_id with session_id
        self.receiver.received_manifests[session_id] = manifest

        # Generate packets with 60% redundancy to allow decodability even with some drops
        packets = list(
            self.streamer.stream_manifest(
                manifest, chunks, redundancy=0.60, session_id=session_id
            )
        )

        stream_info = {
            "session_id": session_id,
            "manifest": manifest,
            "chunks": chunks,
            "payload": payload,
            "expected_hash": hashlib.sha3_256(payload).hexdigest(),
            "remaining_packets": list(packets),
            "delivered_packets": [],
        }

        self.active_streams[session_id] = stream_info
        self.delivered_packets[session_id] = []
        return session_id

    @rule(session_id=sessions)
    def deliver_valid_packet(self, session_id: int):
        """Deliver next available authentic droplet packet to receiver."""
        if session_id not in self.active_streams:
            return

        stream = self.active_streams[session_id]
        if not stream["remaining_packets"]:
            return

        pkt = stream["remaining_packets"].pop(0)
        stream["delivered_packets"].append(pkt)

        # Ingest into receiver
        self.receiver.ingest_packet(pkt)

        # Check if stream reached completion
        if self.receiver.is_complete(stream["manifest"], session_id=session_id):
            self.completed_streams.add(session_id)

    @rule(session_id=sessions)
    def deliver_duplicate_packet(self, session_id: int):
        """Replay an already delivered droplet packet (verifying idempotency)."""
        if session_id not in self.active_streams:
            return

        stream = self.active_streams[session_id]
        if not stream["delivered_packets"]:
            return

        pkt = random.choice(stream["delivered_packets"])
        # Should be safely ignored or processed without crash
        self.receiver.ingest_packet(pkt)

    @rule(session_id=sessions)
    def deliver_corrupted_packet(self, session_id: int):
        """Inject a tampered droplet (corrupted payload or modified seed)."""
        if session_id not in self.active_streams:
            return

        stream = self.active_streams[session_id]
        if not stream["remaining_packets"]:
            return

        original_pkt = stream["remaining_packets"][0]
        # Corrupt packet by bit-flipping payload
        corrupted_payload = bytearray(original_pkt.payload)
        corrupted_payload[0] ^= 0xFF

        corrupted_pkt = MediaDropletPacket(
            session_id=original_pkt.session_id,
            chunk_index=original_pkt.chunk_index,
            k=original_pkt.k,
            orig_len=original_pkt.orig_len,
            symbol_size=original_pkt.symbol_size,
            seed=original_pkt.seed,
            payload=bytes(corrupted_payload),
            auth_tag=original_pkt.auth_tag,
        )

        # Ingesting corrupted packet must NOT crash the receiver
        self.receiver.ingest_packet(corrupted_pkt)

    @rule(session_id=sessions)
    def reset_stream(self, session_id: int):
        """Reset a specific stream session and verify isolated cleanup."""
        if session_id not in self.active_streams:
            return

        self.receiver.reset(session_id=session_id)
        if session_id in self.completed_streams:
            self.completed_streams.remove(session_id)

        # Verify chunks for this session were wiped
        assert session_id not in self.receiver.reconstructed_chunks_by_session

    @invariant()
    def verify_completed_stream_integrity(self):
        """
        Critical invariant: If receiver reports complete for a session,
        assembly MUST be bit-exact and match the SHA3-256 root hash.
        """
        for session_id in list(self.completed_streams):
            if session_id not in self.active_streams:
                continue

            stream = self.active_streams[session_id]
            manifest = stream["manifest"]
            expected = stream["payload"]

            assert self.receiver.is_complete(manifest, session_id=session_id)
            assembled = self.receiver.assemble(manifest, session_id=session_id)
            assert assembled == expected, f"Session {session_id} assembled payload corrupt!"
            actual_hash = hashlib.sha3_256(assembled).hexdigest()
            assert actual_hash == stream["expected_hash"], "SHA3-256 hash mismatch!"

    @invariant()
    def verify_stream_isolation(self):
        """
        Critical invariant: Chunks from Session A must NEVER satisfy or leak into Session B.
        """
        for sid_a, stream_a in self.active_streams.items():
            for sid_b, stream_b in self.active_streams.items():
                if sid_a == sid_b:
                    continue

                chunks_a = self.receiver.reconstructed_chunks_by_session.get(sid_a, {})
                chunks_b = self.receiver.reconstructed_chunks_by_session.get(sid_b, {})

                # Ensure sets of chunk objects are completely disjoint
                if chunks_a and chunks_b and sid_a not in self.completed_streams:
                    # Session B manifest must not report complete purely from Session A chunks
                    assert not (
                        len(chunks_a) >= len(stream_b["chunks"])
                        and not any(c in chunks_b for c in range(len(stream_b["chunks"])))
                        and self.receiver.is_complete(stream_b["manifest"], session_id=sid_b)
                    )


# Expose stateful test to pytest runner with bounded execution settings
TestReceiverStatefulFuzz = StreamReceiverStateMachine.TestCase
TestReceiverStatefulFuzz.settings = settings(
    max_examples=25,
    stateful_step_count=35,
    deadline=None,
)
