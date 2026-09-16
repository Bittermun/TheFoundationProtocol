"""Independently reconcile the frozen experiment's byte totals and exact decoding."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

import zstandard as zstd


def audit(corpus_path, run_dir):
    report = json.loads((run_dir / "results.json").read_text())
    corpus_bytes = corpus_path.read_bytes()
    assert hashlib.sha256(corpus_bytes).hexdigest() == report["corpus_sha256"]
    records = sorted([row["text"].encode() for row in json.loads(corpus_bytes)["records"] if row["split"] == "test"],
                     key=lambda row: hashlib.sha256(row).hexdigest())
    artifact = (run_dir / report["selected"]["file"]).read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == report["selected"]["sha256"]
    dictionary = zstd.ZstdCompressionDict(artifact)
    plain_encoder = zstd.ZstdCompressor(level=3, write_checksum=True)
    dict_encoder = zstd.ZstdCompressor(level=3, write_checksum=True, dict_data=dictionary)
    plain_decoder = zstd.ZstdDecompressor()
    dict_decoder = zstd.ZstdDecompressor(dict_data=dictionary)
    baseline, shared, used = [], [], []
    for original in records:
        plain = plain_encoder.compress(original)
        encoded = dict_encoder.compress(original)
        assert plain_decoder.decompress(plain) == original
        assert dict_decoder.decompress(encoded) == original
        baseline.append(41 + min(len(original), len(plain)))
        shared.append(41 + min(len(original), len(plain), len(encoded)))
        used.append(len(encoded) < min(len(original), len(plain)))
    for row in report["scenarios"]:
        n = row["unique_records"]
        delivery = 41 + len(artifact) if any(used[:n]) else 0
        assert row["baseline_bytes"] == sum(baseline[:n])
        assert row["shared_payload_bytes"] == sum(shared[:n])
        assert row["shared_cold_bytes"] == sum(shared[:n]) + delivery
        assert row["shared_plus_one_redelivery_bytes"] == sum(shared[:n]) + 2 * delivery
        batch = b"".join(struct.pack(">I", len(record)) + record for record in records[:n])
        assert row["batch_baseline_bytes"] == 41 + min(len(batch), len(plain_encoder.compress(batch)))
    return {"passed": True, "records_verified": len(records), "scenario_totals_reconciled": len(report["scenarios"]),
            "scope": "Independent encoding/decoding and arithmetic reconciliation; not a real network transfer audit"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.corpus, args.run_dir)))
