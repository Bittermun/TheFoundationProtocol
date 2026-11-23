"""Command line for publishing, using and installing a school-library toolkit."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

from .pack import LICENSES


def register(subparsers):
    group = subparsers.add_parser("kit", help="Publish and use local school-library builders")
    commands = group.add_subparsers(dest="kit_action", required=True)

    publish = commands.add_parser("publish-builder", help="Validate and sign a declarative builder")
    publish.add_argument("recipe", type=Path)
    publish.add_argument("--key", type=Path, required=True, help="Author's raw Ed25519 private key")

    build = commands.add_parser("run", help="Run a pinned builder and write unsigned output packs")
    build.add_argument("builder", type=Path)
    build.add_argument("--builder-id", required=True)
    build.add_argument("--builder-key", type=Path, required=True)
    build.add_argument("--builder-digest", required=True)
    build.add_argument("--publisher-key", type=Path, required=True, help="Publisher's raw Ed25519 public key")
    build.add_argument("--title", required=True)
    build.add_argument("--input-dir", type=Path, required=True)

    for command in (publish, build):
        command.add_argument("--id", required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--revision", type=int, required=True)
        command.add_argument("--license", choices=LICENSES, required=True)
        command.add_argument("--out", type=Path, required=True)

    sign = commands.add_parser("sign", help="Validate and sign the three output packs")
    sign.add_argument("source", type=Path)
    sign.add_argument("--key", type=Path, required=True, help="Publisher's raw Ed25519 private key")
    sign.add_argument("--out", type=Path, required=True)

    install = commands.add_parser("install", help="Verify and activate a complete offline kit")
    install.add_argument("source", type=Path)
    install.add_argument("--publisher-key", type=Path, required=True)
    search = commands.add_parser("search", help="Search locally installed articles")
    search.add_argument("query")
    read = commands.add_parser("read", help="Read a locally installed article")
    read.add_argument("name")
    for command in (install, search, read):
        command.add_argument("--id", required=True)
        command.add_argument("--db", type=Path, required=True)


def run(args):
    import zstandard
    from . import school

    try:
        actions = {
            "publish-builder": lambda: school.publish_builder(
                args.recipe, args.id, args.version, args.revision, args.license, args.key, args.out,
            ),
            "run": lambda: school.build(
                args.builder, args.builder_id, args.builder_key, args.builder_digest, args.publisher_key,
                args.id, args.version, args.revision, args.title, args.license, args.input_dir, args.out,
            ),
            "sign": lambda: school.sign(args.source, args.key, args.out),
            "install": lambda: school.install(args.source, args.publisher_key, args.id, args.db),
            "search": lambda: school.read_library(args.db, args.id, query=args.query),
            "read": lambda: school.read_library(args.db, args.id, name=args.name),
        }
        print(json.dumps(actions[args.kit_action](), sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error, zstandard.ZstdError) as exc:
        print(f"School kit: {exc}", file=sys.stderr)
        return 1
