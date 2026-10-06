"""Real optional tooling for library tests; never imported by production."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def tools():
    root = Path(__file__).resolve().parents[1]
    optional = root / '.superpowers/tools/python'
    if optional.exists():
        sys.path.insert(0, str(optional))
    pytest.importorskip('libzim.writer', reason='Install optional libzim fixture generator')
    result = {}
    for name, folder in [('kiwix-manage', 'kiwix'), ('kiwix-serve', 'kiwix'), ('zimcheck', 'zim')]:
        local = root / f'.superpowers/tools/{folder}/{name}.exe'
        path = os.environ.get(name.upper().replace('-', '_')) or shutil.which(name) or (str(local) if local.exists() else None)
        if path is None:
            pytest.skip(f'Real integration tool unavailable: {name}')
        result[name] = Path(path)
    return result


def create_zim(path, revision, *, changed_asset_bytes=0):
    from libzim.writer import Creator, Item, StringProvider, Hint

    class FixtureItem(Item):
        def __init__(self, name, data, mime):
            self.name, self.data, self.mime = name, data, mime
        def get_path(self):
            return self.name
        def get_title(self):
            return self.name
        def get_mimetype(self):
            return self.mime
        def get_contentprovider(self):
            return StringProvider(self.data)
        def get_hints(self):
            return {Hint.FRONT_ARTICLE: int(self.mime == 'text/html')}

    page = f'<!doctype html><html><head><title>Library</title></head><body>Library revision {revision}</body></html>'.encode()
    with Creator(path).config_indexing(False, 'eng').config_nbworkers(1) as creator:
        for key, value in {'Title': 'TFP Fixture', 'Description': 'Original CC0 integration fixture', 'Language': 'eng', 'Creator': 'TFP', 'Publisher': 'TFP', 'Date': '2026-10-05', 'Name': 'tfp_fixture'}.items():
            creator.add_metadata(key, value)
        creator.set_mainpath('index.html')
        creator.add_item(FixtureItem('index.html', page, 'text/html'))
        # Incompressible deterministic assets expose real compressed-cluster delta behavior.
        for i in range(20):
            creator.add_item(FixtureItem(f'asset-{i}.bin', hashlib.shake_256(str(i).encode()).digest(16384), 'application/octet-stream'))
        if changed_asset_bytes > 0:
            extra_data = hashlib.shake_256(f'extra-{revision}'.encode()).digest(changed_asset_bytes)
            creator.add_item(FixtureItem('changed-asset.bin', extra_data, 'application/octet-stream'))
    return page


def run(command):
    return subprocess.run([str(c) for c in command], check=True, capture_output=True, timeout=30)
