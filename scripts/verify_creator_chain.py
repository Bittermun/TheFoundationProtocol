#!/usr/bin/env python3
"""Prove the creator journey from three independent, offline wheel installs."""

from __future__ import annotations

import argparse
from hashlib import sha3_256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import venv
from zipfile import ZIP_STORED, ZipFile


# The package and its dependencies have already been provisioned from wheels.
# Block Python socket operations in all three role processes.
OFFLINE = """
import sys
def offline(event, _):
    if event.startswith('socket.'):
        raise AssertionError(f'Unexpected network access: {event}')
sys.addaudithook(offline)
"""

KEYGEN = OFFLINE + """
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.generate()
Path('identity.key').write_bytes(key.private_bytes_raw())
Path('identity.pub').write_bytes(key.public_key().public_bytes_raw())
"""

TFP = OFFLINE + """
from pathlib import Path
import tfp_core_v4
assert sys.prefix != sys.base_prefix
assert Path(tfp_core_v4.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
from tfp_core_v4.cli import main
raise SystemExit(main(sys.argv[1:]))
"""


def school_docs(path, phrase):
    path.mkdir()
    for index in range(16):
        (path / f"lesson-{index:02}.txt").write_text(
            f"Field lesson {index}\n" + "\n".join(
                f"Page {page}. Students observe the orchard and record shade, moisture, "
                f"and leaf color in their school field notebook. This section studies {phrase}."
                for page in range(18)
            ),
            encoding="utf-8",
        )


def role(root, name, wheelhouse, wheel):
    directory = root / name
    directory.mkdir()
    environment = directory / "env"
    venv.create(environment, with_pip=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install",
         "--no-index", "--only-binary=:all:", "--find-links", str(wheelhouse), str(wheel)],
        cwd=directory, check=True, capture_output=True, text=True, timeout=180,
    )
    return directory, python


def execute(python, directory, script, *args):
    return subprocess.run(
        [str(python), "-I", "-c", script, *map(str, args)], cwd=directory,
        check=True, text=True, encoding="utf-8", capture_output=True, timeout=30,
    ).stdout


def prove(root, wheelhouse, recipe):
    wheel, = wheelhouse.glob("tfp-*.whl")
    author_dir, author = role(root, "author", wheelhouse, wheel)
    publisher_dir, publisher = role(root, "publisher", wheelhouse, wheel)
    reader_dir, reader = role(root, "reader", wheelhouse, wheel)

    def kit(python, directory, *args):
        return json.loads(execute(python, directory, TFP, "kit", *args))

    def rejected(expected, python, directory, *args):
        try:
            kit(python, directory, *args)
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1 or expected not in exc.stderr:
                raise
            return
        raise AssertionError(f"Expected refusal: {expected}")

    execute(author, author_dir, KEYGEN)
    execute(publisher, publisher_dir, KEYGEN)
    shutil.copyfile(recipe, author_dir / "recipe.json")
    builder_id, kit_id = "librarian/school-builder", "teacher/field-library"
    common = ("--version", "1.0.0", "--revision", "1", "--license", "CC0-1.0")
    builder = kit(
        author, author_dir, "publish-builder", "recipe.json", "--id", builder_id,
        "--key", "identity.key", "--out", "school.tfpack", *common,
    )
    # Transfer only the artifact and independently provision the public pin.
    shutil.copyfile(author_dir / "school.tfpack", publisher_dir / "school.tfpack")
    shutil.copyfile(author_dir / "identity.pub", publisher_dir / "author.pub")
    shutil.copyfile(publisher_dir / "identity.pub", reader_dir / "publisher.pub")
    shutil.copyfile(author_dir / "identity.pub", reader_dir / "wrong.pub")

    school_docs(publisher_dir / "lessons", "orchard seed exchange")
    build = (
        "run", "school.tfpack", "--builder-id", builder_id, "--builder-key", "author.pub",
        "--builder-digest", builder["digest"], "--publisher-key", "identity.pub",
        "--input-dir", "lessons", "--id", kit_id, "--title", "School field library",
    )
    draft = kit(publisher, publisher_dir, *build, *common, "--out", "draft")
    kit(publisher, publisher_dir, *build, *common, "--out", "rebuilt")
    payloads = ("kit.tfpack", "content.tfpack", "lexicon.tfpack")
    for name in payloads:
        assert (publisher_dir / "draft" / name).read_bytes() == (publisher_dir / "rebuilt" / name).read_bytes()

    kit(publisher, publisher_dir, "sign", "draft", "--key", "identity.key", "--out", "signed")
    shutil.copytree(publisher_dir / "signed", reader_dir / "handoff")
    scope = ("--id", kit_id, "--db", "library.db")
    rejected("Publisher key", reader, reader_dir, "install", "handoff", "--publisher-key", "wrong.pub", *scope)
    (reader_dir / "missing").mkdir()
    for name in ("kit.tfpack", "content.tfpack"):
        shutil.copyfile(reader_dir / "handoff" / name, reader_dir / "missing" / name)
    rejected("Missing required file: lexicon.tfpack", reader, reader_dir,
             "install", "missing", "--publisher-key", "publisher.pub", *scope)
    assert not (reader_dir / "library.db").exists()

    install = ("--publisher-key", "publisher.pub", *scope)
    receipt = kit(reader, reader_dir, "install", "handoff", *install)
    assert receipt["kit"] == draft["kit"] and receipt["documents"] == 16
    found = kit(reader, reader_dir, "search", "orchard seed exchange", *scope)
    assert len(found["results"]) == 16
    article = kit(reader, reader_dir, "read", "lesson-00.txt", *scope)
    original_text = (publisher_dir / "lessons" / "lesson-00.txt").read_bytes()
    assert article["text"].encode("utf-8") == original_text
    verify_dictionary = OFFLINE + """
from zipfile import ZipFile
import zstandard
with ZipFile('handoff/content.tfpack') as archive:
    frame = archive.read('payload/article-001.zst')
assert zstandard.get_frame_parameters(frame).dict_id != 0
try:
    zstandard.ZstdDecompressor().decompress(frame)
except zstandard.ZstdError:
    pass
else:
    raise AssertionError('Article decoded without its dictionary')
"""
    execute(reader, reader_dir, verify_dictionary)

    with ZipFile(publisher_dir / "school.tfpack") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    raw = members["signature.ed25519"]
    members["signature.ed25519"] = bytes([raw[0] ^ 1]) + raw[1:]
    with ZipFile(publisher_dir / "changed.tfpack", "w", compression=ZIP_STORED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    rejected("Invalid creator pack signature", publisher, publisher_dir,
             "run", "changed.tfpack", *build[2:], *common, "--out", "refused")

    school_docs(publisher_dir / "new-lessons", "school water ledger")
    revised = list(build)
    revised[revised.index("--input-dir") + 1] = "new-lessons"
    kit(publisher, publisher_dir, *revised, "--version", "1.1.0", "--revision", 2,
        "--license", "CC0-1.0", "--out", "revised")
    kit(publisher, publisher_dir, "sign", "revised", "--key", "identity.key", "--out", "signed-revision")
    shutil.copytree(publisher_dir / "signed-revision", reader_dir / "revised")
    kit(reader, reader_dir, "install", "revised", *install)
    rejected("Stale revision", reader, reader_dir, "install", "handoff", *install)
    fresh = kit(reader, reader_dir, "search", "school water ledger", *scope)
    assert len(fresh["results"]) == 16
    assert not kit(reader, reader_dir, "search", "orchard seed exchange", *scope)["results"]
    return {
        "status": "passed", "python": sys.version.split()[0], "platform": sys.platform,
        "wheel_sha3": sha3_256(wheel.read_bytes()).hexdigest(),
        "roles": ["author", "publisher", "reader"], "first_library": receipt,
        "first_article_sha3": sha3_256(original_text).hexdigest(),
        "rebuild": "byte-identical on the same authoring wheel and environment",
        "new_library_documents": len(fresh["results"]),
        "refused": ["wrong publisher", "missing dictionary", "changed signature", "stale revision"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, default=Path(__file__).resolve().parents[1] / "examples/school-library/recipe.json")
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="tfp-creator-chain-") as work:
            print(json.dumps(prove(Path(work), args.wheelhouse.resolve(), args.recipe.resolve()), indent=2))
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
