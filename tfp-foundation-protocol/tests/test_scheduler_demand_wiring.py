"""
Tests for GatewayScheduler.schedule_from_aggregator() demand wiring.

Validates that the scheduler correctly reads live demand signals from a
MeshAggregator, schedules slots in demand-score order, and resets demand
counters after scheduling to prevent double-counting.
"""

from tfp_broadcaster.src.gateway.scheduler import BroadcastSlot, GatewayScheduler
from tfp_client.lib.publish.mesh_aggregator import MeshAggregator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _populated_aggregator(
    hashes_and_counts: dict, region: str = "test"
) -> MeshAggregator:
    """Return a MeshAggregator pre-populated with announcements and demand counts."""
    agg = MeshAggregator(region=region)
    for hash_hex, count in hashes_and_counts.items():
        agg.receive_announcement(hash_hex, {"title": f"content-{hash_hex[:8]}"})
        agg.increment_demand(hash_hex, count)
    return agg


# ---------------------------------------------------------------------------
# Basic wiring
# ---------------------------------------------------------------------------


class TestScheduleFromAggregator:
    def test_schedules_slots_from_aggregator_demand(self):
        agg = _populated_aggregator({"a" * 64: 50, "b" * 64: 20, "c" * 64: 5})
        sched = GatewayScheduler(max_slots_per_epoch=3)

        slots = sched.schedule_from_aggregator(agg, epoch=1)

        assert len(slots) > 0
        assert all(isinstance(s, BroadcastSlot) for s in slots)

    def test_slots_ordered_by_demand_score_descending(self):
        agg = _populated_aggregator({"a" * 64: 80, "b" * 64: 40, "c" * 64: 10})
        sched = GatewayScheduler(max_slots_per_epoch=3)
        slots = sched.schedule_from_aggregator(agg, epoch=1)

        assert len(slots) == 3
        scores = [s.demand_score for s in slots]
        assert scores == sorted(scores, reverse=True)

    def test_respects_max_slots_per_epoch(self):
        agg = _populated_aggregator({f"{i:064d}": (100 - i * 5) for i in range(10)})
        sched = GatewayScheduler(max_slots_per_epoch=4)
        slots = sched.schedule_from_aggregator(agg, epoch=1)

        assert len(slots) <= 4

    def test_max_slots_override(self):
        agg = _populated_aggregator({"x" * 64: 60, "y" * 64: 40, "z" * 64: 20})
        sched = GatewayScheduler(max_slots_per_epoch=10)
        slots = sched.schedule_from_aggregator(agg, epoch=1, max_slots=2)

        assert len(slots) <= 2

    def test_empty_aggregator_produces_no_slots(self):
        agg = MeshAggregator()
        sched = GatewayScheduler(max_slots_per_epoch=5)
        slots = sched.schedule_from_aggregator(agg, epoch=1)

        assert slots == []

    def test_scheduled_content_hashes_match_top_demand(self):
        hash_a = "a" * 64
        hash_b = "b" * 64
        agg = _populated_aggregator({hash_a: 90, hash_b: 10})
        sched = GatewayScheduler(max_slots_per_epoch=2)
        slots = sched.schedule_from_aggregator(agg, epoch=1)

        scheduled_hashes = {s.content_hash for s in slots}
        assert hash_a in scheduled_hashes
        assert hash_b in scheduled_hashes

    def test_slots_appear_in_epoch_schedule(self):
        agg = _populated_aggregator({"d" * 64: 55})
        sched = GatewayScheduler(max_slots_per_epoch=5)
        sched.schedule_from_aggregator(agg, epoch=7)

        schedule = sched.get_schedule(epoch=7)
        assert len(schedule) >= 1

    def test_slots_have_correct_status(self):
        agg = _populated_aggregator({"e" * 64: 30})
        sched = GatewayScheduler()
        slots = sched.schedule_from_aggregator(agg, epoch=1)

        assert all(s.status == "scheduled" for s in slots)

    def test_slots_have_correct_epoch(self):
        agg = _populated_aggregator({"f" * 64: 25})
        sched = GatewayScheduler()
        slots = sched.schedule_from_aggregator(agg, epoch=42)

        assert all(s.epoch == 42 for s in slots)


# ---------------------------------------------------------------------------
# Demand reset after scheduling
# ---------------------------------------------------------------------------


class TestDemandResetAfterScheduling:
    def test_demand_reset_for_scheduled_items(self):
        hash_a = "a" * 64
        agg = _populated_aggregator({hash_a: 70})
        sched = GatewayScheduler(max_slots_per_epoch=5)

        slots = sched.schedule_from_aggregator(agg, epoch=1)
        scheduled_hashes = {s.content_hash for s in slots}

        # Demand for scheduled items should be reset to prevent double-counting
        for hash_hex in scheduled_hashes:
            demand = agg.get_demand_for_hash(hash_hex)
            assert demand is None or demand.get("request_count", 0) == 0, (
                f"Demand not reset for {hash_hex}"
            )

    def test_unscheduled_items_demand_not_reset(self):
        """Items that didn't fit in the epoch should retain their demand count."""
        hashes = {f"{i:064d}": (100 - i * 10) for i in range(6)}
        agg = _populated_aggregator(hashes)
        sched = GatewayScheduler(max_slots_per_epoch=2)

        slots = sched.schedule_from_aggregator(agg, epoch=1)
        scheduled_hashes = {s.content_hash for s in slots}
        unscheduled = set(hashes.keys()) - scheduled_hashes

        for hash_hex in unscheduled:
            demand = agg.get_demand_for_hash(hash_hex)
            # Unscheduled items keep their demand count
            assert demand is not None and demand["request_count"] > 0


# ---------------------------------------------------------------------------
# Integration: export_for_gateway round-trip
# ---------------------------------------------------------------------------


class TestExportImportRoundTrip:
    def test_receive_aggregated_demand_then_schedule(self):
        """Verify the older JSON-serialized demand path still works alongside the new direct path."""
        agg = _populated_aggregator({"g" * 64: 45, "h" * 64: 15})
        demand_bytes = agg.export_for_gateway()

        sched = GatewayScheduler(max_slots_per_epoch=5)
        sched.receive_aggregated_demand(demand_bytes)
        slots = sched.schedule_from_demand(epoch=1)

        assert len(slots) > 0

    def test_schedule_from_aggregator_and_export_gateway_consistent(self):
        """Both methods schedule the same top-demand hashes."""
        hashes = {"i" * 64: 70, "j" * 64: 30}
        agg1 = _populated_aggregator(hashes)
        agg2 = _populated_aggregator(hashes)

        sched1 = GatewayScheduler(max_slots_per_epoch=2)
        slots1 = sched1.schedule_from_aggregator(agg1, epoch=1)

        sched2 = GatewayScheduler(max_slots_per_epoch=2)
        sched2.receive_aggregated_demand(agg2.export_for_gateway())
        slots2 = sched2.schedule_from_demand(epoch=1)

        hashes1 = {s.content_hash for s in slots1}
        hashes2 = {s.content_hash for s in slots2}
        assert hashes1 == hashes2
