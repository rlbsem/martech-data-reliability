# Engineering demonstration walkthrough

## 0:00 to 1:00: Begin with the business consequence

Open the [generated report](evidence/report.md). Spend, conversion and revenue totals change for different reasons. The objective is an auditable explanation of variance, not forcing all sources to agree. These are entirely synthetic data and executed local results.

## 1:00 to 2:00: Show the ingestion boundary

Open [reconciliation](evidence/reconciliation.json). Point to accepted-delivery row count, admitted/duplicate/quarantined outcomes and the separately rejected schema delivery. Show one hash and row number in quarantine. A file replay is a receipt lookup; a repeated semantic row in a different file has a distinct row outcome.

## 2:00 to 3:00: Explain warehouse grain

Open [campaign SQL](../src/marketing_reliability/sql/campaign_daily.sql). Paid source facts, web events and CRM opportunities have different keys. Aggregate measures to campaign/day before combining them; joining raw event rows to spend would multiply money. A campaign ID is a supplied relationship, not attribution proof.

## 3:00 to 4:00: Show correction mechanics

Open [pipeline runs](evidence/pipeline-runs.json). A conversion changes date, an opportunity changes value and date, and two records are deleted. Explain why both old and new partitions must become dirty, and why a lower source revision arriving late cannot overwrite a newer one. Original publications remain inspectable.

## 4:00 to 5:00: Show gates refusing publication

Compare the stale-feed and unresolved-reference phases. A recent event timestamp would not establish feed freshness. Coverage is an explicit producer assertion, checked against a declared run date. Missing reference rows cannot disappear silently through the model's inner join: a separate check blocks publication.

## 5:00 to 6:00: Show actual crash recovery

Open [recovery evidence](evidence/recovery.json). Each process exited abruptly with code 86. Before commit, admission/build/publication rolls back. After commit, retry uses the durable receipt or status. The publication tests use changed conversion values so a partial exposure would be visible. Explain the single-writer assumption and the separate filesystem boundary.

## 6:00 to 7:00: Prove the backfill

Compare the one-day and full rebuild runs. A candidate copies untouched partitions and rebuilds selected dates. The independent Python aggregator checks the entire resulting table; a too-narrow correction scope fails. This provides strong correctness evidence at small scale, while full validation and copied snapshots limit performance.

## 7:00 to 8:00: Verify operating boundaries

Show [verification](evidence/verification.json), then [cloud translation](cloud-translation.md). Explain installed-wheel testing and local execution. AWS, Redshift, live CRM/ad APIs and distributed writers were not executed. [Hosted GitHub Actions verification](https://github.com/rlbsem/martech-data-reliability/actions) passed on Windows and Ubuntu for the published build. Redshift's unenforced uniqueness constraints are an example of why moving SQL alone would not prove equivalent reliability.
