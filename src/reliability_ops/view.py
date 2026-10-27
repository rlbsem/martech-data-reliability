"""Live read-only warehouse/journal inspection, independent of controller write credentials."""

import json
from pathlib import Path

import duckdb

from marketing_reliability.warehouse import Warehouse

from .client import Client, Unknown
from .common import hash_value, sqlite
from .oracle import variances, verify


def state(config):
    root = Path(config["state"])
    w = Warehouse.__new__(Warehouse)
    w.root = root / "warehouse"
    w.landing = w.root / "landing"
    w.db = duckdb.connect(str(w.root / "warehouse.duckdb"), read_only=True)
    try:
        with sqlite(root / "operations.sqlite", readonly=True) as c:
            journal = {
                t: [dict(r) for r in c.execute("SELECT * FROM " + t)]
                for t in ["deliveries", "checkpoints", "observations", "audit"]
            }
        candidates = []
        for name, run, hashes, gates in w.rows(
            "SELECT name,run_id,accepted_hashes,gates FROM ops_candidates ORDER BY run_id"
        ):
            candidates.append(
                {
                    "name": name,
                    "run": w.run(run),
                    "table": w.table(run),
                    "raw_oracle": verify(w, run, json.loads(hashes)),
                    "source_variances": variances(w, run),
                    "lineage": w.lineage(run),
                    "operating_gates": json.loads(gates),
                }
            )
        sources = {}
        for service, source in config["sources"].items():
            try:
                body = Client(source).catalog()
                sources[service] = {
                    "status": "observed",
                    "catalog": body,
                    "sha256": hash_value(body),
                }
            except Unknown as error:
                sources[service] = {
                    "status": "unknown",
                    "reason": str(error),
                }
        return {
            "synthetic": True,
            "read_only": True,
            "currency": "USD",
            "sources": sources,
            "journal": journal,
            "candidates": candidates,
            "warehouse": w.reconcile(),
            "opportunity_day": w.rows(
                "SELECT * FROM ops_opportunity_day ORDER BY run_id,day,campaign_id"
            ),
        }
    finally:
        w.close()


def verify_live(config):
    body = state(config)
    active = body["warehouse"]["active_run"]
    selected = next(c for c in body["candidates"] if c["run"]["id"] == active)
    assert not selected["raw_oracle"]["differences"] and not selected["raw_oracle"]["unresolved"]
    assert selected["run"]["evidence"]["table_sha256"] == selected["raw_oracle"]["table_sha256"]
    revenue = {(r[0], r[1]): r[7] for r in selected["raw_oracle"]["expected"]}
    opportunities = [
        [r["day"], r["campaign"], r["opportunities"], revenue[r["day"], r["campaign"]]]
        for r in selected["raw_oracle"]["crm_opportunity_grain"]
    ]
    sql_opportunities = [r[1:] for r in body["opportunity_day"] if r[0] == active]
    assert opportunities == sql_opportunities, "opportunity_day_sql_grain_or_value_difference"
    receipts = 0
    for service, source in config["sources"].items():
        assert body["sources"][service]["status"] == "observed"
        entries = body["sources"][service]["catalog"]["deliveries"]
        checkpoint = next(
            r["seq"] for r in body["journal"]["checkpoints"] if r["service"] == service
        )
        assert checkpoint == len(entries)
        for entry in entries:
            assert Client(source).read_ack(entry)
            receipts += 1
    return {
        "status": "passed",
        "independent_source_receipts": receipts,
        "active_run": active,
        "oracle_rows": len(selected["raw_oracle"]["actual"]),
        "differences": [],
        "source_row_accounting": selected["raw_oracle"]["row_dispositions"],
        "source_rows": selected["raw_oracle"]["accepted_rows"],
        "reported_closed_won_opportunities": sum(r[2] for r in opportunities),
        "opportunity_day_models_compared": len(opportunities),
        "totals": selected["raw_oracle"]["totals"],
        "read_only": True,
        "native_marketing_vendor_calls": 0,
    }
