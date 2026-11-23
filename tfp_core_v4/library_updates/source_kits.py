"""Turn a local source collection into pages for the v4 library writer."""

import csv
from html.parser import HTMLParser
from importlib import import_module
from io import BytesIO, StringIO
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from tfp_core_v4.zim_sync import unique_object
from .converter import (
    MAX_DOCUMENT_BYTES, MAX_DOCUMENTS, validate_article,
    validate_library_metadata, write_library,
)
from .manifest import read_bounded

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_CARTRIDGE_MEMBERS = 2048
FIELD_HEADING = re.compile(r'^##[ \t]+(.+)$', re.MULTILINE)
DIRECTORY_FIELDS = ('name', 'category', 'location', 'contact', 'notes')


def read_field_guide(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    text = source.decode('utf-8-sig')
    parts = FIELD_HEADING.split(text, maxsplit=MAX_DOCUMENTS + 1)
    return [(title.strip(), body.strip()) for title, body in zip(parts[1::2], parts[2::2])]


def read_directory(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    reader = csv.DictReader(StringIO(source.decode('utf-8-sig'), newline=''), strict=True)
    fields = reader.fieldnames
    if fields is None or len(fields) != len(DIRECTORY_FIELDS) or set(fields) != set(DIRECTORY_FIELDS):
        raise ValueError('Directory CSV needs name, category, location, contact and notes columns')
    pages = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_DOCUMENTS or None in row or any(value is None for value in row.values()):
            raise ValueError(f'Directory row {index} exceeds the row limit or has the wrong column count')
        title = row['name']
        body = '\n'.join(f'{field.title()}: {row[field].strip()}' for field in DIRECTORY_FIELDS[1:])
        pages.append((title, body))
    return pages


def read_runbook(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    data = json.loads(source.decode('utf-8-sig'), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != {'playbooks'} or not isinstance(data['playbooks'], list):
        raise ValueError('Runbook JSON needs a playbooks list')
    if not 1 <= len(data['playbooks']) <= MAX_DOCUMENTS:
        raise ValueError(f'Runbook needs 1–{MAX_DOCUMENTS} playbooks')
    pages = []
    for playbook in data['playbooks']:
        if not isinstance(playbook, dict) or set(playbook) != {'title', 'trigger', 'steps'}:
            raise ValueError('Each playbook needs title, trigger and steps')
        trigger, steps = playbook['trigger'], playbook['steps']
        if not isinstance(trigger, str) or not trigger.strip() or not isinstance(steps, list) or not steps:
            raise ValueError('Each playbook needs a trigger and at least one step')
        if any(not isinstance(step, str) or not step.strip() for step in steps):
            raise ValueError('Each playbook step must contain text')
        actions = '\n'.join(f'{index}. {step.strip()}' for index, step in enumerate(steps, start=1))
        pages.append((playbook['title'], f'When to use\n{trigger.strip()}\n\nSteps\n{actions}'))
    return pages


class _CartridgePage(HTMLParser):
    _HIDDEN = {'head', 'script', 'style', 'template'}
    _BLOCKS = {'p', 'br', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'h4', 'tr', 'pre'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self.hidden.append(tag)
        elif tag == 'title':
            self.in_title = True
        elif tag in self._BLOCKS and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif tag == 'title':
            self.in_title = False
        elif tag in self._BLOCKS and not self.hidden:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        elif not self.hidden:
            self.parts.append(re.sub(r'\s+', ' ', data))

    def page(self, fallback_title: str) -> tuple[str, str]:
        title = ' '.join(''.join(self.title_parts).split()) or fallback_title
        body = '\n\n'.join(line.strip() for line in ''.join(self.parts).splitlines() if line.strip())
        return title, body


def _cartridge_path(href: str) -> str | None:
    url = urlsplit(href)
    name = unquote(url.path)
    if url.scheme or url.netloc or not name.lower().endswith(('.html', '.htm')):
        return None
    if '\\' in name or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Cartridge page must reference a relative archive path')
    return name


def _cartridge_read(archive: ZipFile, name: str) -> bytes:
    try:
        entry = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f'Missing cartridge member: {name}') from exc
    if entry.file_size > MAX_DOCUMENT_BYTES or entry.is_dir():
        raise ValueError(f'Cartridge member exceeds the page limit: {name}')
    with archive.open(entry) as member:
        data = member.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(f'Cartridge member exceeds the page limit: {name}')
    return data


def read_canvas(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    try:
        from defusedxml.ElementTree import fromstring
    except ImportError as exc:
        raise RuntimeError('Canvas imports require the tfp[library] extra') from exc
    with ZipFile(BytesIO(source)) as archive:
        members = archive.namelist()
        if len(members) > MAX_CARTRIDGE_MEMBERS or len({name.casefold() for name in members}) != len(members):
            raise ValueError('Cartridge has too many members or duplicate names')
        manifest = fromstring(_cartridge_read(archive, 'imsmanifest.xml'))
        resources = {}
        for resource in manifest.findall('./{*}resources/{*}resource'):
            if resource.get('type') != 'webcontent':
                continue
            hrefs = [resource.get('href', '')] + [item.get('href', '') for item in resource.findall('{*}file')]
            paths = [path for href in hrefs if (path := _cartridge_path(href))]
            if paths:
                identity = resource.get('identifier')
                if not identity or identity in resources:
                    raise ValueError('Cartridge HTML resources need distinct identifiers')
                resources[identity] = paths
        items = manifest.findall('./{*}organizations/{*}organization//{*}item')
        references = [item.get('identifierref') for item in items]
        order = dict.fromkeys([ref for ref in references if ref in resources] + list(resources))
        pages = []
        visited = set()
        for identity in order:
            for name in resources[identity]:
                if name in visited:
                    continue
                if len(pages) == MAX_DOCUMENTS:
                    raise ValueError(f'Cartridge has more than {MAX_DOCUMENTS} HTML pages')
                visited.add(name)
                parser = _CartridgePage()
                parser.feed(_cartridge_read(archive, name).decode('utf-8-sig'))
                parser.close()
                pages.append(parser.page(PurePosixPath(name).stem.replace('-', ' ')))
    return pages


SOURCE_KITS = {
    'canvas': read_canvas,
    'field-guide': read_field_guide,
    'directory': read_directory,
    'runbook': read_runbook,
}


def _load_source_module(name: str):
    if not all(part.isidentifier() for part in name.split('.')):
        raise ValueError('Select an installed source adapter by its dotted module name')
    adapter = import_module(name)
    version = getattr(adapter, 'TFP_SOURCE_API', None)
    reader = getattr(adapter, 'read_pages', None)
    if type(version) is not int or version != 1 or not callable(reader):
        raise ValueError('Source adapter must expose TFP_SOURCE_API = 1 and callable read_pages')
    return reader


def build_source_library(
    source: Path, output: Path, metadata: dict, *, kit: str | None, source_module: str | None,
) -> int:
    if (kit is None) == (source_module is None):
        raise ValueError('Select one source kit or installed adapter module')
    metadata = validate_library_metadata(metadata)
    source_limit = MAX_SOURCE_BYTES if kit in ('canvas', None) else MAX_DOCUMENT_BYTES
    raw = read_bounded(source, source_limit)
    try:
        reader = SOURCE_KITS[kit] if kit is not None else _load_source_module(source_module)
        pages = reader(raw, filename=source.name)
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_DOCUMENTS:
            raise ValueError(f'Source adapter must return a list of 1–{MAX_DOCUMENTS} pages')
        articles = [validate_article(page) for page in pages]
    except Exception as exc:
        raise ValueError(f'Cannot read {source.name}: {exc}') from exc
    write_library(output, metadata, articles)
    return len(articles)
