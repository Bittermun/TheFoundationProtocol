# Experimental offline library converters

A converter turns one local document into a title and plain-text body. TFP
renders the text as an offline HTML page and builds a searchable ZIM archive
with a linked table of contents. The author can sign and distribute that archive
with the existing v4 library commands. Recipients use Kiwix and the pinned
publisher key.

## Write a converter

Publish a Python module with the following public interface. Version 1 uses
only built-in Python types and needs no imports from TFP.

```python
TFP_CONVERTER_API = 1

def convert(document: bytes, *, filename: str) -> tuple[str, str]:
    text = document.decode("utf-8")
    title, _, body = text.partition("\n")
    return title.strip(), body.strip()
```

- TFP calls `convert` once per document in recipe order and passes the recipe's
  basename as the keyword argument `filename`.
- Return a tuple of two strings. The title must contain 1–120 characters after
  trimming. The body must contain text and fit within 1 MiB of UTF-8. TFP
  escapes both fields as HTML text. Paragraph breaks and line breaks display as
  written in the body.
- Raise `ValueError` with a short explanation for invalid document contents.
  TFP reports which document failed.
- The operator explicitly selects an installed importable module with
  `--converter-module package.module` or a trusted local Python file with
  `--converter-file /path/to/converter.py`. Selecting it runs Python code with
  the author's process permissions. Review it before use, install its
  dependencies on the author machine, and keep its conversion local.

## Write a recipe

Save a UTF-8 JSON file with exactly these fields. `schema_version` is integer
`1`. `language` is a three-letter lowercase language code. `date` is a
calendar date in YYYY-MM-DD form. Title, creator, publisher, and description
have a 120-character limit. Document order determines the order of the contents
page.

```json
{
  "schema_version": 1,
  "title": "Example local library",
  "description": "Original notes for offline reading",
  "language": "eng",
  "creator": "Example Volunteer Group",
  "publisher": "Example Volunteer Group",
  "date": "2026-11-18",
  "documents": ["first.txt", "second.txt"]
}
```

Use 1–32 unique basenames under the operator-selected input directory. A basename
may contain ASCII letters, digits, underscores, hyphens and dots, must start
and end with a letter or digit, and may have at most 100 characters. Windows
device names and case-insensitive duplicates are rejected. Each input can
contain up to 1 MiB and the recipe up to 16 KiB. The recipe has no Python,
network, output, or signing-key settings. Transfer the recipe and documents as
ordinary data and select a converter independently when building.

## Build

On the author machine, install TFP and the optional `libzim` Python package
(tested with 3.13.0 on Python 3.11). Use a Python version with a compatible libzim
wheel. From the repository, try the [checklist example](../examples/library_converters/independent/).

```sh
python -m pip install . libzim==3.13.0
tfp library-build recipe.json --input-dir documents --converter-file /path/to/converter.py --out target.zim
```

Choose a new `.zim` path in an existing directory. Open `index.html` as the
main page. Articles use paths such as `document-001.html` and `document-002.html`.
Recipe dates go into ZIM metadata. Build, receive, and activate on a filesystem
that supports hard links, which TFP uses to install finished files atomically.
You can carry the completed releases on USB drives.

## Publish and read

The existing update workflow starts with the same accepted base ZIM on both
machines. The recipient pins the publisher's raw 32-byte Ed25519 public key
through a separate trusted channel. The author signs with the corresponding raw
32-byte private key.

```sh
tfp library-prepare base.zim target.zim --library-id school --revision 1 --signing-key publisher.key --out release
```

For a file handoff, copy the whole release directory. For UDP, copy
`update.json` and `update.sig` to the recipient's release directory first, and
provision the same 32-byte transport key on both machines. Start the receiver,
then send to its destination. The commands use UDP port 9876 by default.

```sh
tfp library-receive release --library-id school --trusted-key publisher.pub --transport-key-file transport.key --host 0.0.0.0 --checkpoint-dir checkpoints
tfp library-send release --library-id school --trusted-key publisher.pub --transport-key-file transport.key --host 192.0.2.10
```

Replace the example send address with the recipient's address. Set
`--accepted-revision` to the recipient's current revision for later updates.
After an interruption, run both commands again with the same recipient release
directory, trusted key, and checkpoint directory. The receiver reports the
signed artifact's filename, size and SHA3-256. Once it has an authenticated
transport manifest, it reports the total missing chunk count and up to 16
zero-based chunk indexes with their SHA3-256 hashes. It reuses completed,
verified chunks and checks the entire artifact against the signed SHA3-256
before writing it.

On the recipient machine, install `tfp[library]`, Kiwix tools and `zimcheck`.
Configure the existing local Kiwix adapter using the
[example configuration](../deploy/iiab/config.example.json) and
`index.html` as the probe article. Register the base archive with
`kiwix-manage` first and start `kiwix-serve` with `--library --monitorLibrary`
against that catalog. Then activate the signed update.

```sh
tfp library-activate release --config config.json
```

Open the library in Kiwix and use the contents page or full-text search. The
recipient runs the v4 verifier and Kiwix with the received archive. The converter,
recipe, source documents, and libzim authoring package stay with the author.

When a `--delta-backend zstd` update produces `artifact.zst`, the exact base
archive doubles as its dictionary. Keep that archive and use the required
SHA3-256 reported by activation to identify it. The same title or source
documents can produce a different ZIM and cannot substitute for those bytes.

### Catalog behavior and local rehearsal

The example station config sets `current_edition_only` for a dedicated
catalog. If the new edition fails its reader probe, activation restores the
previous catalog. Archive files stay on disk for recovery.

A recorded x86-64 Linux rehearsal of `750b376` with local changes used a
wheelhouse and disabled container networking. Kiwix found the base lesson,
removed it from search after activation, then restored the accepted edition
after a later probe failed and kept serving it after a restart. The focused
Linux suite recorded 85 passing tests. These were local software checks.
