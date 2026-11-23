"""Author-side converter host for experimental offline libraries."""

from datetime import date
from collections.abc import Iterable
from html import escape
from importlib import import_module
import json
from pathlib import Path
import re
import runpy
import shutil
from tempfile import TemporaryDirectory

from tfp_core_v4.zim_sync import check_output, new_output, unique_object
from .manifest import MAX_ARCHIVE, read_bounded

MAX_DOCUMENTS = 32
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_RECIPE_BYTES = 16 * 1024
RECIPE_FIELDS = {
    'schema_version', 'title', 'description', 'language',
    'creator', 'publisher', 'date', 'documents',
}
WINDOWS_DEVICES = {'AUX', 'CON', 'NUL', 'PRN'} | {
    f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in range(10)
}


def _short_text(text: object, label: str) -> str:
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 120 or '\0' in text:
        raise ValueError(f'{label} must contain 1–120 characters')
    text.encode('utf-8')
    return text.strip()


def _load_recipe(path: Path) -> dict:
    raw = read_bounded(path, MAX_RECIPE_BYTES)
    recipe = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
    if not isinstance(recipe, dict) or set(recipe) != RECIPE_FIELDS:
        raise ValueError('Unsupported library recipe fields')
    if type(recipe['schema_version']) is not int or recipe['schema_version'] != 1:
        raise ValueError('Unsupported library recipe schema_version')

    recipe.update(validate_library_metadata(recipe))
    names = recipe['documents']
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_DOCUMENTS:
        raise ValueError(f'documents must list 1–{MAX_DOCUMENTS} basenames')
    seen = set()
    for name in names:
        if (
            not isinstance(name, str)
            or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?', name)
            or name.split('.', 1)[0].upper() in WINDOWS_DEVICES
        ):
            raise ValueError(f'Invalid document basename: {name!r}')
        if name.lower() in seen:
            raise ValueError(f'Duplicate document: {name}')
        seen.add(name.lower())
    return recipe


def validate_library_metadata(values: dict) -> dict:
    metadata = {field: _short_text(values[field], field)
                for field in ('title', 'description', 'creator', 'publisher')}
    language = values['language']
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{3}', language):
        raise ValueError('language must be a three-letter lowercase code')
    build_date = values['date']
    if not isinstance(build_date, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', build_date):
        raise ValueError('date must use YYYY-MM-DD')
    date.fromisoformat(build_date)
    return {**metadata, 'language': language, 'date': build_date}


def _read_document(path: Path) -> bytes:
    try:
        return read_bounded(path, MAX_DOCUMENT_BYTES)
    except (OSError, ValueError) as exc:
        raise ValueError(f'Required document {path.name}: {exc}') from exc


def _load_converter(module: str | None, path: Path | None):
    if (module is None) == (path is None):
        raise ValueError('Select one local converter module or file')
    try:
        if path is not None:
            if path.suffix != '.py' or path.is_symlink() or not path.is_file():
                raise ValueError('Select a regular local .py converter file')
            namespace = runpy.run_path(str(path.resolve()))
        else:
            if not all(part.isidentifier() for part in module.split('.')):
                raise ValueError('Select a Python converter module by its dotted name')
            namespace = vars(import_module(module))
    except Exception as exc:
        raise ValueError(f'Cannot load selected converter: {exc}') from exc

    version = namespace.get('TFP_CONVERTER_API')
    convert = namespace.get('convert')
    if type(version) is not int or version != 1 or not callable(convert):
        raise ValueError('Converter must expose TFP_CONVERTER_API = 1 and a callable convert')
    return convert


def _convert(convert, name: str, raw: bytes) -> tuple[str, str]:
    try:
        return validate_article(convert(raw, filename=name))
    except Exception as exc:
        raise ValueError(f'Converter failed for {name}: {exc}') from exc


def validate_article(result: object) -> tuple[str, str]:
    if not isinstance(result, tuple) or len(result) != 2:
        raise ValueError('Return a (title, body) tuple')
    title = _short_text(result[0], 'Document title')
    body = result[1]
    if (not isinstance(body, str) or not body.strip() or '\0' in body
            or len(body) > MAX_DOCUMENT_BYTES or len(body.encode('utf-8')) > MAX_DOCUMENT_BYTES):
        raise ValueError('Document body must contain text and fit in 1 MiB of UTF-8')
    return title, body


def _page(language: str, title: str, content: str) -> bytes:
    title = escape(title)
    return (
        f'<!doctype html><html lang="{language}"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title><style>pre{{white-space:pre-wrap;overflow-wrap:anywhere;'
        'font:inherit}}body{max-width:65ch;margin:2rem auto;padding:0 1rem}</style>'
        f'<body><h1>{title}</h1>{content}</body></html>'
    ).encode('utf-8')


def _write_zim(path: Path, recipe: dict, pages: Iterable[tuple[str, str]]) -> None:
    try:
        from libzim.writer import Creator, Hint, Item, StringProvider
    except ImportError as exc:
        raise RuntimeError('Library authoring requires the optional libzim Python package') from exc

    class Page(Item):
        def __init__(self, path: str, title: str, content: bytes):
            self.path, self.title, self.content = path, title, content

        def get_path(self):
            return self.path

        def get_title(self):
            return self.title

        def get_mimetype(self):
            return 'text/html'

        def get_contentprovider(self):
            return StringProvider(self.content)

        def get_hints(self):
            return {Hint.FRONT_ARTICLE: 1}

    language = recipe['language']
    with Creator(path).config_verbose(False).config_indexing(True, language).config_nbworkers(1) as writer:
        for field in ('title', 'description', 'language', 'creator', 'publisher', 'date'):
            writer.add_metadata(field.capitalize(), recipe[field])
        writer.set_mainpath('index.html')
        links = []
        for index, (title, body) in enumerate(pages, start=1):
            article = f'document-{index:03}.html'
            links.append(f'<li><a href="{article}">{escape(title)}</a></li>')
            content = f'<p><a href="index.html">Contents</a></p><pre>{escape(body)}</pre>'
            writer.add_item(Page(article, title, _page(language, title, content)))
        content = f'<p>{escape(recipe["description"])}</p><ol>{"".join(links)}</ol>'
        writer.add_item(Page('index.html', recipe['title'], _page(language, recipe['title'], content)))


def build_library(
    recipe_path: Path, input_dir: Path, output: Path, *,
    converter_module: str | None = None, converter_file: Path | None = None,
) -> int:
    """Build a ZIM archive with the operator's selected converter and return its document count."""
    check_output(output)
    if output.suffix.lower() != '.zim' or not output.parent.is_dir():
        raise ValueError('Choose a new .zim output in an existing directory')
    recipe = _load_recipe(recipe_path)
    if not input_dir.is_dir():
        raise ValueError(f'Input directory does not exist: {input_dir}')
    documents = {name: _read_document(input_dir / name) for name in recipe['documents']}
    convert = _load_converter(converter_module, converter_file)
    write_library(output, recipe, (_convert(convert, name, raw) for name, raw in documents.items()))
    return len(documents)


def write_library(output: Path, metadata: dict, pages: Iterable[tuple[str, str]]) -> None:
    """Publish validated articles as a new indexed ZIM."""
    check_output(output)
    if output.suffix.lower() != '.zim' or not output.parent.is_dir():
        raise ValueError('Choose a new .zim output in an existing directory')
    with TemporaryDirectory(prefix='.tfp-build-', dir=output.parent) as tmp:
        candidate = Path(tmp) / 'library.zim'
        _write_zim(candidate, metadata, pages)
        if not 0 < candidate.stat().st_size <= MAX_ARCHIVE:
            raise ValueError('Generated ZIM exceeds library archive limits')
        with new_output(output) as destination, candidate.open('rb') as source:
            shutil.copyfileobj(source, destination, 1024 * 1024)
