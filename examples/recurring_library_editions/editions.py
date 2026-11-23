"""Publish and refresh a local channel of signed field-guide editions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha3_256
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from tfp_core_v4.library_updates.activation import (
    activate_package, atomic_bytes, load_config, recover_activation, sync_directory,
)
from tfp_core_v4.library_updates.converter import (
    MAX_DOCUMENT_BYTES, MAX_DOCUMENTS, validate_article, validate_library_metadata, write_library,
)
from tfp_core_v4.library_updates.manifest import canonical, file_digest, read_bounded
from tfp_core_v4.library_updates.prepare import prepare_update
from tfp_core_v4.library_updates.source_kits import read_field_guide
from tfp_core_v4.zim_sync import unique_object

RECIPE_FIELDS = {'library_id', 'title', 'description', 'language', 'creator', 'publisher'}


def read_recipe(path: Path) -> dict:
    recipe = json.loads(read_bounded(path, 16384), object_pairs_hook=unique_object)
    if not isinstance(recipe, dict) or set(recipe) != RECIPE_FIELDS:
        raise ValueError('Recipe must define the library ID and field-guide metadata')
    if not isinstance(recipe['library_id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', recipe['library_id']):
        raise ValueError('Choose a lowercase library ID')
    return recipe


def edition_paths(channel: Path) -> list[Path]:
    if not channel.exists():
        return []
    paths = [path for path in channel.iterdir() if re.fullmatch(r'edition-[1-9][0-9]{0,17}', path.name)]
    paths.sort(key=lambda path: int(path.name.removeprefix('edition-')))
    if any(path.name != f'edition-{index}' or path.is_symlink() or not path.is_dir()
           for index, path in enumerate(paths, start=1)):
        raise ValueError('The channel must contain consecutive, complete edition directories')
    return paths


def build_field_guide(raw: bytes, filename: str, recipe: dict, output: Path) -> None:
    from libzim.reader import Archive
    from libzim.search import Query, Searcher

    pages = read_field_guide(raw, filename=filename)
    if not 1 <= len(pages) <= MAX_DOCUMENTS:
        raise ValueError(f'Field guides require 1–{MAX_DOCUMENTS} nonempty level-two sections')
    pages = [validate_article(page) for page in pages]
    metadata = validate_library_metadata({**recipe, 'date': datetime.now(timezone.utc).date().isoformat()})
    write_library(output, metadata, pages)

    archive = Archive(output)
    if not archive.has_fulltext_index:
        raise ValueError('The candidate archive has no full-text index')
    searcher = Searcher(archive)
    for index, (title, _) in enumerate(pages, start=1):
        hits = searcher.search(Query().set_query(title)).getResults(0, len(pages) + 1)
        if f'document-{index:03}.html' not in hits:
            raise ValueError(f'The candidate index does not find its article {title!r}')


def publish(
    recipe_path: Path, source: Path, channel: Path, bootstrap: Path, signing_key: Path,
    *, source_revision: str | None = None,
) -> dict:
    recipe = read_recipe(recipe_path)
    # Read one snapshot so the source digest and archive describe the same bytes.
    raw = read_bounded(source, MAX_DOCUMENT_BYTES)
    source_sha3 = sha3_256(raw).hexdigest()
    existing = edition_paths(channel)
    base = bootstrap
    if existing:
        latest = existing[-1]
        previous = json.loads(read_bounded(latest / 'edition.json', 16384), object_pairs_hook=unique_object)
        if previous['library_id'] != recipe['library_id'] or previous['release_revision'] != len(existing):
            raise ValueError('This channel belongs to a different library or its edition metadata is inconsistent')
        base = latest / 'library.zim'
        if file_digest(base) != previous['archive_sha3']:
            raise ValueError('The previous edition archive does not match its recorded digest')
        if source_sha3 == previous['source_sha3']:
            return {'status': 'unchanged', **previous}

    revision = len(existing) + 1
    channel.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.candidate-', dir=channel) as temporary:
        stage = Path(temporary) / 'edition'
        stage.mkdir()
        archive = stage / 'library.zim'
        build_field_guide(raw, source.name, recipe, archive)
        prepare_update(base, archive, stage / 'update', recipe['library_id'], revision, signing_key)
        edition = {
            'library_id': recipe['library_id'],
            'title': recipe['title'],
            'release_revision': revision,
            'source_revision': source_revision or f'sha3-256:{source_sha3}',
            'source_sha3': source_sha3,
            'archive_sha3': file_digest(archive),
        }
        atomic_bytes(stage / 'edition.json', canonical(edition))
        # Only a complete signed edition appears in the channel. An occupied revision
        # makes the losing publisher retry from the new head of the channel.
        stage.rename(channel / f'edition-{revision}')
        sync_directory(channel)
    return {'status': 'published', **edition}


def refresh(channel: Path, config_path: Path) -> dict:
    config = load_config(config_path)
    paths = edition_paths(channel)
    state = recover_activation(config)
    applied = []
    for path in paths[state.revision:]:
        result = activate_package(path / 'update', config)
        if result.status == 'committed':
            applied.append(result.revision)
        state = result
    return {'library_id': config.library_id, 'release_revision': state.revision, 'applied': applied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    author = commands.add_parser('publish')
    for option in ('recipe', 'source', 'channel', 'bootstrap', 'signing-key'):
        author.add_argument(f'--{option}', required=True, type=Path)
    author.add_argument('--source-revision')
    reader = commands.add_parser('refresh')
    reader.add_argument('--channel', required=True, type=Path)
    reader.add_argument('--config', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'publish':
            result = publish(args.recipe, args.source, args.channel, args.bootstrap, args.signing_key,
                             source_revision=args.source_revision)
        else:
            result = refresh(args.channel, args.config)
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
