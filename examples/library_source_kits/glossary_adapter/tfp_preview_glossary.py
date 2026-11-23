"""An independent author-side adapter for a local term-to-definition mapping."""

import json

TFP_SOURCE_API = 1


def read_pages(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    definitions = json.loads(source.decode('utf-8'))
    if not isinstance(definitions, dict):
        raise ValueError(f'Expected a JSON object in {filename}')
    return sorted(definitions.items())
