"""Bounded operator-only UDP adapter over the existing authenticated FM/FD wire."""
import asyncio
import hashlib
import hmac
import math
from pathlib import Path
import socket

from tfp_client.lib.media.fountain_streamer import AntiPollutionError, FountainStreamer, deserialize_manifest_packet
from tfp_client.lib.media.receiver import FountainStreamReceiver
from tfp_client.lib.media.stream_packager import MediaManifest
from tfp_core_v4.merkle import MerkleTree
from tfp_core_v4.zim_sync import check_output, new_output, valid_hash
from .manifest import MAX_ARTIFACT, read_bounded

TRANSPORT_CHUNK = 65536


def validate_transport(size: int, digest: str, key: bytes) -> None:
    if type(size) is not int or not 0 < size <= MAX_ARTIFACT or len(key) != 32:
        raise ValueError('Artifact requires pilot size limits and a 32-byte transport key')
    valid_hash(digest)


def artifact_packets(source: Path, transport_key: bytes, redundancy: float = .75):
    """Keep per-artifact data bounded; packet production is lazy."""
    data = read_bounded(source, MAX_ARTIFACT)
    digest = hashlib.sha3_256(data).hexdigest()
    validate_transport(len(data), digest, transport_key)
    if not 0 <= redundancy <= 4:
        raise ValueError('Invalid repair redundancy')
    chunks = [data[i:i + TRANSPORT_CHUNK] for i in range(0, len(data), TRANSPORT_CHUNK)]
    manifest = MediaManifest(digest, 'application/octet-stream', len(data), len(chunks),
                             MerkleTree(chunks).root_hex, [hashlib.sha3_256(c).hexdigest() for c in chunks],
                             [len(c) for c in chunks], {'artifact_sha3': digest})
    streamer = FountainStreamer(symbol_size=512, secret_key=transport_key)
    yield from streamer.stream_manifest_wire_packets(manifest, chunks, redundancy=redundancy)


async def send_artifact(source: Path, host: str, port: int, transport_key: bytes,
                        *, rounds: int = 1, packet_interval: float = .002, timeout_seconds: float = 60) -> int:
    if type(rounds) is not int or not 1 <= rounds <= 20 or not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or not math.isfinite(packet_interval) or packet_interval < 0:
        raise ValueError('Invalid sender pacing or deadline')
    loop = asyncio.get_running_loop()
    sent = 0
    packets = await asyncio.to_thread(list, artifact_packets(source, transport_key))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        async with asyncio.timeout(timeout_seconds):
            for _ in range(rounds):
                for raw in packets:
                    if len(raw) > 65507:
                        raise ValueError('Manifest exceeds UDP payload ceiling')
                    await asyncio.wait_for(loop.sock_sendto(sock, raw, (host, port)), timeout=timeout_seconds)
                    sent += len(raw)
                    await asyncio.sleep(packet_interval)
    return sent


def matches(manifest: MediaManifest | None, size: int, digest: str) -> bool:
    return bool(manifest and manifest.total_size == size and 0 < manifest.chunk_count <= 256
                and all(0 < n <= TRANSPORT_CHUNK for n in manifest.chunk_sizes)
                and isinstance(manifest.manifest_id, str) and hmac.compare_digest(manifest.manifest_id, digest)
                and isinstance(manifest.metadata.get('artifact_sha3'), str)
                and hmac.compare_digest(manifest.metadata['artifact_sha3'], digest))


async def receive_artifact(expected_size: int, expected_sha3: str, destination: Path,
                           checkpoint_dir: Path, host: str, port: int,
                           timeout_seconds: float, transport_key: bytes) -> Path:
    validate_transport(expected_size, expected_sha3, transport_key)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('Invalid receiver deadline')
    check_output(destination)
    # Keep updates in separate namespaces; the core also validates authentication context.
    receiver = FountainStreamReceiver(symbol_size=512, secret_key=transport_key, verify_tag=True,
                                     max_sessions=1, max_chunks_per_session=256, max_droplets_per_chunk=256,
                                     checkpoint_dir=checkpoint_dir / expected_sha3)
    if not matches(receiver.latest_manifest, expected_size, expected_sha3):
        receiver.reset()
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        sock.setblocking(False)
        sock.bind((host, port))
        async with asyncio.timeout(timeout_seconds):
            while not receiver.is_complete():
                raw = await asyncio.wait_for(loop.sock_recv(sock, 65535), timeout=timeout_seconds)
                if raw.startswith(b'FM'):
                    try:
                        manifest = deserialize_manifest_packet(raw, secret_key=transport_key, verify_tag=True)
                    except (AntiPollutionError, ValueError, KeyError, TypeError):
                        continue
                    if not matches(manifest, expected_size, expected_sha3):
                        continue
                elif not matches(receiver.latest_manifest, expected_size, expected_sha3):
                    continue
                receiver.ingest_bytes(raw)
            data = receiver.assemble()
            if len(data) != expected_size or not hmac.compare_digest(hashlib.sha3_256(data).hexdigest(), expected_sha3):
                raise ValueError('Received artifact integrity failure')
            def write_output() -> None:
                with new_output(destination) as out:
                    out.write(data)

            await asyncio.to_thread(write_output)
    return destination
