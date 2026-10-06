import asyncio
import hashlib
import importlib
import socket

import pytest


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
async def test_real_udp_artifact_delivery(tmp_path):
    adapter = importlib.import_module('tfp_core_v4.library_updates.receive')
    source, out = tmp_path / 'source', tmp_path / 'out'
    source.write_bytes(hashlib.shake_256(b'artifact').digest(80000))
    port = free_port()
    receiver = asyncio.create_task(adapter.receive_artifact(80000, hashlib.sha3_256(source.read_bytes()).hexdigest(), out, tmp_path / 'checkpoints', '127.0.0.1', port, 5, b'x' * 32))
    try:
        await asyncio.sleep(.1)
        await adapter.send_artifact(source, '127.0.0.1', port, b'x' * 32, rounds=2, packet_interval=.001)
        assert await receiver == out
        assert out.read_bytes() == source.read_bytes()
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


@pytest.mark.asyncio
async def test_no_delivery_times_out_without_output(tmp_path):
    adapter = importlib.import_module('tfp_core_v4.library_updates.receive')
    with pytest.raises(TimeoutError):
        await adapter.receive_artifact(1, hashlib.sha3_256(b'x').hexdigest(), tmp_path / 'out', tmp_path / 'cp', '127.0.0.1', free_port(), .05, b'x' * 32)
    assert not (tmp_path / 'out').exists()


@pytest.mark.asyncio
async def test_empty_transport_key_rejected(tmp_path):
    adapter = importlib.import_module('tfp_core_v4.library_updates.receive')
    with pytest.raises(ValueError):
        await adapter.receive_artifact(1, '0' * 64, tmp_path / 'out', tmp_path / 'cp', '127.0.0.1', free_port(), .05, b'')


@pytest.mark.asyncio
async def test_wrong_transport_key_cannot_complete(tmp_path):
    adapter = importlib.import_module('tfp_core_v4.library_updates.receive')
    source = tmp_path / 'source'
    source.write_bytes(b'content')
    port = free_port()
    task = asyncio.create_task(adapter.receive_artifact(7, hashlib.sha3_256(b'content').hexdigest(), tmp_path / 'out', tmp_path / 'cp', '127.0.0.1', port, .4, b'x' * 32))
    try:
        await asyncio.sleep(.05)
        await adapter.send_artifact(source, '127.0.0.1', port, b'y' * 32)
        with pytest.raises(TimeoutError):
            await task
        assert not (tmp_path / 'out').exists()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
