import json
import random

import pytest

from conftest import delivery, fixture, load
from marketing_reliability.warehouse import GateError


def publish(w, dates=None, full=False):
    run = w.plan("2026-09-04", dates=dates, full=full)
    w.build(run)
    w.publish(run)
    return run


def test_replay_and_semantic_row_duplicate_are_distinct(baseline):
    before = baseline.reconcile()
    assert load(baseline, 3)["replayed"]
    assert baseline.reconcile() == before
    row = fixture(2)["rows"][0]
    baseline.ingest(delivery("paid_media", [{**row, "currency": "USD"}], "new", version=2))
    after = baseline.reconcile()
    assert after["admitted_versions"] == before["admitted_versions"]
    assert after["row_dispositions"]["duplicate"] == 2


def test_batch_identity_collision_does_not_advance_coverage(baseline):
    batch = fixture(2)
    batch["covered_through"] = "2026-09-20"
    result = baseline.ingest(json.dumps(batch).encode())
    assert result["status"] == "rejected"
    assert baseline.rows("SELECT through_day FROM coverage WHERE source='paid_media'") == [
        ["2026-09-03"]
    ]


def test_conflicting_revision_rejects_entire_delivery(baseline):
    rows = [fixture(3)["rows"][1], {**fixture(3)["rows"][0], "conversions": 0}]
    rows[0]["id"] = "new"
    before = baseline.rows("SELECT * FROM versions ORDER BY source,id,revision")
    result = baseline.ingest(delivery("web", rows, "conflict"))
    assert result["status"] == "rejected"
    assert baseline.rows("SELECT * FROM versions ORDER BY source,id,revision") == before
    assert not baseline.rows("SELECT * FROM row_receipts WHERE hash=?", [result["hash"]])


def test_lower_revision_retained_without_resurrecting_deleted_row(baseline):
    original = fixture(3)["rows"][0]
    baseline.ingest(delivery("web", [{"id": "w1", "revision": 4, "op": "delete"}], "delete"))
    baseline.ingest(delivery("web", [{**original, "revision": 2}], "late"))
    publish(baseline)
    assert sum(r[6] for r in baseline.table()) == 3
    assert baseline.reconcile()["current_tombstones"] == 1


def test_correction_dirties_old_and_new_dates(baseline):
    original = fixture(3)["rows"][0]
    baseline.ingest(delivery("web", [{**original, "revision": 2, "day": "2026-09-02"}], "moved"))
    assert baseline.reconcile()["dirty_dates"] == ["2026-09-01", "2026-09-02"]
    partial = baseline.plan("2026-09-04", dates=["2026-09-02"])
    assert not baseline.build(partial)["evidence"]["independent_full_match"]
    with pytest.raises(GateError, match="independent"):
        baseline.publish(partial)
    run = publish(baseline)
    assert baseline.run(run)["scope"] == ["2026-09-01", "2026-09-02"]
    assert baseline.table(1)[0][6] == 1
    assert baseline.table()[0][6] == 0


def test_single_day_rebuild_copies_other_days_without_changing_bytes(baseline):
    before = baseline.table()
    run = publish(baseline, dates=["2026-09-01"])
    assert baseline.run(run)["scope"] == ["2026-09-01"]
    assert baseline.table() == before
    assert baseline.validate(run)["independent_full_match"]


def test_delete_last_row_removes_partition(warehouse):
    for source in ("campaigns", "paid_media", "web", "crm"):
        rows = (
            [{"id": "a", "revision": 1, "op": "upsert", "name": "A"}]
            if source == "campaigns"
            else []
        )
        warehouse.ingest(delivery(source, rows))
    warehouse.ingest(
        delivery(
            "web",
            [
                {
                    "id": "w",
                    "revision": 1,
                    "op": "upsert",
                    "day": "2026-09-01",
                    "campaign_id": "a",
                    "conversions": 1,
                }
            ],
            "one",
        )
    )
    publish(warehouse)
    warehouse.ingest(delivery("web", [{"id": "w", "revision": 2, "op": "delete"}], "gone"))
    publish(warehouse)
    assert warehouse.table() == []
    assert warehouse.reconcile()["dirty_dates"] == []


def test_reference_change_rebuilds_historical_partitions(baseline):
    baseline.ingest(
        delivery(
            "campaigns",
            [{"id": "search", "revision": 2, "op": "upsert", "name": "Renamed"}],
            "rename",
        )
    )
    run = publish(baseline)
    assert baseline.run(run)["scope"] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert {r[2] for r in baseline.table() if r[1] == "search"} == {"Renamed"}


def test_unknown_reference_is_gate_not_silent_inner_join_loss(baseline):
    baseline.ingest(
        delivery(
            "web", [{**fixture(3)["rows"][0], "id": "orphan", "campaign_id": "absent"}], "orphan"
        )
    )
    run = baseline.plan("2026-09-04")
    evidence = baseline.build(run)["evidence"]
    assert evidence["unresolved"] == [{"source": "web", "id": "orphan", "campaign_id": "absent"}]
    with pytest.raises(GateError, match="unresolved"):
        baseline.publish(run)
    assert baseline.reconcile()["active_run"] == 1


@pytest.mark.parametrize("as_of", ["2026-09-02", "2026-09-05"])
def test_source_coverage_blocks_future_assertion_and_staleness(baseline, as_of):
    run = baseline.plan(as_of)
    assert len(baseline.build(run)["evidence"]["blockers"]) == 4
    with pytest.raises(GateError, match="coverage"):
        baseline.publish(run)


def test_missing_feed_is_not_zero(warehouse):
    load(warehouse, 1)
    run = warehouse.plan("2026-09-04")
    assert len(warehouse.build(run)["evidence"]["blockers"]) == 3


def test_plan_cannot_publish_after_new_ingestion(baseline):
    run = baseline.plan("2026-09-04")
    baseline.ingest(delivery("web", [], "heartbeat"))
    baseline.build(run)
    with pytest.raises(GateError, match="stale"):
        baseline.publish(run)


def test_sibling_candidates_cannot_overwrite_each_other(baseline):
    a, b = baseline.plan("2026-09-04"), baseline.plan("2026-09-04")
    baseline.build(a)
    baseline.build(b)
    baseline.publish(a)
    with pytest.raises(GateError, match="stale"):
        baseline.publish(b)
    baseline.publish(1)
    assert baseline.reconcile()["active_run"] == a


def test_equal_count_metric_corruption_is_caught(baseline):
    run = baseline.plan("2026-09-04")
    baseline.build(run)
    baseline.db.execute(
        "UPDATE mart SET cost_cents=cost_cents+1 WHERE run_id=? AND day='2026-09-01'", [run]
    )
    with pytest.raises(GateError, match="independent"):
        baseline.publish(run)


def test_implementation_mismatch_requires_new_plan(baseline):
    run = baseline.plan("2026-09-04")
    baseline.db.execute("UPDATE runs SET implementation='different' WHERE id=?", [run])
    with pytest.raises(GateError, match="implementation"):
        baseline.build(run)


def test_landing_corruption_fails_closed(baseline):
    raw = next(baseline.landing.glob("*.json"))
    raw.write_bytes(b"changed")
    with pytest.raises(GateError, match="checksum"):
        baseline.reconcile()


def test_fanout_does_not_multiply_spend(baseline):
    rows = [{**fixture(3)["rows"][0], "id": f"event_{i}"} for i in range(100)]
    baseline.ingest(delivery("web", rows, "many"))
    publish(baseline)
    assert sum(r[3] for r in baseline.table()) == 36000
    assert sum(r[6] for r in baseline.table()) == 104


def test_randomized_revisions_incremental_match_independent_model(baseline):
    rng = random.Random(240930)
    latest = {}
    for cycle in range(20):
        key = f"r{rng.randrange(6)}"
        revision = cycle + 1
        value = {
            "id": key,
            "revision": revision,
            "op": "upsert",
            "day": f"2026-09-0{rng.randrange(1, 4)}",
            "campaign_id": rng.choice(["search", "social"]),
            "conversions": rng.randrange(2),
        }
        if cycle % 5 == 0:
            value = {"id": key, "revision": revision, "op": "delete"}
        latest[key] = value
        baseline.ingest(delivery("web", [value], f"cycle{cycle}"))
        incremental = publish(baseline)
        full = publish(baseline, full=True)
        assert baseline.table(incremental) == baseline.table(full)
        assert sum(r[6] for r in baseline.table()) == 4 + sum(
            v.get("conversions", 0) for v in latest.values()
        )
