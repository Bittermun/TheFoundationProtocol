"""Lazy optional CLI registration; reader/tool imports occur only for these commands."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys


def register(subparsers):
    prepare = subparsers.add_parser('library-prepare', help='Prepare a signed offline-library update')
    prepare.add_argument('base', type=Path)
    prepare.add_argument('target', type=Path)
    prepare.add_argument('--library-id', required=True)
    prepare.add_argument('--revision', type=int, required=True)
    prepare.add_argument('--signing-key', type=Path, required=True)
    prepare.add_argument('--out', type=Path, required=True)
    prepare.add_argument('--delta-backend', choices=['cdc', 'zstd', 'auto'], default='cdc')
    prepare.set_defaults(library_adapter=True)
    for command in ('library-send', 'library-receive'):
        parser = subparsers.add_parser(command, help='Transfer an authorized artifact using existing FM/FD UDP packets')
        parser.add_argument('package', type=Path)
        parser.add_argument('--library-id', required=True)
        parser.add_argument('--trusted-key', type=Path, required=True)
        parser.add_argument('--accepted-revision', type=int, default=0)
        parser.add_argument('--transport-key-file', type=Path, required=True)
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--port', type=int, default=9876)
        parser.add_argument('--timeout', type=float, default=60)
        if command == 'library-send':
            parser.add_argument('--rounds', type=int, default=3)
            parser.add_argument('--packet-interval', type=float, default=.002)
        else:
            parser.add_argument('--checkpoint-dir', type=Path, required=True)
        parser.set_defaults(library_adapter=True)
    for command in ('library-activate', 'library-status', 'library-recover'):
        parser = subparsers.add_parser(command, help='Manage the optional operator-side Kiwix adapter')
        if command == 'library-activate':
            parser.add_argument('package', type=Path)
        parser.add_argument('--config', type=Path, required=True)
        parser.add_argument('--json', action='store_true')
        parser.set_defaults(library_adapter=True)


def run(args) -> int:
    try:
        if args.command == 'library-prepare':
            from .prepare import prepare_update
            result = {'package': str(prepare_update(args.base, args.target, args.out, args.library_id, args.revision, args.signing_key, delta_backend=args.delta_backend))}
        elif args.command in ('library-send', 'library-receive'):
            from .manifest import read_bounded, key_id, verify_descriptor, verify_update
            from .receive import send_artifact, receive_artifact
            public = read_bounded(args.trusted_key, 32)
            transport_key = read_bounded(args.transport_key_file, 32)
            verify = verify_update if args.command == 'library-send' else verify_descriptor
            update = verify(args.package, {key_id(public): public}, args.library_id, args.accepted_revision)
            path = args.package / update.artifact_name
            if args.command == 'library-send':
                wire_bytes = asyncio.run(send_artifact(path, args.host, args.port, transport_key, rounds=args.rounds, packet_interval=args.packet_interval, timeout_seconds=args.timeout))
                result = {'status': 'sent', 'wire_bytes': wire_bytes}
            else:
                asyncio.run(receive_artifact(update.artifact_size, update.artifact_sha3, path, args.checkpoint_dir, args.host, args.port, args.timeout, transport_key))
                result = {'status': 'received_digest_verified', 'artifact': str(path)}
        else:
            from .activation import activate_package, load_config, library_status, recover_activation
            config = load_config(args.config)
            if args.command == 'library-status':
                result = library_status(config)
            else:
                value = activate_package(args.package, config) if args.command == 'library-activate' else recover_activation(config)
                result = asdict(value)
        print(json.dumps(result, default=str, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Library adapter failed ({type(exc).__name__}): {exc}', file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description='Optional operator-side TFP library adapters')
    register(parser.add_subparsers(dest='command', required=True))
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
