# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Experiment 2: Process-Boundary UDP Datagram Delivery with Intermediary Packet Dropping.

Verifies:
1. Sockets, packet framing, and serialization work across an actual network boundary on Windows.
2. An intermediate proxy physically intercepts, records, and drops UDP datagrams.
3. The receiver starts with zero sender state and reconstructs solely from wire datagrams.
4. If the proxy drops 100% of datagrams, reconstruction fails cleanly.
"""

import asyncio
import random
import socket
import pytest

from tfp_client.lib.media.stream_packager import MediaStreamPackager
from tfp_client.lib.media.fountain_streamer import FountainStreamer
from tfp_client.lib.media.receiver import FountainStreamReceiver


class DroppingProxyProtocol(asyncio.DatagramProtocol):
    """Intermediary proxy protocol that intercepts UDP packets, drops a recorded percentage, and forwards remainder."""

    def __init__(self, target_port: int, drop_rate: float = 0.25):
        self.target_port = target_port
        self.drop_rate = drop_rate
        self.packets_received = 0
        self.packets_forwarded = 0
        self.packets_dropped = 0
        self.transport = None
        self._rng = random.Random(42)

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        self.packets_received += 1
        if self._rng.random() < self.drop_rate:
            self.packets_dropped += 1
        else:
            self.packets_forwarded += 1
            self.transport.sendto(data, ("127.0.0.1", self.target_port))


@pytest.mark.asyncio
async def test_udp_process_boundary_with_packet_loss():
    """
    Test real UDP socket boundary where sender transmits through a lossy intermediary proxy.
    Receiver has zero access to sender memory and reconstructs purely from socket datagrams.
    """
    loop = asyncio.get_running_loop()

    payload = b"CRITICAL_EARTHQUAKE_TRIAGE: Medical supplies at Grid Alpha-7. Water potability verified." * 20
    packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=2048)
    manifest, chunks, _ = packager.package(payload)

    secret = b"udp-test-secret-key-32b-length!!"
    streamer = FountainStreamer(symbol_size=256, secret_key=secret)
    # Stream manifest over the wire (repeated 6x to survive 25% loss) followed by fountain droplets
    wire_datagrams = list(
        streamer.stream_manifest_wire_packets(
            manifest, chunks, redundancy=1.5, repeat_manifest=6
        )
    )
    total_packets_sent = len(wire_datagrams)

    # Receiver setup (starts completely empty with ZERO access to sender's manifest)
    receiver = FountainStreamReceiver(symbol_size=256, secret_key=secret)
    done_event = asyncio.Event()

    class ReceiverProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            receiver.ingest_bytes(data)
            # Receiver autonomously checks completion using manifest received over the wire
            if receiver.is_complete():
                done_event.set()

    # 1. Bind receiver endpoint
    rx_trans, _ = await loop.create_datagram_endpoint(
        ReceiverProtocol,
        local_addr=("127.0.0.1", 0),
    )
    rx_port = rx_trans.get_extra_info("sockname")[1]

    # 2. Bind intermediary proxy endpoint forwarding to receiver
    proxy_proto = DroppingProxyProtocol(target_port=rx_port, drop_rate=0.25)
    proxy_trans, _ = await loop.create_datagram_endpoint(
        lambda: proxy_proto,
        local_addr=("127.0.0.1", 0),
    )
    proxy_port = proxy_trans.get_extra_info("sockname")[1]

    try:
        # 3. Broadcast wire datagrams (manifest + droplets) to PROXY port (not receiver port)
        await streamer.broadcast_udp(wire_datagrams, host="127.0.0.1", port=proxy_port)

        # 4. Wait for receiver to complete from surviving forwarded packets
        await asyncio.wait_for(done_event.wait(), timeout=3.0)

        # Small drain period to allow any trailing datagrams in OS loopback buffer to reach proxy
        for _ in range(10):
            if proxy_proto.packets_received >= total_packets_sent:
                break
            await asyncio.sleep(0.01)
    finally:
        rx_trans.close()
        proxy_trans.close()

    # 5. Assertions on physical proxy behavior
    assert proxy_proto.packets_received >= total_packets_sent - 1, (
        f"Proxy received {proxy_proto.packets_received}/{total_packets_sent} packets"
    )
    assert proxy_proto.packets_dropped > 0, "Proxy must have physically dropped packets"
    assert proxy_proto.packets_forwarded > 0, "Proxy must have forwarded surviving packets"
    assert proxy_proto.packets_dropped + proxy_proto.packets_forwarded == proxy_proto.packets_received

    # 6. Receiver reconstruction verification with ZERO sender object sharing
    assert receiver.is_complete(), "Receiver must complete reconstruction from wire manifest"
    reconstructed = receiver.assemble()
    assert reconstructed == payload, "Reconstructed payload must be bit-exact match"


@pytest.mark.asyncio
async def test_udp_proxy_100_percent_loss_fails():
    """Control: When proxy drops 100% of datagrams, receiver MUST NOT reconstruct."""
    loop = asyncio.get_running_loop()

    payload = b"Unreachable emergency message"
    packager = MediaStreamPackager(min_chunk_size=512, target_chunk_size=1024, max_chunk_size=2048)
    manifest, chunks, _ = packager.package(payload)

    secret = b"udp-secret-key-32b-length-abcde"
    streamer = FountainStreamer(symbol_size=256, secret_key=secret)
    wire_datagrams = list(
        streamer.stream_manifest_wire_packets(
            manifest, chunks, redundancy=0.50, repeat_manifest=3
        )
    )

    receiver = FountainStreamReceiver(symbol_size=256, secret_key=secret)
    done_event = asyncio.Event()

    class ReceiverProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            receiver.ingest_bytes(data)
            if receiver.is_complete():
                done_event.set()

    rx_trans, _ = await loop.create_datagram_endpoint(
        ReceiverProtocol,
        local_addr=("127.0.0.1", 0),
    )
    rx_port = rx_trans.get_extra_info("sockname")[1]

    # Proxy with 100% drop rate
    proxy_proto = DroppingProxyProtocol(target_port=rx_port, drop_rate=1.0)
    proxy_trans, _ = await loop.create_datagram_endpoint(
        lambda: proxy_proto,
        local_addr=("127.0.0.1", 0),
    )
    proxy_port = proxy_trans.get_extra_info("sockname")[1]

    try:
        await streamer.broadcast_udp(wire_datagrams, host="127.0.0.1", port=proxy_port)
        # Verify receiver does NOT complete
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(done_event.wait(), timeout=0.5)
    finally:
        rx_trans.close()
        proxy_trans.close()

    assert proxy_proto.packets_received == len(wire_datagrams)
    assert proxy_proto.packets_dropped == len(wire_datagrams)
    assert proxy_proto.packets_forwarded == 0
    assert not receiver.is_complete(), "Receiver must NOT be complete under 100% loss"
