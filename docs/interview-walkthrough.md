# Eight-minute walkthrough

## 0:00–1:00 — Begin with the business consequence

Open the [generated report](evidence/report.md). Spend, conversion and revenue totals change for different reasons. The objective is an auditable explanation of variance, not forcing all sources to agree. These are entirely synthetic data and executed local results.

## 1:00–2:00 — Show the ingestion boundary

Open [reconciliation](evidence/reconciliation.json). Point to accepted-delivery row count, admitted/duplicate/quarantined outcomes and the separately rejected schema delivery. Show one hash and row number in quarantine. A file replay is a receipt lookup; a repeated semantic row in a different file has a distinct row outcome.

## 2:00–3:00 — Explain warehouse grain

Open [campaign SQL](../src/marketing_reliability/sql/campaign_daily.sql). Paid source facts, web events and CRM opportunities have different keys. Aggregate measures to campaign/day before combining them; joining raw event rows to spend would multiply money. A campaign ID is a supplied relationship, not attribution proof.

## 3:00–4:00 — Show correction mechanics

Open [pipeline runs](evidence/pipeline-runs.json). A conversion changes date, an opportunity changes value and date, and two records are deleted. Explain why both old and new partitions must become dirty, and why a lower source revision arriving late cannot overwrite a newer one. Original publications remain inspectable.

## 4:00–5:00 — Show gates refusing publication

Compare the stale-feed and unresolved-reference phases. A recent event timestamp would not establish feed freshness. Coverage is an explicit producer assertion, checked against a declared run date. Missing reference rows cannot disappear silently through the model's inner join: a separate check blocks publication.

## 5:00–6:00 — Show actual crash recovery

Open [recovery evidence](evidence/recovery.json). Each process exited abruptly with code 86. Before commit, admission/build/publication rolls back. After commit, retry uses the durable receipt or status. The publication tests use changed conversion values so a partial exposure would be visible. Explain the single-writer assumption and the separate filesystem boundary.

## 6:00–7:00 — Prove the backfill

Compare the one-day and full rebuild runs. A candidate copies untouched partitions and rebuilds selected dates. The independent Python aggregator checks the entire resulting table; a too-narrow correction scope fails. This provides strong correctness evidence at small scale, while full validation and copied snapshots limit performance.

## 7:00–8:00 — State the honest operating boundary

Show [verification](evidence/verification.json), then [cloud translation](cloud-translation.md). Explain installed-wheel testing and local execution. AWS, Redshift, live CRM/ad APIs, distributed writers and hosted CI were not executed. Redshift's unenforced uniqueness constraints are an example of why moving SQL alone would not prove equivalent reliability.

## Questions this project lets Richard answer in an interview

- **How do you distinguish duplicate deliveries from duplicate business records?** Byte-addressed receipts versus source/ID/revision and normalized payload comparison.
- **What makes an incremental model wrong after a correction?** Rebuilding only the new date leaves an old contribution behind; the full oracle exposes it.
- **How do you evolve a contract?** Explicit v1/v2 interpretation, common normalized meaning and refusal of undeclared changes.
- **Is a fresh feed complete?** No. Coverage, quarantine and unresolved references express different evidence.
- **When should bad data stop reporting?** Here malformed rows are disclosed exclusions, while unresolved references and stale feeds block a new publication. A financial-close policy would need stricter admission/completeness gates.
- **How do you recover after a process dies?** Query durable receipts/status, retry the same identity, and avoid advancing a publication separately from its commit.
- **How do you validate SQL beyond row counts?** Compare every dimension/measure to a separate Python aggregation and inject equal-count corruption.
- **What does a safe backfill change?** Only selected candidate partitions; exposure waits for full reconciliation and current-epoch checks.
- **Why no dbt, Airflow or SCD2?** One model and explicit transactional boundaries make them unnecessary here; discuss when a larger DAG or different history requirement changes that decision.
- **What would break in a cloud port?** Different write coordination, loading semantics and unenforced warehouse keys require new proofs, not renamed components.
