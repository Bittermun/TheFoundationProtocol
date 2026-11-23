# TFP Creator Preview

The preview ZIP contains four ZIMs, their source files, a browser gallery, and a
record of the full-text queries checked during the build. Extract the ZIP and
open `index.html` to browse the gallery. Open a `.zim` in Kiwix for full-text search.

## Build one of the starter kits

| Kit | Local input | Output pages |
| --- | --- | --- |
| `canvas` | Canvas Common Cartridge `.imscc` | Text from local HTML resources, ordered by manifest references where present |
| `field-guide` | UTF-8 Markdown with level-two headings | One page per heading with its section text |
| `directory` | CSV with `name,category,location,contact,notes` | One page per record |
| `runbook` | JSON with a `playbooks` list | One page per `title`, `trigger`, and `steps` record |

Use Python 3.11 with a compatible libzim wheel. From the checkout, install the
authoring dependencies and try the runbook.

```sh
python -m pip install ".[library]" libzim==3.13.0
tfp library-import examples/library_source_kits/runbook.json --kit runbook --title "Site continuity runbook" --publisher "Example site" --date 2026-11-20 --out continuity.zim
```

The cartridge example uses original fixture content. The Canvas adapter
extracts UTF-8 HTML text. Embedded media, attachments, quizzes, grade sync, and
the Canvas app are outside this import profile. Export only materials you can
share with the people who will reach the local reader. A ZIM is a content
archive, and its bytes can be read by whoever receives it.

For a second edition, use
[TFP library preparation and activation](library-converter.md#publish-and-read)
with the exact ZIM already installed at the receiving site.

## Add an adapter

An installed Python module can supply pages from another local file format.
The author selects and trusts the module. Readers receive the resulting ZIM.
The interface uses Python types and accepts up to 32 `(title, body)` tuples
with a title of up to 120 characters and a UTF-8 body of up to 1 MiB.

```python
TFP_SOURCE_API = 1

def read_pages(source: bytes, *, filename: str) -> list[tuple[str, str]]:
    return [(filename, source.decode("utf-8"))]
```

The independently installable glossary adapter provides a complete example.

```sh
python -m pip install ./examples/library_source_kits/glossary_adapter
tfp library-import examples/library_source_kits/glossary.json --source-module tfp_preview_glossary --title "Field glossary" --publisher "Example site" --date 2026-11-20 --out glossary.zim
```

## Prepare a shareable preview

```sh
python scripts/build_creator_preview.py --out tfp-creator-preview.zip
```

The [Creator Preview workflow](../.github/workflows/creator-preview.yml)
builds from the wheel and attaches the ZIP as an Actions artifact.
