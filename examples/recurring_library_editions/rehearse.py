"""Run the two-edition example with disposable keys and a loopback Kiwix reader."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tfp_core_v4.library_updates.kiwix import http_get, parse_xml
from .editions import build_field_guide, edition_paths, read_recipe

EXAMPLE = Path(__file__).resolve().parent
CLI = 'examples.recurring_library_editions.editions'
ATOM = '{http://www.w3.org/2005/Atom}'
FIRST_PHRASE = 'copper trail marker'
SECOND_PHRASE = 'linen route card'


def checked(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def cli(command: list[str], *, expected: int = 0) -> dict | str:
    result = subprocess.run([sys.executable, '-B', '-m', CLI, *command],
                            capture_output=True, text=True, encoding='utf-8', timeout=120)
    checked(result.returncode == expected, f'{command[0]} exited {result.returncode}: {result.stderr}')
    if expected != 0:
        return result.stderr.strip()
    # libzim can print progress before the command's final JSON record.
    try:
        return json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'{command[0]} did not return a final JSON record') from exc


def tool(name: str) -> Path:
    value = os.environ.get(name.upper().replace('-', '_')) or shutil.which(name)
    if not value or not Path(value).is_file():
        raise ValueError(f'Install {name} or set {name.upper().replace("-", "_")} to its path')
    return Path(value).resolve()


def catalog_entry(origin: str) -> str:
    catalog = parse_xml(http_get(origin, '/catalog/v2/entries?count=-1', 2))
    entries = catalog.findall(f'{ATOM}entry')
    checked(len(entries) == 1, 'The dedicated catalog should show exactly one edition')
    entry_id = entries[0].findtext(f'{ATOM}id')
    if not entry_id:
        raise RuntimeError('The catalog entry has no archive ID')
    return entry_id


def reader_finds(origin: str, phrase: str) -> bool:
    results = http_get(origin, f'/search?pattern={quote(phrase)}', 5).decode('utf-8')
    return bool(re.search(r'href="[^"]*document-001\.html(?:\?[^"]*)?"', results))


def exercise(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f'Choose a new rehearsal output directory: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    serve, manage, zimcheck = (tool(name) for name in ('kiwix-serve', 'kiwix-manage', 'zimcheck'))
    recipe_path = EXAMPLE / 'recipe.json'
    recipe = read_recipe(recipe_path)
    with TemporaryDirectory(prefix='.recurring-library-', dir=output.parent) as temporary:
        sandbox = Path(temporary)
        handoff = sandbox / 'handoff'
        handoff.mkdir()
        channel = handoff / 'channel'
        bootstrap = handoff / 'bootstrap.zim'
        bootstrap_source = EXAMPLE / 'fixtures/bootstrap.md'
        build_field_guide(bootstrap_source.read_bytes(), bootstrap_source.name, recipe, bootstrap)
        key = Ed25519PrivateKey.generate()
        private = sandbox / 'publisher.key'
        private.write_bytes(key.private_bytes_raw())
        public = handoff / 'rehearsal-publisher.pub'
        public.write_bytes(key.public_key().public_bytes_raw())

        station = sandbox / 'station'
        station.mkdir()
        base = station / 'bootstrap.zim'
        shutil.copyfile(bootstrap, base)
        catalog = station / 'library.xml'
        subprocess.run([str(manage), str(catalog), 'add', str(base)], check=True, capture_output=True, timeout=30)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        config = station / 'config.json'
        config.write_text(json.dumps({
            'library_id': recipe['library_id'], 'archive_dir': str(station / 'archives'),
            'library_xml': str(catalog), 'state_dir': str(station / 'state'), 'base_archive': str(base),
            'trusted_public_key': str(public), 'kiwix_manage': str(manage), 'zimcheck': str(zimcheck),
            'serve_base_url': origin, 'probe_article_path': 'index.html', 'current_edition_only': True,
            'command_timeout_seconds': 10,
        }), encoding='utf-8')

        source = sandbox / 'field-guide.md'
        publish = ['publish', '--recipe', str(recipe_path), '--source', str(source), '--channel', str(channel),
                   '--bootstrap', str(bootstrap), '--signing-key', str(private)]
        refresh = ['refresh', '--channel', str(channel), '--config', str(config)]
        server = subprocess.Popen([str(serve), '--library', '--monitorLibrary', '--address=127.0.0.1',
                                   f'--port={port}', str(catalog)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        timeline = []
        try:
            deadline = time.monotonic() + 8
            while True:
                try:
                    previous_entry = catalog_entry(origin)
                    break
                except OSError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Kiwix did not open the rehearsal catalog')
                    time.sleep(.1)

            for revision, (fixture, phrase) in enumerate([
                ('field-guide.md', FIRST_PHRASE), ('field-guide-next.md', SECOND_PHRASE),
            ], start=1):
                shutil.copyfile(EXAMPLE / 'fixtures' / fixture, source)
                published = cli(publish)
                received = cli(refresh)
                entry = catalog_entry(origin)
                checked(published['status'] == 'published' and published['release_revision'] == revision,
                        f'Publisher did not produce edition {revision}')
                checked(received['applied'] == [revision] and received['release_revision'] == revision,
                        f'Recipient did not activate edition {revision}')
                checked(entry != previous_entry and reader_finds(origin, phrase),
                        f'Kiwix did not find {phrase!r} in edition {revision}')
                timeline.append({'published': published, 'received': received,
                                 'reader': {'catalog_id': entry, 'search_phrase': phrase, 'found': True}})
                previous_entry = entry

            checked(not reader_finds(origin, FIRST_PHRASE), 'The superseded edition still appears in search')
            accepted_catalog = catalog.read_bytes()
            repeated = cli(publish)
            caught_up = cli(refresh)
            checked(repeated['status'] == 'unchanged' and repeated['release_revision'] == 2 and caught_up['applied'] == [],
                    'Repeating the source created or activated another edition')
            source.write_text('# Field guide\n\nThe candidate is missing any level-two section.\n', encoding='utf-8')
            rejected = cli(publish, expected=1)
            after_failure = cli(refresh)
            checked('level-two sections' in rejected, 'The candidate did not fail its content check')
            checked(len(edition_paths(channel)) == 2 and after_failure['applied'] == [] and after_failure['release_revision'] == 2,
                    'The failed candidate changed the channel or accepted revision')
            checked(catalog.read_bytes() == accepted_catalog and reader_finds(origin, SECOND_PHRASE),
                    'The last good edition became unavailable after the failed candidate')
            proof = {
                'library_id': recipe['library_id'], 'reader': 'Kiwix Serve on loopback with a monitored dedicated catalog',
                'trigger': 'Same one-shot publisher command after editing the source file', 'editions': timeline,
                'replay': {'publisher': repeated, 'recipient': caught_up},
                'failed_candidate': {'error': rejected, 'recipient': after_failure,
                                     'last_good_search_phrase': SECOND_PHRASE, 'found': True},
            }
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

        (handoff / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
        handoff.rename(output)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    proof = exercise(args.out.resolve())
    for edition in proof['editions']:
        print(f"Edition {edition['received']['release_revision']}: Kiwix found {edition['reader']['search_phrase']!r}")
    print(f'Replaying edition 2 added zero editions. The failing build left edition 2 searchable.\n{args.out / "proof.json"}')


if __name__ == '__main__':
    main()
