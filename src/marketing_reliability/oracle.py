"""Independent full aggregation of normalized payloads, without warehouse SQL."""

from collections import defaultdict

from .contracts import METRICS


def aggregate(inputs):
    campaigns = {
        row["id"]: row["name"]
        for source, row in inputs
        if source == "campaigns" and row["op"] == "upsert"
    }
    groups = defaultdict(lambda: [0] * len(METRICS))
    unresolved = []
    for source, row in inputs:
        if source == "campaigns" or row["op"] == "delete":
            continue
        if row["campaign_id"] not in campaigns:
            unresolved.append(
                {"source": source, "id": row["id"], "campaign_id": row["campaign_id"]}
            )
            continue
        bucket = groups[row["day"], row["campaign_id"]]
        for i, metric in enumerate(METRICS):
            bucket[i] += row.get(metric, 0)
    result = [
        [date, campaign, campaigns[campaign], *values]
        for (date, campaign), values in sorted(groups.items())
    ]
    return result, sorted(unresolved, key=lambda r: (r["source"], r["id"]))
