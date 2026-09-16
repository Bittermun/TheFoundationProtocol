# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Command Line Interface for TFP v4.0

Usage:
  python -m tfp_core_v4.cli publish <file_path> [--title <title>]
  python -m tfp_core_v4.cli fetch <root_hash> --output <output_path> [--loss <loss_rate>]
  python -m tfp_core_v4.cli inspect <root_hash>
  python -m tfp_core_v4.cli verify
"""

import argparse
from pathlib import Path
import sys

from .node import TFPNode


def main():
    parser = argparse.ArgumentParser(
        prog="tfp",
        description="The Foundation Protocol (TFP v4.0) CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Publish
    pub_p = subparsers.add_parser("publish", help="Publish a file into TFP")
    pub_p.add_argument("file_path", help="Path to file to publish")
    pub_p.add_argument("--title", default=None, help="Optional title metadata")

    # Fetch
    fetch_p = subparsers.add_parser("fetch", help="Fetch and reconstruct content by root hash")
    fetch_p.add_argument("root_hash", help="SHA3-256 root hash")
    fetch_p.add_argument("--output", "-o", required=True, help="Path to save reconstructed file")
    fetch_p.add_argument("--loss", type=float, default=0.0, help="Simulated packet drop rate (0.0 - 0.50)")

    # Inspect
    insp_p = subparsers.add_parser("inspect", help="Inspect recipe and chunk DAG")
    insp_p.add_argument("root_hash", help="SHA3-256 root hash to inspect")

    # Verify
    subparsers.add_parser("verify", help="Run automated protocol verification suite")

    args = parser.parse_args()
    if args.command in {"fetch", "inspect"}:
        parser.error(
            f"{args.command} is not implemented in this stateless research CLI; "
            "no data was fetched or inspected. Use tfp_cli.main for the running node."
        )
    node = TFPNode()

    if args.command == "publish":
        path = Path(args.file_path)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        with open(path, "rb") as f:
            data = f.read()

        title = args.title or path.name
        recipe = node.publish(data, metadata={"title": title, "filename": path.name})
        print("[TFP] Encoded locally in memory; data is not persisted or sent to peers.")
        print(f"  Root Hash   : {recipe.root_hash}")
        print(f"  Total Size  : {recipe.total_size} bytes")
        print(f"  Chunks Count: {len(recipe.chunk_hashes)}")
        print(f"  Avg Chunk   : {recipe.total_size // max(1, len(recipe.chunk_hashes))} bytes")

    elif args.command == "verify":
        print("[TFP] Running self-verification test suite...")
        # Self-test
        sample_data = b"THE FOUNDATION PROTOCOL v4.0 TEST PAYLOAD: " * 50
        recipe = node.publish(sample_data, metadata={"test": True})
        recovered = node.fetch(recipe.root_hash, simulated_loss=0.30)
        if recovered != sample_data:
            raise RuntimeError("Local reconstruction differs from original bytes")
        print("[TFP] Local reconstruction matched the original bytes.")
        print("[TFP] Simulated drops may be repaired from the original local pool; this is not a network-loss benchmark.")


if __name__ == "__main__":
    main()
