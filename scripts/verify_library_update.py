"""Offline process-boundary proof using a prepared package and a real Kiwix server.

Run from an installed environment with --python pointing to its interpreter.
Requires optional psutil only for evidence collection, not for the adapters.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import random
import shutil
import socket
import subprocess
import time

import psutil


class LossProxy(asyncio.DatagramProtocol):
    def __init__(self, target: tuple[str, int], seed: int, rate: float) -> None:
        self.target = target
        self.rate = rate
        self.rng = random.Random(seed)  # Reproducible test impairment, never keys/IDs.
        self.received = 0
        self.forwarded = 0
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, raw: bytes, address: tuple[str, int]) -> None:
        self.received += len(raw)
        if self.rng.random() >= self.rate:
            if self.transport is not None:
                self.transport.sendto(raw, self.target)
            self.forwarded += len(raw)


def kill_tree(process: subprocess.Popen) -> None:
    # Windows venv python.exe can be a launcher with an actual interpreter child.
    try:
        children = psutil.Process(process.pid).children(recursive=True)
        for child in children:
            child.kill()
        process.kill()
        process.wait(timeout=5)
        psutil.wait_procs(children, timeout=5)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def demonstrate(args: argparse.Namespace) -> int:
    from tfp_core_v4.library_updates.manifest import file_digest, key_id, read_bounded, verify_descriptor

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receive_package = output / 'received'
    receive_package.mkdir()
    for filename in ('update.json', 'update.sig'):
        shutil.copyfile(args.package / filename, receive_package / filename)

    pub_bytes = read_bounded(args.public_key, 32)
    pub_id = key_id(pub_bytes)
    raw_desc = json.loads((args.package / 'update.json').read_bytes())
    library_id = raw_desc['library_id']
    verified_update = verify_descriptor(
        args.package,
        {pub_id: pub_bytes},
        library_id,
        0,
    )
    artifact_name = verified_update.artifact_name

    receiver_port, proxy_port = free_port(), free_port()
    proxy = LossProxy(('127.0.0.1', receiver_port), args.seed, args.loss)
    loop = asyncio.get_running_loop()
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    proxy_socket.bind(('127.0.0.1', proxy_port))
    proxy_socket.setblocking(False)
    transport, _ = await loop.create_datagram_endpoint(lambda: proxy, sock=proxy_socket)
    processes: list[subprocess.Popen] = []
    logs = []
    peak = 0
    started = time.monotonic()

    def launch(command: list[str], name: str) -> subprocess.Popen:
        log = (output / (name + '.log')).open('wb')
        logs.append(log)
        process = subprocess.Popen(
            [str(args.python), '-I', '-m', 'tfp_core_v4.library_updates.cli', *command],
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=output,
        )
        processes.append(process)
        return process

    async def wait_for(predicate) -> None:
        nonlocal peak
        while not predicate():
            if time.monotonic() - started > 120:
                raise TimeoutError('Process-boundary demonstration exceeded deadline')
            for process in processes:
                if process.poll() is None:
                    try:
                        monitored = psutil.Process(process.pid)
                        tree_rss = monitored.memory_info().rss + sum(
                            child.memory_info().rss for child in monitored.children(recursive=True)
                        )
                        peak = max(peak, tree_rss)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            await asyncio.sleep(0.01)

    common = [
        '--library-id', verified_update.library_id,
        '--trusted-key', str(args.public_key.resolve()),
        '--transport-key-file', str(args.transport_key.resolve()),
        '--timeout', '90',
    ]
    receive_command = [
        'library-receive', str(receive_package),
        *common,
        '--port', str(receiver_port),
        '--checkpoint-dir', str(output / 'checkpoints'),
    ]
    report: dict = {
        'schema_version': 1,
        'scenario': args.scenario,
        'loss_rate': args.loss,
        'loss_seed': args.seed,
        'stages': {},
        'fixture_target_sha3': verified_update.target_sha3,
    }

    try:
        if args.scenario == 'restart':
            first = launch(receive_command, 'receiver-before')
            await asyncio.sleep(0.3)
            sender = launch(
                ['library-send', str(args.package.resolve()), *common, '--port', str(proxy_port), '--rounds', '3', '--packet-interval', '.01'],
                'sender-before',
            )
            await wait_for(lambda: any((output / 'checkpoints').rglob('chunk_*.dat')) or first.poll() is not None)
            if first.poll() is not None:
                raise RuntimeError('Receiver completed/failed before checkpoint interruption; use a multi-chunk artifact')
            # Closing a Windows UDP destination can poison the proxy socket via ICMP.
            # Pause forwarding before the receiver goes away, then bind a fresh socket.
            transport.close()
            await asyncio.to_thread(kill_tree, first)
            if sender.poll() is None:
                await asyncio.to_thread(kill_tree, sender)
            checkpoint_count = len(list((output / 'checkpoints').rglob('chunk_*.dat')))
            second = launch(receive_command, 'receiver-after')
            await asyncio.sleep(0.3)
            proxy_port = free_port()
            transport, _ = await loop.create_datagram_endpoint(lambda: proxy, local_addr=('127.0.0.1', proxy_port))
            sender = launch(
                ['library-send', str(args.package.resolve()), *common, '--port', str(proxy_port), '--rounds', '3', '--packet-interval', '.01'],
                'sender-after',
            )
            await wait_for(lambda: second.poll() is not None and sender.poll() is not None)
            if second.returncode or sender.returncode:
                raise RuntimeError('Sender or restarted receiver failed; see process logs')
            report['checkpoint_chunks_before_restart'] = checkpoint_count
            report['stages']['restart_delivery'] = 'passed'
        else:  # delivery scenario (tiny artifact or standard uninterrupted transfer)
            receiver = launch(receive_command, 'receiver')
            await asyncio.sleep(0.3)
            sender = launch(
                ['library-send', str(args.package.resolve()), *common, '--port', str(proxy_port), '--rounds', '3', '--packet-interval', '.01'],
                'sender',
            )
            await wait_for(lambda: receiver.poll() is not None and sender.poll() is not None)
            if receiver.returncode or sender.returncode:
                raise RuntimeError('Sender or receiver failed; see process logs')
            report['stages']['delivery'] = 'passed'

        received = receive_package / artifact_name
        if not received.exists() or file_digest(received) != verified_update.artifact_sha3:
            raise ValueError('Independent received digest mismatch')

        activation = launch(['library-activate', str(receive_package), '--config', str(args.config.resolve()), '--json'], 'activation')
        await wait_for(lambda: activation.poll() is not None)
        if activation.returncode:
            raise RuntimeError('Real reader activation failed; see activation.log')
        report['stages']['reader_activation'] = 'passed'
        report['status'] = 'passed'

    except Exception as exc:
        report['status'] = 'failed'
        report['failure_reason'] = str(exc)
    finally:
        transport.close()
        for process in processes:
            if process.poll() is None:
                kill_tree(process)
            process.wait(timeout=5)
        for log in logs:
            log.close()

    restart_count = 1 if args.scenario == 'restart' else 0
    report.update(
        artifact_kind=verified_update.artifact_kind,
        patch_format=verified_update.patch_format,
        format_name=verified_update.format_name,
        artifact_bytes=verified_update.artifact_size,
        full_archive_bytes=verified_update.target_size,
        proxy_received_wire_bytes=proxy.received,
        proxy_forwarded_wire_bytes=proxy.forwarded,
        operator_process_tree_peak_rss_bytes=peak,
        elapsed_seconds=round(time.monotonic() - started, 3),
        restart_count=restart_count,
    )
    report['wire_to_full_ratio'] = round(proxy.received / verified_update.target_size, 4)
    if peak > 256 * 1024 * 1024:
        report.update(status='failed', failure_reason='Operator process-tree RSS exceeded declared 256 MiB pilot cap')
    if args.wheel:
        report['wheel_sha3'] = file_digest(args.wheel)
    location = subprocess.run([str(args.python), '-I', '-c', 'import tfp_core_v4.library_updates.manifest as m; print(m.__file__)'], capture_output=True, text=True, timeout=10)
    report['loaded_adapter_path'] = location.stdout.strip()
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'public-key', 'transport-key', 'config', 'python', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--scenario', choices=['delivery', 'restart'], default='restart')
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--loss', type=float, default=0.3)
    parser.add_argument('--seed', type=int, default=20261005)
    args = parser.parse_args()
    if not 0 <= args.loss <= 1:
        parser.error('Loss must be between 0 and 1')
    return asyncio.run(demonstrate(args))


if __name__ == '__main__':
    raise SystemExit(main())
