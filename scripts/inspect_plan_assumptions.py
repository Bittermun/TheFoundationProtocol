"""Report bounded, in-memory observations used by the Foundation execution plan.

This is an inspection tool, not a release gate. A true concern_observed value
records a counterexample to an intended property. Run from any directory with
Python 3.11+; it prints JSON and does not write application state or use a network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tfp-foundation-protocol")]

from tfp_client.lib.lexicon.hlt import (  # noqa: E402
    DeltaType,
    HierarchicalLexiconTree,
    LexiconDelta,
    LexiconSynchronizer,
)
from tfp_client.lib.publish.mesh_aggregator import MeshAggregator  # noqa: E402
from tfp_core_v4.node import TFPNode  # noqa: E402


def inspect() -> dict:
    observations = []

    def record(probe_id: str, concern: bool, **details) -> None:
        observations.append({"id": probe_id, "concern_observed": concern, **details})

    tree = HierarchicalLexiconTree()
    domain = tree.add_domain("probe", "v1.0.0", "1" * 64)
    sync = LexiconSynchronizer(tree)
    delta = LexiconDelta(DeltaType.ADDITION, "v1.0.0", "v1.0.1", {"a": "b"})
    accepted = sync.process_sync_response(domain, [delta], "0" * 64)
    record("P1", accepted and tree.compute_merkle_root() != "0" * 64,
           accepted=accepted, sync_state=sync.state.value,
           adapter_retained=tree.get_latest_version("probe")["adapter_count"] == 1)

    tree = HierarchicalLexiconTree()
    older = tree.add_domain("probe", "v1.0.0", "1" * 64)
    tree.add_domain("probe", "v2.0.0", "2" * 64)
    before_root = tree.compute_merkle_root()
    before_version = tree.get_latest_version("probe")["version"]
    tree.domain_names["probe"] = older
    after_version = tree.get_latest_version("probe")["version"]
    record("P2", before_root == tree.compute_merkle_root() and before_version != after_version,
           before_version=before_version, after_version=after_version,
           root_unchanged=before_root == tree.compute_merkle_root())

    tree = HierarchicalLexiconTree()
    tree.add_domain("probe", "v2.0.0", "2" * 64)
    tree.add_domain("probe", "v1.0.0", "1" * 64)
    selected = tree.get_latest_version("probe")["version"]
    record("P3", selected == "v1.0.0", selected_after_older_announcement=selected)

    tree = HierarchicalLexiconTree()
    domain = tree.add_domain("probe", "v1.0.0", "1" * 64)
    tree.add_adapter(domain, "v1.9.0", b"nine", "anchor")
    tree.add_adapter(domain, "v1.10.0", b"ten", "anchor")
    selected = tree.get_latest_version("probe")["version"]
    record("P4", selected == "v1.9.0", selected_adapter=selected)

    timestamp = "2026-09-12T00:00:00+00:00"
    left = LexiconDelta(DeltaType.ADDITION, "v1", "v2", {"a": "1", "b": "2"}, timestamp)
    right = LexiconDelta(DeltaType.ADDITION, "v1", "v2", {"b": "2", "a": "1"}, timestamp)
    record("P5", left.data == right.data and left.compute_hash() != right.compute_hash(),
           equal_logical_data=left.data == right.data,
           different_serialized_hashes=left.compute_hash() != right.compute_hash())

    with patch("tfp_client.lib.publish.mesh_aggregator.time.time", return_value=0.0):
        agg = MeshAggregator()
        agg.receive_announcement("1" * 64, {})
        agg.increment_demand("1" * 64, 10)
    with patch("tfp_client.lib.publish.mesh_aggregator.time.time", return_value=3600.0):
        short = agg.aggregate_demand_signals(time_window=1.0)
        long = agg.aggregate_demand_signals(time_window=7200.0)
    record("P6", short == long and short["1" * 64]["request_count"] == 10,
           one_second_window_count=short["1" * 64]["request_count"],
           two_hour_window_count=long["1" * 64]["request_count"])

    data = b"Foundation planning probe. " * 4
    node = TFPNode(symbol_size=256)
    recipe = node.publish(data)
    try:
        recovered = node.fetch(recipe.root_hash, simulated_loss=1.0)
        record("P7", recovered == data, exact_recovery_at_full_simulated_loss=recovered == data,
               scope="Local TFPNode only; fallback reads its original droplet store")
    except Exception as exc:
        record("P7", False, exception=type(exc).__name__)

    node = TFPNode(symbol_size=256)
    node.publish(data)
    node.publish(data)
    telemetry = node.get_telemetry()
    record("P8", telemetry["bandwidth_saved_pct"] > 0,
           reported_bandwidth_saved_pct=telemetry["bandwidth_saved_pct"],
           workload="Two local publish calls; no fetch or network operation")

    source_paths = [
        "tfp-foundation-protocol/tfp_client/lib/lexicon/hlt/tree.py",
        "tfp-foundation-protocol/tfp_client/lib/lexicon/hlt/delta.py",
        "tfp-foundation-protocol/tfp_client/lib/lexicon/hlt/sync.py",
        "tfp-foundation-protocol/tfp_client/lib/publish/mesh_aggregator.py",
        "tfp_core_v4/node.py",
        "tfp_core_v4/cdc.py",
        "tfp_core_v4/fountain.py",
        "scripts/inspect_plan_assumptions.py",
    ]
    return {
        "scope": "Bounded local component inspection; not full-suite or deployed-network evidence",
        "python": platform.python_version(),
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths},
        "observations": observations,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), indent=2))
