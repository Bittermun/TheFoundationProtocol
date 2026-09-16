"""Execute the frozen exploratory shared-dictionary comparison, without network claims."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import time

import psutil
import zstandard as zstd

HEADER = struct.Struct(">BII32s")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frame(data, ordinary, shared=None):
    options = [(0, data), (1, ordinary.compress(data))]
    if shared is not None:
        options.append((2, shared.compress(data)))
    mode, body = min(options, key=lambda pair: len(pair[1]))
    return HEADER.pack(mode, len(data), len(body), hashlib.sha256(data).digest()) + body


def restore(encoded, ordinary, shared):
    mode, size, length, expected = HEADER.unpack(encoded[:HEADER.size])
    body = encoded[HEADER.size:]
    if len(body) != length or mode not in (0, 1, 2):
        raise ValueError("Invalid frame")
    if mode == 0:
        data = body
    else:
        decoder = ordinary if mode == 1 else shared
        if decoder is None:
            raise ValueError("Missing dictionary")
        data = decoder.decompress(body, max_output_size=size)
    if len(data) != size or hashlib.sha256(data).digest() != expected:
        raise ValueError("Content integrity mismatch")
    return data


def load_dictionary(data, expected):
    if digest(data) != expected:
        raise ValueError("Dictionary identity mismatch")
    return zstd.ZstdCompressionDict(data)


def measure(records, dictionary, level):
    ordinary = zstd.ZstdCompressor(level=level, write_checksum=True)
    shared = zstd.ZstdCompressor(level=level, write_checksum=True, dict_data=dictionary)
    encoded_a = [frame(data, ordinary) for data in records]
    encoded_b = [frame(data, ordinary, shared) for data in records]
    dec_a = zstd.ZstdDecompressor()
    dec_b = zstd.ZstdDecompressor(dict_data=dictionary)
    timings = {"ordinary": [], "shared": []}
    # Alternate order to reduce systematic cache/order bias; verify every decode.
    for repeat in range(30):
        variants = [("ordinary", encoded_a), ("shared", encoded_b)]
        if repeat % 2:
            variants.reverse()
        for name, frames in variants:
            for original, encoded in zip(records, frames):
                start = time.perf_counter_ns()
                recovered = restore(encoded, dec_a, dec_b)
                elapsed = time.perf_counter_ns() - start
                if recovered != original:
                    raise ValueError("Non-exact restoration")
                timings[name].append(elapsed)
    return encoded_a, encoded_b, {name: statistics.quantiles(values, n=100)[94] / 1000 for name, values in timings.items()}


def train_worker(path, size):
    records = [base64.b64decode(row) for row in json.loads(Path(path).read_text())]
    start, cpu = time.perf_counter(), time.process_time()
    dictionary = zstd.train_dictionary(size, records, k=50, d=8, steps=1, threads=0, dict_id=1, level=3)
    wall, cpu = time.perf_counter() - start, time.process_time() - cpu
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)
    if peak is None:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    print(json.dumps({"data": base64.b64encode(dictionary.as_bytes()).decode(), "wall_seconds": wall,
                      "cpu_seconds": cpu, "process_peak_rss_bytes": peak}))


def run(args):
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    corpus_bytes = args.corpus.read_bytes()
    if digest(corpus_bytes) != contract["corpus_sha256"]:
        raise ValueError("Frozen corpus identity mismatch")
    if zstd.__version__ != "0.25.0":
        raise ValueError("Run requires python-zstandard 0.25.0")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    corpus = json.loads(corpus_bytes)
    splits = {name: sorted([row["text"].encode() for row in corpus["records"] if row["split"] == name], key=digest)
              for name in ("train", "tune", "test")}
    train_path = args.output_dir / "train-only.json"
    train_path.write_text(json.dumps([base64.b64encode(row).decode() for row in splits["train"]]))
    candidates = []
    for size in contract["candidates_bytes"]:
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--train", str(train_path), "--size", str(size)],
                               capture_output=True, text=True, check=True, timeout=30)
        result = json.loads(child.stdout)
        data = base64.b64decode(result.pop("data"))
        dictionary = load_dictionary(data, digest(data))
        compressor = zstd.ZstdCompressor(level=3, write_checksum=True)
        shared = zstd.ZstdCompressor(level=3, write_checksum=True, dict_data=dictionary)
        frames = [frame(row, compressor, shared) for row in splits["tune"]]
        delivery = HEADER.size + len(data) if any(row[0] == 2 for row in frames) else 0
        path = args.output_dir / f"dictionary-{size}.zdict"
        path.write_bytes(data)
        candidates.append({"size": len(data), "sha256": digest(data), "tune_total_bytes": sum(map(len, frames)) + delivery,
                           "file": path.name, **result})
    selected = min(candidates, key=lambda row: (row["tune_total_bytes"], row["size"]))
    # Written before touching test performance. No test-driven retuning.
    (args.output_dir / "selection.json").write_text(json.dumps({"contract_sha256": digest(contract_bytes), "candidates": candidates, "selected": selected}, indent=2))
    data = (args.output_dir / selected["file"]).read_bytes()
    dictionary = load_dictionary(data, selected["sha256"])
    records = splits["test"]
    ordinary, shared, timings = measure(records, dictionary, 3)
    compressor = zstd.ZstdCompressor(level=3, write_checksum=True)
    scenarios = []
    for count in contract["client_unique_records"]:
        subset = records[:count]
        count = len(subset)
        a, b = sum(map(len, ordinary[:count])), sum(map(len, shared[:count]))
        delivery = HEADER.size + len(data) if any(row[0] == 2 for row in shared[:count]) else 0
        batch = b"".join(struct.pack(">I", len(row)) + row for row in subset)
        batch_frame = frame(batch, compressor)
        if restore(batch_frame, zstd.ZstdDecompressor(), None) != batch:
            raise ValueError("Batch restoration failed")
        scenarios.append({"unique_records": count, "baseline_bytes": a, "shared_payload_bytes": b,
                          "dictionary_delivery_bytes": delivery, "shared_cold_bytes": b + delivery,
                          "shared_cold_savings_fraction": 1 - (b + delivery) / a,
                          "shared_with_cached_dictionary_bytes": b,
                          "shared_plus_one_redelivery_bytes": b + 2 * delivery,
                          "shared_plus_training_input_acquisition_bytes": b + delivery + sum(map(len, splits["train"])),
                          "batch_baseline_bytes": len(batch_frame), "exact_content_repeat_incremental_bytes_both": 0})
    controls = {}
    for name, rows in (
        ("pseudorandom", [hashlib.shake_256(f"control-{i}".encode()).digest(len(row)) for i, row in enumerate(records)]),
        ("already_compressed", [compressor.compress(row) for row in records]),
    ):
        a, b, _ = measure(rows, dictionary, 3)
        uses = sum(row[0] == 2 for row in b)
        controls[name] = {"exact": True, "ordinary_bytes": sum(map(len, a)), "shared_cold_bytes": sum(map(len, b)) + (HEADER.size + len(data) if uses else 0), "dictionary_encoded_records": uses}
    try:
        load_dictionary(data + b"corruption", selected["sha256"])
    except ValueError:
        controls["wrong_dictionary_rejected"] = True
    else:
        raise ValueError("Bad dictionary accepted")
    for original, encoded in zip(records, ordinary):
        if restore(encoded, zstd.ZstdDecompressor(), None) != original:
            raise ValueError("Dictionary-free fallback failed")
    controls["missing_dictionary_fallback_exact"] = True
    at100 = next(row for row in scenarios if row["unique_records"] == 100)
    gates = {"cold_savings_100": at100["shared_cold_savings_fraction"] >= 0.10,
             "decode_p95": timings["shared"] <= timings["ordinary"] + max(timings["ordinary"] * 0.05, 5),
             "training_time": selected["wall_seconds"] <= 5,
             "training_memory": selected["process_peak_rss_bytes"] <= 268435456}
    report = {"contract_id": contract["id"], "contract_sha256": digest(contract_bytes), "corpus_sha256": digest(corpus_bytes),
              "script_sha256": digest(Path(__file__).read_bytes()), "python": sys.version, "platform": platform.platform(),
              "zstandard": zstd.__version__, "zstd_library": zstd.ZSTD_VERSION, "training_input_bytes": sum(map(len, splits["train"])),
              "selected": selected, "test_records": len(records), "scenarios": scenarios, "decode_p95_microseconds": timings,
              "controls": controls, "exploratory_gates": gates, "exploratory_pass": all(gates.values()),
              "claim_level": "L1 exploratory local comparison; no network/pooling/deployment quality claim",
              "limitations": contract["limitations"]}
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train")
    parser.add_argument("--size", type=int)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.train:
        train_worker(args.train, args.size)
    else:
        run(args)
