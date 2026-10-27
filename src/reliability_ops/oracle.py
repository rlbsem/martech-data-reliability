"""Reconstruct winners and metrics from retained raw deliveries, not model SQL or its oracle."""

import json
from collections import Counter

from marketing_reliability.contracts import (
    ContractError,
    METRICS,
    canonical,
    digest,
    envelope,
    record,
)


def verify(warehouse, run_id, hashes):
    versions, dispositions, accounting = {}, Counter(), []
    for sha in hashes:
        raw = (warehouse.landing / (sha + ".json")).read_bytes()
        assert digest(raw) == sha, "raw_source_bytes_changed"
        batch = envelope(raw)
        per_delivery = Counter()
        for line, value in enumerate(batch["rows"], 1):
            try:
                normalized = record(batch["source"], batch["schema_version"], value)
                if normalized.get("day", batch["covered_through"]) > batch["covered_through"]:
                    raise ContractError("beyond coverage")
            except ContractError:
                disposition = "quarantined"
            else:
                key = (batch["source"], normalized["id"], normalized["revision"])
                if key in versions:
                    assert versions[key]["payload"] == normalized, "accepted_revision_conflict"
                    disposition = "duplicate"
                else:
                    versions[key] = {
                        "source": batch["source"],
                        "payload": normalized,
                        "hash": sha,
                        "line": line,
                    }
                    disposition = "admitted"
            actual = warehouse.rows(
                "SELECT disposition,raw FROM row_receipts WHERE hash=? AND line=?", [sha, line]
            )
            assert actual == [[disposition, canonical(value)]], "raw_row_disposition_difference"
            per_delivery[disposition] += 1
            dispositions[disposition] += 1
        assert len(batch["rows"]) == sum(per_delivery.values())
        accounting.append({"hash": sha, "rows": len(batch["rows"]), "outcomes": dict(per_delivery)})
    latest = {}
    for (source, key, revision), value in versions.items():
        if (source, key) not in latest or latest[source, key]["payload"]["revision"] < revision:
            latest[source, key] = value
    expected_inputs = sorted(
        [
            [s, key, v["payload"]["revision"], canonical(v["payload"]), v["hash"], v["line"]]
            for (s, key), v in latest.items()
        ]
    )
    actual_inputs = warehouse.rows(
        "SELECT source,id,revision,payload,hash,line FROM run_inputs WHERE run_id=? ORDER BY source,id",
        [run_id],
    )
    assert actual_inputs == expected_inputs, "independent_latest_revision_or_lineage_difference"
    campaigns = {
        key: v["payload"]["name"]
        for (s, key), v in latest.items()
        if s == "campaigns" and v["payload"]["op"] == "upsert"
    }
    totals, unresolved, opportunities = {}, [], {}
    for (source, key), value in latest.items():
        p = value["payload"]
        if source == "campaigns" or p["op"] == "delete":
            continue
        if p["campaign_id"] not in campaigns:
            unresolved.append({"source": source, "id": key, "campaign_id": p["campaign_id"]})
            continue
        group = (p["day"], p["campaign_id"])
        bucket = totals.setdefault(group, [0, 0, 0, 0, 0])
        if source == "paid_media":
            bucket[0] += p["cost_cents"]
            bucket[1] += p["impressions"]
            bucket[2] += p["clicks"]
        elif source == "web":
            bucket[3] += p["conversions"]
        elif source == "crm":
            bucket[4] += p["revenue_cents"]
            opportunities[group] = opportunities.get(group, 0) + 1
    expected = [[d, c, campaigns[c], *values] for (d, c), values in sorted(totals.items())]
    actual = warehouse.table(run_id)
    differences = []
    a, b = {tuple(r[:2]): r for r in expected}, {tuple(r[:2]): r for r in actual}
    for key in sorted(a.keys() | b.keys()):
        if a.get(key) != b.get(key):
            differences.append(
                {"day": key[0], "campaign": key[1], "expected": a.get(key), "actual": b.get(key)}
            )
    return {
        "method": "retained_raw_bytes_independent_revision_selection_and_source_specific_python_arithmetic",
        "contract_normalizer_shared": True,
        "aggregation_shared": False,
        "accepted_deliveries": accounting,
        "accepted_rows": sum(dispositions.values()),
        "row_dispositions": dict(dispositions),
        "unique_versions": len(versions),
        "latest_records": len(latest),
        "superseded": len(versions) - len(latest),
        "tombstones": sum(v["payload"]["op"] == "delete" for v in latest.values()),
        "expected": expected,
        "actual": actual,
        "differences": differences,
        "unresolved": sorted(unresolved, key=lambda x: (x["source"], x["id"])),
        "totals": {m: sum(r[i + 3] for r in expected) for i, m in enumerate(METRICS)},
        "crm_opportunity_grain": [
            {"day": k[0], "campaign": k[1], "opportunities": v}
            for k, v in sorted(opportunities.items())
        ],
        "raw_lineage_verified": len(expected_inputs),
        "table_sha256": digest(canonical(actual).encode()),
    }


def variances(warehouse, run_id):
    base = warehouse.run(run_id)["base"]
    old = {
        (r[0], r[1]): json.loads(r[2])
        for r in warehouse.rows("SELECT source,id,payload FROM run_inputs WHERE run_id=?", [base])
    }
    new = {
        (r[0], r[1]): json.loads(r[2])
        for r in warehouse.rows("SELECT source,id,payload FROM run_inputs WHERE run_id=?", [run_id])
    }
    return [
        {"source": k[0], "record": k[1], "before": old.get(k), "after": new.get(k)}
        for k in sorted(old.keys() | new.keys())
        if old.get(k) != new.get(k)
    ]
