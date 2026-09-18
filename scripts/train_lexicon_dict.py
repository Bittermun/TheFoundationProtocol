#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Domain Lexicon Dictionary Factory for The Foundation Protocol.

Automates training of specialized Zstandard domain dictionaries (e.g. medical,
technical, disaster relief) for extreme bandwidth reduction on edge devices
and lossy radio/mesh transports.

Usage:
  python scripts/train_lexicon_dict.py --domain medical --output lexicons/medical.zdict
  python scripts/train_lexicon_dict.py --domain technical --output lexicons/technical.zdict
  python scripts/train_lexicon_dict.py --input-dir /path/to/docs --output lexicons/custom.zdict
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, List, Tuple

try:
    import zstandard as zstd
except ImportError:
    print("[ERROR] zstandard is required: pip install zstandard", file=sys.stderr)
    sys.exit(1)


# Built-in high-density specialized domain training corpora generator
def generate_domain_samples(domain: str, count: int = 200) -> List[bytes]:
    """Generates structured, realistic domain sample records for dictionary training."""
    samples = []
    if domain == "medical":
        terms = [
            "acute myocardial infarction", "triage priority ALPHA", "epinephrine 1mg/ml IV",
            "hemostatic gauze application", "airway patency verified", "Glasgow Coma Scale GCS-13",
            "cricothyroidotomy protocol", "lactated ringers infusion 500ml/hr", "SpO2 94% on ambient air",
            "thoracostomy chest tube insertion", "tension pneumothorax decompression", "burn dressing sterile",
            "hypothermia prevention thermal blanket", "broad spectrum cephalosporin 2g", "tourniquet applied 0845Z"
        ]
        for i in range(count):
            record = {
                "schema": "tfp.med.triage.v1",
                "patient_id": f"MED-{1000 + i}",
                "timestamp_utc": 1774000000 + i * 60,
                "vitals": {
                    "heart_rate_bpm": 70 + (i % 45),
                    "blood_pressure": f"{110 + (i % 20)}/{70 + (i % 15)}",
                    "respiratory_rate": 16 + (i % 8),
                    "o2_saturation_pct": 92 + (i % 8),
                },
                "assessment": f"Patient presenting with {terms[i % len(terms)]}. Requires immediate monitoring.",
                "interventions": [terms[(i + j) % len(terms)] for j in range(3)],
                "evacuation_priority": "URGENT" if i % 4 == 0 else "PRIORITY",
            }
            samples.append(json.dumps(record, indent=2).encode("utf-8"))

    elif domain == "disaster_relief":
        situations = [
            "river flood stage 4 cresting", "seismic magnitude 6.8 aftershock", "power grid black start required",
            "potable water distribution point active", "SATCOM uplink degraded by storm", "bridge integrity compromised",
            "shelter capacity 85% occupied", "HAM radio net 146.520MHz simplex relay", "food rations supply 72hr buffer"
        ]
        for i in range(count):
            record = {
                "schema": "tfp.relief.incident.v2",
                "incident_id": f"INC-RELIEF-{2000 + i}",
                "sector": f"SECTOR-{'ABCDEF'[i % 6]}-{i % 10}",
                "coordinates": {"lat": 12.3456 + (i * 0.01), "lon": -45.6789 - (i * 0.01)},
                "situation": situations[i % len(situations)],
                "resources_requested": ["diesel generator 5kW", "water purification tablets", "satellite transceivers"],
                "mesh_relay_status": "RELAY_OPERATIONAL",
                "severity_code": 3 + (i % 3),
            }
            samples.append(json.dumps(record, indent=2).encode("utf-8"))

    else:  # technical / default
        tech_terms = [
            "XOR-LDPC rateless fountain droplet", "systematic parity generator GF(2)",
            "ContentDefinedChunker FastCDC 64-bit rolling hash", "Merkle tree SHA3-256 root audit proof",
            "Ed25519 sovereign asymmetric signature envelope", "async HTTP shard peer transport pool",
            "Freivalds probabilistic matrix verification O(n^2)", "Zstandard trained dictionary compression"
        ]
        for i in range(count):
            record = {
                "protocol": "TheFoundationProtocol",
                "version": "4.1",
                "module": f"tfp.core.{tech_terms[i % len(tech_terms)].split()[0].lower()}",
                "task_id": f"TASK-AST-{3000 + i}",
                "capabilities": tech_terms,
                "invariants": ["no-mock-in-production", "constant-time-crypto", "asymmetric-work-verification"],
                "active_peers": [f"192.168.1.{10 + j}:8080" for j in range(4)],
            }
            samples.append(json.dumps(record, indent=2).encode("utf-8"))

    return samples


def train_lexicon_dictionary(
    samples: List[bytes], dict_size: int = 112640
) -> Tuple[zstd.ZstdCompressionDict, Dict[str, float]]:
    """Trains a Zstandard compression dictionary from sample payloads and evaluates savings."""
    if not samples:
        raise ValueError("Cannot train dictionary on empty sample set")

    # Split 80/20 train/test
    split_idx = int(len(samples) * 0.8)
    train_samples = samples[:split_idx]
    test_samples = samples[split_idx:]

    # Train dictionary using zstandard
    trained_dict = zstd.train_dictionary(dict_size=dict_size, samples=train_samples)

    # Benchmark against generic compression without dictionary
    cctx_plain = zstd.ZstdCompressor(level=3)
    cctx_dict = zstd.ZstdCompressor(level=3, dict_data=trained_dict)

    raw_total = sum(len(s) for s in test_samples)
    plain_total = sum(len(cctx_plain.compress(s)) for s in test_samples)
    dict_total = sum(len(cctx_dict.compress(s)) for s in test_samples)

    plain_ratio = raw_total / plain_total if plain_total else 1.0
    dict_ratio = raw_total / dict_total if dict_total else 1.0
    bandwidth_savings_pct = (1.0 - (dict_total / plain_total)) * 100.0 if plain_total else 0.0

    metrics = {
        "raw_bytes": raw_total,
        "generic_compressed_bytes": plain_total,
        "dict_compressed_bytes": dict_total,
        "generic_ratio": round(plain_ratio, 2),
        "dict_ratio": round(dict_ratio, 2),
        "bandwidth_savings_vs_generic_pct": round(bandwidth_savings_pct, 2),
        "dictionary_id": trained_dict.dict_id(),
        "dictionary_size_bytes": len(trained_dict.as_bytes()),
    }
    return trained_dict, metrics


def main():
    parser = argparse.ArgumentParser(description="Train specialized Zstandard domain dictionaries for TFP")
    parser.add_argument("--domain", choices=["medical", "disaster_relief", "technical"], default="medical")
    parser.add_argument("--input-dir", type=str, help="Optional directory of sample files to train on")
    parser.add_argument("--output", type=str, required=True, help="Output path for the trained .zdict file")
    parser.add_argument("--dict-size", type=int, default=112640, help="Max dictionary size in bytes (default: 110KB)")
    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.input_dir:
        input_dir = Path(args.input_dir)
        samples = [p.read_bytes() for p in input_dir.rglob("*") if p.is_file() and p.stat().st_size > 50]
        print(f"Loaded {len(samples)} custom sample files from {input_dir}")
    else:
        samples = generate_domain_samples(args.domain, count=250)
        print(f"Generated {len(samples)} specialized training samples for domain '{args.domain}'")

    print(f"Training Zstandard dictionary (target size: {args.dict_size} bytes)...")
    dictionary, metrics = train_lexicon_dictionary(samples, dict_size=args.dict_size)

    out_path.write_bytes(dictionary.as_bytes())
    print(f"[SUCCESS] Dictionary saved to {out_path}")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
