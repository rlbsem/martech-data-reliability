"""Deterministic synthetic inputs; this is a fixture authoring tool, not the pipeline."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def row(key, **fields):
    return {"id": key, "revision": 1, "op": "upsert", **fields}


def generate():
    p1 = row(
        "p1", day="2026-09-01", campaign_id="search", cost_cents=10000, impressions=1000, clicks=100
    )
    w1 = row("w1", day="2026-09-01", campaign_id="search", conversions=1)
    cases = [
        (
            "01-campaigns",
            "campaigns",
            1,
            "2026-09-03",
            [row("search", name="Search"), row("social", name="Social")],
        ),
        (
            "02-paid",
            "paid_media",
            1,
            "2026-09-03",
            [
                p1,
                row(
                    "p2",
                    day="2026-09-01",
                    campaign_id="social",
                    cost_cents=6000,
                    impressions=600,
                    clicks=60,
                ),
                row(
                    "p3",
                    day="2026-09-02",
                    campaign_id="search",
                    cost_cents=12000,
                    impressions=1200,
                    clicks=120,
                ),
                row(
                    "p4",
                    day="2026-09-03",
                    campaign_id="social",
                    cost_cents=8000,
                    impressions=800,
                    clicks=80,
                ),
            ],
        ),
        (
            "03-web",
            "web",
            1,
            "2026-09-03",
            [
                w1,
                row("w2", day="2026-09-01", campaign_id="search", conversions=0),
                row("w3", day="2026-09-01", campaign_id="social", conversions=1),
                row("w4", day="2026-09-02", campaign_id="search", conversions=1),
                row("w5", day="2026-09-03", campaign_id="social", conversions=1),
                w1,
                row("bad", day="2026-09-01", campaign_id="social", conversions="1"),
            ],
        ),
        (
            "04-crm",
            "crm",
            1,
            "2026-09-03",
            [
                row("o1", day="2026-09-01", campaign_id="search", revenue_cents=50000),
                row("o2", day="2026-09-02", campaign_id="search", revenue_cents=70000),
                row("o3", day="2026-09-03", campaign_id="social", revenue_cents=30000),
            ],
        ),
        (
            "05-web-corrections",
            "web",
            1,
            "2026-09-06",
            [
                row("w6", day="2026-09-01", campaign_id="social", conversions=1),
                {**w1, "revision": 2, "day": "2026-09-02"},
                {"id": "w5", "revision": 2, "op": "delete"},
                w1,
                row("bad", revision=2, day="2026-09-01", campaign_id="social", conversions=1),
                row("w7", day="2026-09-03", campaign_id="partner", conversions=1),
            ],
        ),
        (
            "06-paid-v2",
            "paid_media",
            2,
            "2026-09-06",
            [
                {**p1, "revision": 3, "cost_cents": 11000, "currency": "USD"},
                row(
                    "p5",
                    day="2026-09-03",
                    campaign_id="partner",
                    cost_cents=4000,
                    impressions=400,
                    clicks=40,
                    currency="USD",
                ),
                row(
                    "eur",
                    day="2026-09-03",
                    campaign_id="partner",
                    cost_cents=700,
                    impressions=70,
                    clicks=7,
                    currency="EUR",
                ),
            ],
        ),
        (
            "07-crm-corrections",
            "crm",
            1,
            "2026-09-06",
            [
                row("o2", revision=2, day="2026-09-03", campaign_id="search", revenue_cents=65000),
                {"id": "o3", "revision": 2, "op": "delete"},
            ],
        ),
        (
            "08-campaign-repair",
            "campaigns",
            1,
            "2026-09-06",
            [row("partner", name="Partner"), row("search", revision=2, name="Paid Search")],
        ),
        (
            "09-paid-out-of-order",
            "paid_media",
            1,
            "2026-09-06",
            [{**p1, "revision": 2, "cost_cents": 999}],
        ),
        (
            "10-unsupported-schema",
            "paid_media",
            3,
            "2026-09-06",
            [{**p1, "spend_dollars": "110.00"}],
        ),
    ]
    target = ROOT / "fixtures"
    target.mkdir(exist_ok=True)
    for name, source, version, through, rows in cases:
        payload = {
            "source": source,
            "batch_id": name,
            "schema_version": version,
            "covered_through": through,
            "rows": rows,
        }
        target.joinpath(name + ".json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    generate()
