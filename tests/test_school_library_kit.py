from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
import zstandard


REPO = Path(__file__).resolve().parents[1]


def invoke(*args, cwd=REPO):
    return subprocess.run(
        [sys.executable, "-m", "tfp_core_v4.cli", "kit", *map(str, args)],
        cwd=cwd, text=True, encoding="utf-8", capture_output=True, timeout=30,
    )


def ok(*args):
    result = invoke(*args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def fails(message, *args):
    result = invoke(*args)
    assert result.returncode == 1, result.stderr
    assert message in result.stderr


def identity(root, name):
    key = Ed25519PrivateKey.generate()
    private = root / f"{name}.key"
    public = root / f"{name}.pub"
    private.write_bytes(key.private_bytes_raw())
    public.write_bytes(key.public_key().public_bytes_raw())
    return private, public


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


def test_creator_chain_and_rejections(tmp_path):
    a_secret, a_public = identity(tmp_path, "creator-a")
    b_secret, b_public = identity(tmp_path, "creator-b")
    builder = tmp_path / "builder.tfpack"
    authored = ok(
        "publish-builder", REPO / "examples/school-library/recipe.json",
        "--id", "librarian/school-builder", "--version", "1.0.0", "--revision", 1,
        "--key", a_secret, "--license", "CC0-1.0", "--out", builder,
    )
    docs = tmp_path / "docs"
    school_docs(docs, "orchard seed exchange")
    out = tmp_path / "unsigned"
    signed = tmp_path / "signed"
    run = (
        "run", builder, "--builder-id", "librarian/school-builder", "--builder-key", a_public,
        "--builder-digest", authored["digest"], "--publisher-key", b_public,
        "--id", "teacher/library", "--title", "School orchard", "--version", "1.0.0", "--revision", 1,
        "--input-dir", docs, "--license", "CC0-1.0",
    )
    first = ok(*run, "--out", out)
    rebuild = ok(*run, "--out", tmp_path / "again")
    for name in ("kit", "content", "lexicon"):
        assert (out / f"{name}.tfpack").read_bytes() == (tmp_path / "again" / f"{name}.tfpack").read_bytes()
    assert rebuild["inputs_sha3"] == first["inputs_sha3"]
    ok("sign", out, "--key", b_secret, "--out", signed)

    with ZipFile(signed / "content.tfpack") as content:
        frame = content.read("payload/article-001.zst")
        assert zstandard.get_frame_parameters(frame).dict_id != 0
        with pytest.raises(zstandard.ZstdError):
            zstandard.ZstdDecompressor().decompress(frame)

    db = tmp_path / "recipient.db"
    install = (
        "install", signed, "--publisher-key", b_public, "--id", "teacher/library", "--db", db,
    )
    fails("Publisher key", *install[:2], "--publisher-key", a_public, "--id", "teacher/library", "--db", db)
    assert not db.exists()
    lexicon = signed / "lexicon.tfpack"
    hidden = tmp_path / "missing.tfpack"
    lexicon.rename(hidden)
    fails("Missing required file: lexicon.tfpack", *install)
    assert not db.exists()
    hidden.rename(lexicon)
    ok(*install)
    assert ok(*install)["status"] == "already_active"
    assert len(ok("search", "orchard seed exchange", "--id", "teacher/library", "--db", db)["results"]) == 16
    assert "orchard seed exchange" in ok(
        "read", "lesson-00.txt", "--id", "teacher/library", "--db", db,
    )["text"]

    docs2 = tmp_path / "docs2"
    school_docs(docs2, "school water ledger")
    out2, signed2 = tmp_path / "unsigned2", tmp_path / "signed2"
    args2 = list(run)
    for opt, val in (("--input-dir", docs2), ("--version", "1.1.0"), ("--revision", 2)):
        args2[args2.index(opt) + 1] = val
    ok(*args2, "--out", out2)
    ok("sign", out2, "--key", b_secret, "--out", signed2)
    ok("install", signed2, *install[2:])
    fails("Stale revision", *install)
    assert not ok("search", "orchard seed exchange", "--id", "teacher/library", "--db", db)["results"]
    assert "school water ledger" in ok("read", "lesson-00.txt", "--id", "teacher/library", "--db", db)["text"]

    lexicon.write_bytes((signed2 / "lexicon.tfpack").read_bytes())
    fails("Dependency mismatch", *install)
    raw = bytearray(builder.read_bytes())
    with ZipFile(builder) as archive:
        payload = archive.read("payload/recipe.json")
    at = raw.index(payload)
    raw[at] ^= 1
    builder.write_bytes(raw)
    fails("Invalid creator pack", *run, "--out", tmp_path / "rejected")


@pytest.mark.parametrize(
    ("problem", "reason"),
    [
        ("unknown operation", "Unsupported school builder operations"),
        ("cycle", "Unsupported school builder operations"),
        ("external input", "Invalid school builder document limits"),
        ("large dictionary", "Invalid school builder operation parameters"),
    ],
)
def test_builder_rejects_invalid_recipe_before_publishing(tmp_path, problem, reason):
    original = REPO / "examples/school-library/recipe.json"
    recipe = json.loads(original.read_text(encoding="utf-8"))
    if problem == "unknown operation":
        recipe["steps"][0]["op"] = "unknown"
    elif problem == "cycle":
        recipe["steps"][0]["from"] = ["kit"]
    elif problem == "external input":
        recipe["input"]["suffix"] = "https://example.invalid/"
    else:
        recipe["steps"][0]["params"]["max_dict_kib"] = 100
    draft = tmp_path / "invalid.json"
    draft.write_text(json.dumps(recipe), encoding="utf-8")
    secret, _ = identity(tmp_path, "creator")
    output = tmp_path / "invalid.tfpack"
    fails(
        reason, "publish-builder", draft, "--id", "librarian/school-builder",
        "--version", "1.0.0", "--revision", 1, "--license", "CC0-1.0", "--key", secret, "--out", output,
    )
    assert not output.exists()
