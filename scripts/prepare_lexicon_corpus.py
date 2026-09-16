"""Freeze a reproducible, exploratory documentation-record corpus from Git.

The request/update scenarios are synthetic. This corpus establishes a local
experiment, not an adopter workload or a claim about semantic reconstruction.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True, timeout=30).stdout


def prepare(revision):
    revision = git("rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    paths = git("ls-tree", "-r", "--name-only", revision, "--", "docs", "README.md").decode().splitlines()
    records, sources, seen = [], [], set()
    for path in sorted(p for p in paths if p.endswith(".md")):
        raw = git("show", f"{revision}:{path}")
        bucket = int(hashlib.sha256(path.encode()).hexdigest(), 16) % 10
        split = "train" if bucket < 6 else "tune" if bucket < 8 else "test"
        sources.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "split": split})
        paragraphs = re.split(r"\n\s*\n", raw.decode("utf-8").replace("\r\n", "\n"))
        for index, paragraph in enumerate(paragraphs):
            data = (paragraph.strip() + "\n").encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            if not 80 <= len(data) <= 4096 or digest in seen:
                continue
            seen.add(digest)
            records.append({"id": digest, "source": path, "paragraph": index, "split": split,
                            "bytes": len(data), "text": data.decode("utf-8")})
    counts = {split: sum(r["split"] == split for r in records) for split in ("train", "tune", "test")}
    if any(count < 10 for count in counts.values()):
        raise ValueError(f"Insufficient source-separated records: {counts}")
    return {"schema_version": 1, "source_commit": revision,
            "license_source": "LICENSE at source_commit; local repository analysis only",
            "scope": "Exploratory documentation records; not an observed outside-project workload",
            "normalization": "UTF-8, CRLF to LF, blank-line paragraphs, strip then append LF; records 80..4096 bytes",
            "split_rule": "SHA256(source path) modulo 10: 0..5 train, 6..7 tune, 8..9 test; exact duplicate records removed globally",
            "sources": sources, "record_counts": counts, "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus = prepare(args.revision)
    encoded = (json.dumps(corpus, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.output.exists() and args.output.read_bytes() != encoded:
        raise SystemExit("Refusing to overwrite a different frozen corpus; select a new output path.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(json.dumps({"source_commit": corpus["source_commit"], "sha256": hashlib.sha256(encoded).hexdigest(),
                      "record_counts": corpus["record_counts"], "source_count": len(corpus["sources"]),
                      "bytes": sum(record["bytes"] for record in corpus["records"])}, indent=2))


if __name__ == "__main__":
    main()
