"""Execute the operating story; all financial values are synthetic source facts in USD cents."""

import json
import subprocess
import sys
from pathlib import Path

from marketing_reliability.contracts import canonical
from marketing_reliability.warehouse import GateError

from .client import Unknown
from .common import OWNERS, save, sqlite
from .controller import Operations
from .runtime import source_hash
from .source import append, claim

FIXTURES = Path.cwd() / "fixtures"


def raw_fixture(number):
    return next(FIXTURES.glob(f"{number:02d}-*.json")).read_bytes()


def run(config, source_configs, controller_file):
    checks, phases = [], []

    def require(name, expected, observed):
        if expected != observed:
            raise AssertionError(name)
        checks.append({"check": name, "expected": expected, "observed": observed, "passed": True})

    def claims(service, revision, **kwargs):
        for feed in OWNERS[service]:
            claim(source_configs[service], feed, revision, **kwargs)

    def blocked(ops, name, **kwargs):
        previous = ops.w.table()
        candidate = ops.candidate(name, **kwargs)
        try:
            ops.publish(candidate)
        except GateError:
            require(name + "_preserves_last_verified_publication", previous, ops.w.table())
        else:
            raise AssertionError("invalid_candidate_published: " + name)
        return candidate

    for service, numbers in {"advertising": [1, 2], "website": [3], "crm": [4]}.items():
        for n in numbers:
            data = raw_fixture(n)
            append(source_configs[service], json.loads(data)["source"], data)
        claims(service, 1)
    with Operations(config) as ops:
        for service in OWNERS:
            ops.sync(service)
        baseline = ops.candidate("Verified baseline")
        before = ops.publish(baseline)
        require("baseline_source_spend_cents", 36000, before["totals"]["cost_cents"])
        require("baseline_observed_conversions", 4, before["totals"]["conversions"])
        require("baseline_reported_crm_value_cents", 150000, before["totals"]["revenue_cents"])
        require(
            "all_source_rows_accounted",
            before["accepted_rows"],
            sum(before["row_dispositions"].values()),
        )
        versions = before["unique_versions"]
        require("checkpoint_replay_has_no_new_delivery", [], ops.sync("website"))
        require(
            "checkpoint_replay_has_no_duplicate_versions",
            versions,
            ops.check(baseline)["unique_versions"],
        )
        phases.append({"phase": "baseline", "run": baseline})
        with sqlite(source_configs["website"]["db"]) as c:
            c.execute("UPDATE faults SET mode='outage'")
        try:
            ops.sync("website")
        except Unknown:
            require("actual_http_source_outage_detected", True, True)
        else:
            raise AssertionError("outage_not_detected")
        blocked(ops, "HTTP outage")
        with sqlite(source_configs["website"]["db"]) as c:
            c.execute("UPDATE faults SET mode='none'")
        require("source_recovery_preserves_checkpoint", [], ops.sync("website"))
        blocked(ops, "Stale source coverage", as_of="2026-09-06")
    # A real child dies after DuckDB commit, before the controller checkpoint/ack.
    append(source_configs["website"], "web", raw_fixture(5))
    claims("website", 2, through="2026-09-05")
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "reliability_ops.worker",
            "--config",
            str(controller_file),
            "ingest",
            "--crash",
            "after_ingest",
        ],
        capture_output=True,
        timeout=60,
    )
    require("actual_ingestion_process_termination", 86, child.returncode)
    with sqlite(source_configs["website"]["db"]) as c:
        c.execute("UPDATE faults SET mode='lost_ack'")
    with Operations(config) as ops:
        ops.sync("website")
        with sqlite(source_configs["website"]["db"]) as c:
            ack = c.execute("SELECT count(*) FROM acknowledgments WHERE seq=2").fetchone()[0]
            requests = [r[0] for r in c.execute("SELECT result FROM requests WHERE seq=2")]
        require("lost_ack_has_one_durable_source_receipt", 1, ack)
        require("lost_ack_recovered_without_duplicate_post", ["committed_ack_lost"], requests)
        for service, n in [("advertising", 6), ("crm", 7)]:
            data = raw_fixture(n)
            append(source_configs[service], json.loads(data)["source"], data)
            claims(service, 2, through="2026-09-05")
            ops.sync(service)
        blocked(ops, "Unresolved campaign references", as_of="2026-09-06", through="2026-09-05")
        bad = append(source_configs["advertising"], "paid_media", raw_fixture(10))
        ops.sync("advertising")
        claims("advertising", 3, through="2026-09-05")
        blocked(ops, "Unsupported schema", as_of="2026-09-06", through="2026-09-05")
        repair = json.loads(raw_fixture(9))
        repair["batch_id"] = "supported-schema-repair"
        append(
            source_configs["advertising"], "paid_media", canonical(repair).encode(), replaces=[bad]
        )
        data = raw_fixture(8)
        append(source_configs["advertising"], "campaigns", data)
        claims("advertising", 4, through="2026-09-05")
        ops.sync("advertising")
        corrected = ops.candidate(
            "Corrected source metrics", as_of="2026-09-06", through="2026-09-05"
        )
        after = ops.publish(corrected)
        require("corrected_spend_cents", 41000, after["totals"]["cost_cents"])
        require("corrected_conversions", 6, after["totals"]["conversions"])
        require("corrected_reported_crm_cents", 115000, after["totals"]["revenue_cents"])
        require("old_published_version_unchanged", before["actual"], ops.w.table(baseline))
        phases.append({"phase": "corrected", "run": corrected})
        claims("website", 3, complete=False, through="2026-09-05")
        blocked(ops, "Incomplete reporting period", as_of="2026-09-06", through="2026-09-05")
        claims("website", 4, through="2026-09-05")
        moving = ops.candidate(
            "Source changes during publication", as_of="2026-09-06", through="2026-09-05"
        )
        append(
            source_configs["website"],
            "web",
            canonical(
                {
                    "source": "web",
                    "batch_id": "post-pin-data",
                    "schema_version": 1,
                    "covered_through": "2026-09-05",
                    "rows": [
                        {
                            "id": "w2",
                            "revision": 2,
                            "op": "upsert",
                            "day": "2026-09-01",
                            "campaign_id": "search",
                            "conversions": 0,
                        }
                    ],
                }
            ).encode(),
        )
        claims("website", 5, through="2026-09-05")
        try:
            ops.publish(moving)
        except GateError:
            require("changed_source_snapshot_blocks_publish", after["actual"], ops.w.table())
        else:
            raise AssertionError("changed_source_published")
        ops.sync("website")
        corrupted = ops.candidate(
            "Equal row count, wrong values", as_of="2026-09-06", through="2026-09-05"
        )
        count = len(ops.w.table(corrupted))
        ops.w.db.execute(
            "UPDATE mart SET cost_cents=cost_cents+1 WHERE run_id=? AND day='2026-09-01' AND campaign_id='search'",
            [corrupted],
        )
        require("corruption_preserves_row_count", count, len(ops.w.table(corrupted)))
        require(
            "independent_oracle_detects_exact_value_difference",
            1,
            len(ops.check(corrupted)["differences"]),
        )
        try:
            ops.publish(corrupted)
        except GateError:
            require(
                "value_reconciliation_failure_preserves_publication", after["actual"], ops.w.table()
            )
        else:
            raise AssertionError("wrong_values_published")
        # Plan the native crash run at the same freshness coordinate as the worker default.
        ops.candidate("crash-rebuild", as_of="2026-09-06", through="2026-09-05")
        # Retain a planned run for the actual process-death experiment.
        run = ops.w.plan("2026-09-06", full=True)
        pins, gates = ops.gates("2026-09-01", "2026-09-05")
        hashes = [
            r[0]
            for r in ops.w.rows(
                "SELECT hash FROM deliveries WHERE status='accepted' ORDER BY rowid"
            )
        ]
        ops.w.db.execute(
            "INSERT INTO ops_candidates VALUES(?,?,?,?,?,?,?)",
            [
                "Actual rebuild termination",
                run,
                canonical(pins),
                canonical(hashes),
                canonical(gates),
                "2026-09-01",
                "2026-09-05",
            ],
        )
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "reliability_ops.worker",
            "--config",
            str(controller_file),
            "build",
            "--name",
            "Actual rebuild termination",
            "--crash",
            "during_build",
        ],
        capture_output=True,
        timeout=60,
    )
    require("actual_rebuild_process_termination", 86, child.returncode)
    with Operations(config) as ops:
        require("rebuild_death_preserves_active_report", after["actual"], ops.w.table())
        require("rebuild_transaction_rolled_back", "planned", ops.w.run(run)["status"])
        ops.w.build(run)
        ops.publish(run)
        incremental = ops.candidate(
            "Affected-date rebuild", as_of="2026-09-06", through="2026-09-05", dates=["2026-09-01"]
        )
        ops.publish(incremental)
        full = ops.candidate(
            "Independent full rebuild", as_of="2026-09-06", through="2026-09-05", full=True
        )
        final = ops.publish(full)
        require("incremental_full_table_parity", ops.w.table(incremental), final["actual"])
        require("final_oracle_value_differences", [], final["differences"])
        require("final_unresolved_references", [], final["unresolved"])
        snapshot = ops.snapshot()
    source_state = {}
    for s, conf in source_configs.items():
        with sqlite(conf["db"], readonly=True) as c:
            source_state[s] = {
                t: [dict(r) for r in c.execute("SELECT * FROM " + t)]
                for t in ["acknowledgments", "requests"]
            }
    report = {
        "schema": "reliability-operations.v1",
        "synthetic": True,
        "currency": "USD",
        "source_hash": source_hash(),
        "execution": "actual_local_http_separate_sqlite_sources_duckdb_and_process_death",
        "checks": checks,
        "phases": phases,
        "snapshot": snapshot,
        "independent_source_receipts": source_state,
        "native_marketing_vendor_calls": 0,
    }
    save(Path(config["state"]) / "acceptance.json", report)
    return report
