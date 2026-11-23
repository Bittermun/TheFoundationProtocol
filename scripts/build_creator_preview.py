# SPDX-License-Identifier: Apache-2.0
"""Build, verify and bundle four TFP libraries from an installed wheel."""

import argparse
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from libzim.reader import Archive
from libzim.search import Query, Searcher

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'library_source_kits'
STARTERS = (
    ('canvas', 'Field science course', 'Canvas Common Cartridge', 'course.imscc', 'observation notebook'),
    ('field-guide', 'School garden field guide', 'Markdown sections', 'field-guide.md', 'rain gauge log'),
    ('directory', 'School services directory', 'CSV records', 'directory.csv', 'printed course catalog'),
    ('runbook', 'Offline continuity runbook', 'JSON playbooks', 'runbook.json', 'cellular data disabled'),
)


def build_cartridge(path: Path) -> None:
    source = EXAMPLES / 'canvas'
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for member in sorted(source.rglob('*')):
            if member.is_file():
                archive.write(member, member.relative_to(source).as_posix())


def gallery(cards: list[str]) -> str:
    return """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TFP Creator Preview</title>
<style>
body{color:#162132;background:#f5f6f8;font:16px/1.55 system-ui;margin:0}
main{max-width:960px;margin:auto;padding:6vh clamp(1rem,5vw,3rem)}
h1{font-size:clamp(2.5rem,7vw,4rem);line-height:1.05;margin:.4em 0}
.intro{max-width:55ch}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:1rem}
article{background:white;border:1px solid #d9dfe6;border-radius:12px;padding:1.3rem}
h2{font-size:1.3rem;margin:.25rem 0}.actions{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem}
a{color:#174e85;text-underline-offset:.22em}a:focus-visible{outline:2px solid #174e85}
footer{margin:2rem 0}
</style>
<main><h1>TFP Creator Preview</h1>
<p class="intro">Browse sample libraries built from a course export, a field guide,
a services spreadsheet and a continuity runbook. Open a ZIM in Kiwix to search its contents.</p>
<div class="grid">""" + ''.join(cards) + """</div>
<footer><a href="verification.json">Build verification</a></footer></main></html>
"""


def build_preview(output: Path) -> list[dict]:
    output = output.resolve()
    if output.suffix != '.zip' or not output.parent.is_dir():
        raise ValueError('Choose a new .zip file in an existing directory')
    with TemporaryDirectory(prefix='.tfp-preview-', dir=output.parent) as work:
        stage = Path(work)
        bundle = stage / 'bundle'
        sources = bundle / 'sources'
        sources.mkdir(parents=True)
        (bundle / 'libraries').mkdir()
        shutil.copyfile(EXAMPLES.parents[1] / 'LICENSE', bundle / 'LICENSE')
        build_cartridge(sources / 'course.imscc')
        cards = []
        results = []
        for kit, title, format_name, filename, query in STARTERS:
            source = sources / filename
            if kit != 'canvas':
                shutil.copyfile(EXAMPLES / filename, source)
            zim = bundle / 'libraries' / f'{kit}.zim'
            subprocess.run(
                [sys.executable, '-I', '-m', 'tfp_core_v4.cli', 'library-import', str(source),
                 '--kit', kit, '--out', str(zim), '--title', title,
                 '--publisher', 'The Foundation Protocol', '--date', '2026-11-20'],
                cwd=stage, check=True, capture_output=True, encoding='utf-8', timeout=60,
            )
            archive = Archive(zim)
            search = Searcher(archive).search(Query().set_query(query))
            matches = list(search.getResults(0, 10))
            if matches != ['document-001.html'] or archive.has_entry_by_path('document-003.html'):
                raise ValueError(f'Unexpected preview count or full-text search result for {kit}')
            snapshot = bundle / kit
            snapshot.mkdir()
            for name in ('index.html', 'document-001.html', 'document-002.html'):
                (snapshot / name).write_bytes(bytes(archive.get_entry_by_path(name).get_item().content))
            del search, archive
            page_link = f'{kit}/index.html'
            zim_link = f'libraries/{kit}.zim'
            cards.append(
                f'<article><div>{escape(format_name)}</div><h2>{escape(title)}</h2>'
                f'<p class="actions"><a href="{page_link}">Browse pages</a>'
                f'<a href="{zim_link}">Open ZIM</a>'
                f'<a href="sources/{filename}">Source file</a></p></article>'
            )
            results.append({'kit': kit, 'documents': 2, 'search': query, 'matches': matches,
                            'archive_sha256': sha256(zim.read_bytes()).hexdigest()})
        (bundle / 'index.html').write_text(gallery(cards), encoding='utf-8')
        (bundle / 'verification.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        candidate = stage / 'preview.zip'
        with ZipFile(candidate, 'w', compression=ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle).as_posix())
        os.link(candidate, output)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        results = build_preview(args.out)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, exc.stderr or str(exc))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Creator preview: {exc}\n')
    print(json.dumps({'bundle': str(args.out), 'libraries': results}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
