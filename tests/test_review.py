import json
import random
import subprocess
import sys

import pytest

from conftest import ROOT, delivery, fixture
from marketing_reliability.warehouse import GateError, Warehouse


def test_missing_landing_object_detected(baseline):
    next(baseline.landing.glob("*.json")).unlink()
    with pytest.raises(GateError, match="missing"):
        baseline.reconcile()


def test_lineage_resolves_to_exact_original_record(baseline):
    for source, key, revision, op, _, _, checksum, line in baseline.lineage(1):
        original = json.loads((baseline.landing / f"{checksum}.json").read_bytes())
        row = original["rows"][line - 1]
        assert (original["source"], row["id"], row["revision"], row["op"]) == (
            source,
            key,
            revision,
            op,
        )


def test_bad_higher_revision_keeps_prior_accepted_value_and_exposes_quarantine(baseline):
    row = {**fixture(3)["rows"][0], "revision": 2, "conversions": "bad"}
    baseline.ingest(delivery("web", [row], "bad-correction"))
    run = baseline.plan("2026-09-04")
    baseline.build(run)
    baseline.publish(run)
    assert sum(r[6] for r in baseline.table()) == 4
    assert len(baseline.reconcile()["quarantine"]) == 2


def test_deleted_campaign_blocks_dependent_facts(baseline):
    baseline.ingest(
        delivery("campaigns", [{"id": "search", "revision": 2, "op": "delete"}], "delete-reference")
    )
    run = baseline.plan("2026-09-04")
    assert baseline.build(run)["evidence"]["unresolved"]
    with pytest.raises(GateError, match="unresolved"):
        baseline.publish(run)


@pytest.mark.parametrize("seed", [3, 19, 87])
def test_arrival_order_does_not_change_revision_winner(tmp_path, seed):
    values = [
        {**fixture(3)["rows"][0], "revision": rev, "conversions": rev % 2} for rev in range(1, 11)
    ]
    random.Random(seed).shuffle(values)
    with Warehouse(tmp_path / "ordered") as w:
        for i, value in enumerate(values):
            w.ingest(delivery("web", [value], f"b{i}"))
        assert w.rows("SELECT revision,conversions FROM latest") == [[10, 0]]
        assert w.reconcile()["superseded_versions"] == 9


def test_per_delivery_accounting_catches_balanced_cross_file_corruption(baseline):
    hashes = baseline.rows("SELECT hash FROM deliveries ORDER BY hash")
    baseline.db.execute("UPDATE deliveries SET row_count=row_count+1 WHERE hash=?", hashes[0])
    baseline.db.execute("UPDATE deliveries SET row_count=row_count-1 WHERE hash=?", hashes[1])
    with pytest.raises(GateError, match="per-delivery"):
        baseline.reconcile()


def test_rejected_cli_returns_nonzero_json(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "marketing_reliability.cli",
            "--state",
            str(tmp_path / "cli"),
            "ingest",
            str(ROOT / "fixtures/10-unsupported-schema.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "rejected"


def test_second_process_writer_is_refused(baseline):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "marketing_reliability.cli",
            "--state",
            str(baseline.root),
            "report",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "lock" in result.stderr.lower() or "another process" in result.stderr.lower()


def test_build_with_blockers_returns_nonzero_cli(tmp_path):
    state = tmp_path / "cli-blocked"
    with Warehouse(state) as w:
        run = w.plan("2026-09-04")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "marketing_reliability.cli",
            "--state",
            str(state),
            "build",
            str(run),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert len(json.loads(result.stdout)["evidence"]["blockers"]) == 4
