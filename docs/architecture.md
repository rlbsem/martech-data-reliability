# Architecture and correctness contract

The hiring question is whether unreliable recurring marketing deliveries can become explainable, recoverable warehouse publications. The unit of correctness is a source revision plus a published campaign/day table, not a customer action, audience decision or platform migration.

## Chosen stack

Python 3.12 performs bounded file admission and run management. DuckDB 1.3.2 executes persisted SQL aggregation, windowed revision selection, snapshots and atomic pointer changes. Versions are pinned to the actual tested environment, not presented as the newest releases. The Python standard library supplies checksums, atomic file replacement and the independent arithmetic oracle.

The pipeline has two meaningful boundaries: filesystem landing to warehouse admission, and candidate to publication. A database server, broker and scheduler would each add a recovery surface without improving this small local proof. There is no dbt wrapper: the one analytical model and explicit transactional publication protocol are directly inspectable. A larger model DAG would justify dbt's dependency management and data testing. No SCD2 dimension is needed: campaign labels use current accepted reference data for a new report, while old publications retain their old labels.

DuckDB documents ACID transactions and snapshot isolation. The implementation also deliberately serializes processes: a second writer must wait until the first closes the database or fail with DuckDB's file-lock error. It does not coordinate distributed writers. [Transactions](https://duckdb.org/docs/current/sql/statements/transactions) and [concurrency](https://duckdb.org/docs/lts/connect/concurrency).

## Grains and semantics

| Data | Grain / key | Meaning |
|---|---|---|
| Delivery | SHA-256 bytes; unique accepted source/batch ID | Exact source artifact and receipt |
| Row receipt | Delivery hash + one-based row number | Admitted, duplicate or quarantined |
| Version | Source + ID + positive revision | Full replacement record or deletion tombstone |
| Paid media | Stable source fact ID | A reported spend/counter fact for a campaign/day |
| Web | Stable event ID | One observed event, conversion 0 or 1 |
| CRM | Stable opportunity ID | Closed-won revenue fact at its supplied recognition date |
| Campaign | Campaign ID | Current label, or explicit removal |
| Mart | Run + day + campaign | Additive source measures in integer units |

Campaign IDs are supplied relationships. The pipeline does not establish attribution, campaign eligibility or the truth of a CRM win. No cross-source customer identity is needed. Money is USD cents; quantities are integers. The mart avoids revenue/spend ratios because those measures have different recognition semantics.

## Admission transaction

1. Hash raw bytes; write and flush a temporary object, then atomically rename it in the landing directory. Existing hash-named objects are verified, never overwritten through the application. An interrupted temporary write can leave an ignored `.tmp` object.
2. An existing receipt returns unchanged on retry. A reused accepted source/batch ID with different bytes is rejected. Unsupported envelope/schema is retained as a rejected object and does not advance coverage.
3. Validate each row against its exact declared schema. Reject coercions and unknown fields. Invalid rows receive quarantine receipts; valid duplicate revisions receive duplicate receipts. Different meanings for the same source/ID/revision reject the entire delivery and roll back any earlier admitted rows.
4. In one DuckDB transaction, insert new versions and all row receipts, mark affected dates, advance the monotonic declared source coverage, record the delivery and increment the ingestion epoch. A kill before commit leaves no partial admission; a kill after commit is resolved by replaying the original bytes.

Revisions are source sequence numbers, not arrival order or timestamps. Lower revisions can be retained without becoming current. A tombstone never inherits a previous payload. Quarantining a bad higher revision leaves the previous valid revision current; the ledger exposes this limitation. Repair requires a new delivery ID and valid source revision, not editing stored evidence.

## Candidate and publication

`plan` pins all latest versions (including tombstones), source coverage, implementation hash, ingestion epoch, base publication, scope and explicit freshness date. Default scope is dirty dates. A moved correction marks both its old and new date. A reference change conservatively marks every historical fact date. A first build and `--full` include all historical dates.

`build` copies untouched base partitions and recomputes the selected dates using [SQL](../src/marketing_reliability/sql/campaign_daily.sql). Source measures are aggregated at campaign/day before joining the unique campaign reference. Candidate rows and their validation evidence commit together. A restart of a planned run retries the build; an already built run returns its retained result.

Validation independently sums the pinned normalized payloads in Python. It compares every dimension and measure, not only totals or row counts. Missing campaign references are retained separately and block publication even when the SQL and oracle both omit the unresolved records. All four feeds must have declared coverage within 0..1 days of the run date. Future coverage relative to that date is also blocked.

`publish` repeats validation, checks that candidate evidence did not change, and requires the same epoch, base publication and implementation. Pointer change, run status and dirty-date clearance commit together. An older successful retry never reactivates an old run. Data arriving during a staged build makes that plan stale; the operator creates a new one. Blocked runs remain inspectable, with no active-pointer change.

The publication table is a current corrected view of admitted data at a run, not an arbitrary business-time query engine. Previously published tables and input snapshots remain inspectable by run ID. A scoped rebuild cannot publish if copied partitions disagree with the full oracle. This deliberately trades validation cost for a strong small-data correctness proof.

## Evidence and limits

Accepted delivery rows = admitted versions + duplicate rows + quarantined rows. Admitted versions = superseded versions + current tombstones + current live records. Rejected deliveries are accounted separately. The original object and row receipt explain every admitted version; the run input snapshot carries that lineage into each report. The [contract reference](contracts.md) specifies field-level rules.

There are no hard deletes, retention automation, filesystem-admin protections, privacy lifecycle, continuous scheduler, automatic exponential retry, metrics server or production SLA. Source data is read in memory (100,000-row envelope limit); raw byte size is not bounded before parsing. Row-wise inserts favor clarity over throughput. Full snapshots and retained candidates grow storage; production retention and load testing are future work.
