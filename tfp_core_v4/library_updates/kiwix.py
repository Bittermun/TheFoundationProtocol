"""External Kiwix tooling and bounded public reader probes, only on operator hosts."""
import http.client
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import tostring
try:
    import defusedxml.ElementTree as ET
except ImportError as exc:
    raise RuntimeError('Kiwix activation requires the optional tfp[library] extra') from exc

from .manifest import read_bounded


def run_tool(arguments: list[str], timeout: float) -> str:
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(arguments, shell=False, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        output.seek(0)
        text = output.read(16384).decode('utf-8', errors='replace')
    if result.returncode:
        raise ValueError(f'Kiwix validation/tool failed ({result.returncode}): {text}')
    return text


def validate_zim(path: Path, executable: Path, timeout: float) -> None:
    run_tool([str(executable), '--checksum', '--integrity', str(path)], timeout)


def parse_xml(raw: bytes):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML entity declarations are not accepted')
    return ET.fromstring(raw)


def prepare_catalog(
    original: bytes, candidate: Path, archive: Path, executable: Path, timeout: float,
    *, current_edition_only: bool = False,
) -> str:
    root = parse_xml(original)
    if current_edition_only:
        for book in root.findall('book'):
            root.remove(book)
        original = tostring(root, encoding='utf-8', xml_declaration=True)
    candidate.write_bytes(original)
    run_tool([str(executable), str(candidate), 'add', str(archive)], timeout)
    root = parse_xml(read_bounded(candidate, 1048576))
    books = list(root.iter('book'))
    if current_edition_only and len(books) != 1:
        raise ValueError('Expected exactly one edition in the candidate Kiwix catalog')
    for book in books:
        registered = (candidate.parent / book.attrib.get('path', '')).resolve()
        if registered == archive.resolve():
            return book.attrib['id']
    raise ValueError('Kiwix catalog did not register the target archive')


def http_get(base_url: str, endpoint: str, timeout: float) -> bytes:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Expected an operator-configured HTTP(S) Kiwix URL without credentials')
    cls = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    connection = cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request('GET', parsed.path.rstrip('/') + endpoint)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'Kiwix probe returned {response.status}')
        raw = response.read(1048577)
        if not raw or len(raw) > 1048576:
            raise ValueError('Kiwix probe response exceeds bounds or is empty')
        return raw
    finally:
        connection.close()


def probe_reader(
    base_url: str, archive: Path, book_id: str, article: str, timeout: float,
    current_edition_only: bool = False,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Kiwix did not expose the updated archive before deadline')
        try:
            catalog = parse_xml(http_get(base_url, '/catalog/v2/entries?count=-1', min(remaining, 2)))
            entries = catalog.findall('{http://www.w3.org/2005/Atom}entry')
            identifiers = [entry.findtext('{http://www.w3.org/2005/Atom}id') for entry in entries]
            if not any(value in (book_id, f'urn:uuid:{book_id}') for value in identifiers):
                raise ValueError('Target absent from public OPDS catalog')
            if current_edition_only and len(entries) != 1:
                raise ValueError('Expected exactly one edition in the public OPDS catalog')
            endpoint = '/raw/' + quote(archive.stem.lower(), safe='') + '/content/' + quote(article, safe='/')
            http_get(base_url, endpoint, min(max(deadline - time.monotonic(), .001), 2))
            return
        except (OSError, ValueError, http.client.HTTPException):
            time.sleep(min(.1, max(0, deadline - time.monotonic())))
