"""Build and verify the school-library creator chain entirely from local files."""
from __future__ import annotations

from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import sqlite3
import stat

import zstandard as zstd

from tfp_core_v4.lexicon_training import train_lexicon_dictionary
from tfp_core_v4.library_updates.manifest import canonical, read_bounded
from tfp_core_v4.zim_sync import check_output
from . import pack

MAX_RECIPE = 16 * 1024
MAX_DOCUMENTS = 32
MAX_DOC_BYTES = 256 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DICTIONARY_BYTES = 32 * 1024
MAX_INDEX_BYTES = 32 * 1024
NAMES = ("kit", "content", "lexicon")


def _profile(kind):
    return f"tfp.school-{kind}.v1"


def _sha3(raw):
    return pack.digest(raw, pack.SHA3_PROFILE)


def _bounded(value, low, high):
    return type(value) is int and low <= value <= high


def _document_name(name):
    return (
        isinstance(name, str)
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}\.txt", name))
        and not pack.DEVICE.fullmatch(name[:-4])
    )


def _recipe(raw):
    if len(raw) > MAX_RECIPE:
        raise ValueError("Recipe exceeds size limit")
    recipe = pack.parse_object(raw)
    if not (pack.exact(recipe, ("schema_version", "title", "summary", "input", "steps"))
            and _bounded(recipe["schema_version"], 1, 1)
            and pack.plain(recipe["title"], 120) and pack.plain(recipe["summary"], 240, 0)):
        raise ValueError("Invalid school builder recipe")
    limits = recipe["input"]
    if not (pack.exact(limits, ("suffix", "max_documents", "max_total_bytes"))
            and limits["suffix"] == ".txt"
            and _bounded(limits["max_documents"], 4, MAX_DOCUMENTS)
            and _bounded(limits["max_total_bytes"], 1024, MAX_INPUT_BYTES)):
        raise ValueError("Invalid school builder document limits")
    steps = recipe["steps"]
    if not isinstance(steps, list) or len(steps) != 3:
        raise ValueError("Expected three school builder operations")
    for step in steps:
        if not (pack.exact(step, ("id", "op", "from", "params")) and isinstance(step["id"], str)
                and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", step["id"])):
            raise ValueError("Invalid school builder step")
    train, articles, emit = steps
    if (len({"docs", train["id"], articles["id"], emit["id"]}) != 4
            or [step["op"] for step in steps] != ["lexicon.train", "article.package", "pack.emit"]
            or train["from"] != ["docs"] or articles["from"] != ["docs", train["id"]]
            or emit["from"] != [train["id"], articles["id"]]):
        raise ValueError("Unsupported school builder operations or references")
    if not (pack.exact(train["params"], ("max_dict_kib",))
            and _bounded(train["params"]["max_dict_kib"], 1, MAX_DICTIONARY_BYTES // 1024)
            and pack.exact(articles["params"], ("level",))
            and _bounded(articles["params"]["level"], 1, 9) and emit["params"] == {}):
        raise ValueError("Invalid school builder operation parameters")
    return recipe


def _documents(directory, limits):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Choose a local document directory")
    names = []
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries, start=1):
            if index > 128:
                raise ValueError("Document folder contains too many entries")
            if entry.name.lower().endswith(".txt"):
                names.append(entry.name)
    if not 4 <= len(names) <= limits["max_documents"]:
        raise ValueError("Expected at least four text files within recipe limits")
    if len({name.lower() for name in names}) != len(names) or not all(_document_name(name) for name in names):
        raise ValueError("Invalid or conflicting document name")
    documents = []
    total = 0
    for name in sorted(names):
        path = directory / name
        # Refuse reparse-point inputs on Windows as well as ordinary symlinks.
        attrs = path.lstat()
        if not stat.S_ISREG(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
            raise ValueError("Expected a regular local document")
        raw = read_bounded(path, MAX_DOC_BYTES)
        total += len(raw)
        if total > limits["max_total_bytes"]:
            raise ValueError("Recipe input byte budget exceeded")
        text = raw.decode("utf-8")
        title = text.splitlines()[0].strip() if text else ""
        if not pack.plain(title, 120) or "\0" in text:
            raise ValueError(f"Document needs a short first-line title and UTF-8 text: {name}")
        documents.append((name, title, raw))
    return documents


def _child_id(root, kind):
    if not pack.is_id(root):
        raise ValueError("Expected a school kit ID in namespace/name form")
    value = f"{root}-{kind}"
    if not pack.is_id(value):
        raise ValueError("School kit name is too long for child artifact IDs")
    return value


@contextmanager
def _new_folder(output):
    check_output(output)
    if not output.parent.is_dir():
        raise ValueError("Choose an output under an existing local directory")
    with TemporaryDirectory(prefix=".tfp-school-", dir=output.parent) as stage:
        # Keep the directory returned by TemporaryDirectory in place for its cleanup.
        handoff = Path(stage) / "handoff"
        handoff.mkdir()
        yield handoff
        check_output(output)
        handoff.rename(output)


def publish_builder(source, artifact_id, release, revision, license_id, key_path, output):
    raw = read_bounded(source, MAX_RECIPE)
    recipe = _recipe(raw)
    key = pack.read_secret(key_path)
    builder = pack.make_pack(
        "builder", artifact_id, release, revision, recipe["title"], recipe["summary"],
        license_id, key.public_key().public_bytes_raw(), {"payload/recipe.json": canonical(recipe)},
    )
    pack.write_pack(builder, output, key)
    return builder.ref


def build(builder_path, builder_id, builder_public, builder_digest, publisher_public, artifact_id,
          release, revision, title, license_id, directory, output):
    for kind in ("content", "lexicon"):
        _child_id(artifact_id, kind)
    builder = pack.read_pack(
        builder_path, public=pack.read_public(builder_public),
        expected_id=builder_id, expected_profile=_profile("builder"),
    )
    if builder.ref["digest"] != builder_digest:
        raise ValueError("Builder digest does not match the local pin")
    if builder.manifest["dependencies"]:
        raise ValueError("School builder recipes cannot require other packs")
    recipe = _recipe(builder.payload["payload/recipe.json"])
    public = pack.read_public(publisher_public)
    documents = _documents(directory, recipe["input"])
    train, articles, _emit = recipe["steps"]
    try:
        dictionary, _metrics = train_lexicon_dictionary(
            [raw for _, _, raw in documents], dict_size=train["params"]["max_dict_kib"] * 1024,
        )
    except zstd.ZstdError as exc:
        raise ValueError("Dictionary training needs more or larger lesson text samples") from exc
    dictionary_raw = dictionary.as_bytes()
    tools = (("zstandard", zstd.__version__), ("zstd", ".".join(map(str, zstd.ZSTD_VERSION))))
    summary = recipe["summary"]

    def make(kind, name, payload, dependencies=()):
        return pack.make_pack(
            kind, name, release, revision, title, summary, license_id, public, payload,
            dependencies=dependencies, parent=builder.ref, tool_versions=tools,
        )

    lexicon = make("lexicon", _child_id(artifact_id, "lexicon"), {"payload/dictionary.zdict": dictionary_raw})
    compressor = zstd.ZstdCompressor(level=articles["params"]["level"], dict_data=dictionary)
    payload = {}
    index = []
    for position, (name, label, raw) in enumerate(documents, start=1):
        path = f"payload/article-{position:03}.zst"
        payload[path] = compressor.compress(raw)
        index.append({"name": name, "title": label, "path": path, "bytes": len(raw), "sha3": _sha3(raw)})
    inputs_sha3 = _sha3(canonical({"documents": [[article["name"], article["sha3"]] for article in index]}))
    payload["payload/index.json"] = canonical({
        "schema_version": 1, "dictionary_sha3": _sha3(dictionary_raw),
        "dictionary_id": dictionary.dict_id(), "inputs_sha3": inputs_sha3, "articles": index,
    })
    content = make("content", _child_id(artifact_id, "content"), payload, (lexicon.ref,))
    kit = make("kit", artifact_id, {"payload/kit.json": canonical({"schema_version": 1})}, (content.ref, lexicon.ref))
    with _new_folder(output) as stage:
        for name, artifact in zip(NAMES, (kit, content, lexicon)):
            pack.write_pack(artifact, stage / f"{name}.tfpack")
    return {"kit": kit.ref, "inputs_sha3": inputs_sha3, "documents": len(index)}


def _check_closure(kit, content, lexicon):
    kits = (kit, content, lexicon)
    if [item.manifest["profile"] for item in kits] != [_profile(kind) for kind in NAMES]:
        raise ValueError("Wrong school kit profiles")
    if kit.payload["payload/kit.json"] != canonical({"schema_version": 1}):
        raise ValueError("Unsupported school kit payload")
    root = kit.manifest
    if len(root["provenance"]["parents"]) != 1 or root["provenance"]["parents"][0]["profile"] != _profile("builder"):
        raise ValueError("Missing school builder provenance")
    for child, kind in ((content, "content"), (lexicon, "lexicon")):
        if (child.manifest["id"] != _child_id(root["id"], kind)
                or any(child.manifest[field] != root[field] for field in (
                    "version", "revision", "provenance", "publisher_key_id", "crypto_profile",
                ))):
            raise ValueError("Dependency mismatch in school kit closure")
    if (kit.manifest["dependencies"] != sorted((content.ref, lexicon.ref), key=lambda ref: ref["id"])
            or content.manifest["dependencies"] != [lexicon.ref] or lexicon.manifest["dependencies"]):
        raise ValueError("Dependency mismatch in school kit closure")


def sign(source, secret, output):
    key = pack.read_secret(secret)
    artifacts = [pack.read_pack(source / f"{name}.tfpack") for name in NAMES]
    _check_closure(*artifacts)
    _read_documents(*artifacts[1:])
    with _new_folder(output) as stage:
        for name, artifact in zip(NAMES, artifacts):
            pack.write_pack(artifact, stage / f"{name}.tfpack", key)
    return artifacts[0].ref


def _read_documents(content, lexicon):
    raw = content.payload["payload/index.json"]
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("School article index exceeds its size limit")
    index = pack.parse_object(raw)
    if not (pack.exact(index, ("schema_version", "dictionary_sha3", "dictionary_id", "inputs_sha3", "articles"))
            and _bounded(index["schema_version"], 1, 1) and isinstance(index["articles"], list)
            and 4 <= len(index["articles"]) <= MAX_DOCUMENTS
            and _bounded(index["dictionary_id"], 1, 0xffffffff)
            and pack.is_digest(index["inputs_sha3"], pack.SHA3_PROFILE)):
        raise ValueError("Invalid school article index")
    dictionary_raw = lexicon.payload["payload/dictionary.zdict"]
    if not 1 <= len(dictionary_raw) <= MAX_DICTIONARY_BYTES or _sha3(dictionary_raw) != index["dictionary_sha3"]:
        raise ValueError("Exact article dictionary digest is required")
    dictionary = zstd.ZstdCompressionDict(dictionary_raw, dict_type=zstd.DICT_TYPE_FULLDICT)
    if dictionary.dict_id() != index["dictionary_id"]:
        raise ValueError("Exact article dictionary ID is required")
    decompressor = zstd.ZstdDecompressor(dict_data=dictionary)
    names, paths, result, inputs = set(), {"payload/index.json"}, [], []
    total = 0
    for position, article in enumerate(index["articles"], start=1):
        name = f"payload/article-{position:03}.zst"
        if not (pack.exact(article, ("name", "title", "path", "bytes", "sha3"))
                and _document_name(article["name"]) and pack.plain(article["title"], 120)
                and article["path"] == name and name in content.payload
                and _bounded(article["bytes"], 1, MAX_DOC_BYTES)
                and pack.is_digest(article["sha3"], pack.SHA3_PROFILE)
                and article["name"].lower() not in names):
            raise ValueError("Invalid school article record")
        names.add(article["name"].lower())
        paths.add(name)
        total += article["bytes"]
        if total > MAX_INPUT_BYTES:
            raise ValueError("School article bytes exceed installation budget")
        frame = content.payload[name]
        settings = zstd.get_frame_parameters(frame)
        if (settings.content_size != article["bytes"] or settings.window_size > MAX_DOC_BYTES
                or settings.dict_id != dictionary.dict_id()):
            raise ValueError("Article frame does not require the declared dictionary and size")
        body = decompressor.decompress(frame, max_output_size=article["bytes"], allow_extra_data=False)
        text = body.decode("utf-8")
        if (len(body) != article["bytes"] or _sha3(body) != article["sha3"] or "\0" in text
                or text.splitlines()[0].strip() != article["title"]):
            raise ValueError("Decoded school article does not match its digest or size")
        result.append((article["name"], article["title"], text))
        inputs.append([article["name"], article["sha3"]])
    if (paths != content.payload.keys() or inputs != sorted(inputs)
            or _sha3(canonical({"documents": inputs})) != index["inputs_sha3"]):
        raise ValueError("School article inventory or input provenance mismatch")
    return result


def install(source: Path, public_path: Path, artifact_id: str, db: Path) -> dict:
    public = pack.read_public(public_path)
    ids = [artifact_id, _child_id(artifact_id, "content"), _child_id(artifact_id, "lexicon")]
    kit, content, lexicon = [
        pack.read_pack(source / f"{kind}.tfpack", public=public, expected_id=expected, expected_profile=_profile(kind))
        for kind, expected in zip(NAMES, ids)
    ]
    _check_closure(kit, content, lexicon)
    documents = _read_documents(content, lexicon)
    root = kit.manifest
    publication = kit.ref["digest"]
    # Track the raw key across supported manifest hash profiles.
    pin = _sha3(public)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS school_active ("
            "id TEXT PRIMARY KEY, pin TEXT NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS school_versions ("
            "id TEXT, version TEXT, digest TEXT NOT NULL, PRIMARY KEY (id, version))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS school_articles ("
            "id TEXT, name TEXT, title TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (id, name))"
        )
        active = connection.execute(
            "SELECT pin, revision, digest FROM school_active WHERE id = ?", (artifact_id,),
        ).fetchone()
        if active:
            active_key, revision, active_digest = active
            if active_key != pin:
                raise ValueError("School kit publisher cannot replace the local installation pin")
            if root["revision"] < revision:
                raise ValueError("Stale revision of school kit")
            if root["revision"] == revision:
                if publication != active_digest:
                    raise ValueError("Conflicting school kit at the accepted revision")
                return {"status": "already_active", "kit": kit.ref}
        binding = connection.execute(
            "SELECT digest FROM school_versions WHERE id = ? AND version = ?", (artifact_id, root["version"]),
        ).fetchone()
        if binding and binding[0] != publication:
            raise ValueError("School kit version already bound to different bytes")
        connection.execute(
            "INSERT INTO school_versions VALUES (?, ?, ?)", (artifact_id, root["version"], publication),
        )
        connection.execute(
            "INSERT OR REPLACE INTO school_active VALUES (?, ?, ?, ?)",
            (artifact_id, pin, root["revision"], publication),
        )
        connection.execute("DELETE FROM school_articles WHERE id = ?", (artifact_id,))
        connection.executemany(
            "INSERT INTO school_articles VALUES (?, ?, ?, ?)",
            ((artifact_id, *document) for document in documents),
        )
    return {"status": "active", "kit": kit.ref, "documents": len(documents)}


def read_library(db: Path, artifact_id: str, *, query=None, name=None) -> dict:
    if not pack.is_id(artifact_id):
        raise ValueError("Invalid school kit ID")
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if not connection.execute("SELECT 1 FROM school_active WHERE id = ?", (artifact_id,)).fetchone():
            raise ValueError("School kit is not installed")
        if name is not None:
            row = connection.execute(
                "SELECT title, body FROM school_articles WHERE id = ? AND name = ?", (artifact_id, name),
            ).fetchone()
            if row is None:
                raise ValueError("School article is not present")
            return {"name": name, "title": row[0], "text": row[1]}
        if not pack.plain(query, 120):
            raise ValueError("Enter a search phrase of 1–120 characters")
        needle = query.casefold()
        rows = connection.execute(
            "SELECT name, title, body FROM school_articles WHERE id = ? ORDER BY name", (artifact_id,),
        )
        return {"results": [
            {"name": name, "title": title} for name, title, text in rows
            if needle in title.casefold() or needle in text.casefold()
        ]}
