# Run and recover

Install the pinned dependencies and package using the [README instructions](../README.md#reproduce). Run commands from the repository root. Use a fresh state directory for each independent experiment; no command resets an existing database.

```text
python scripts/demo.py --state work/my-demo
marketing-pipeline --state work/my-demo report
marketing-pipeline --state work/my-demo lineage 6
```

The demo prints the exact database location and writes the linked evidence. It asserts results, so a changed fixture or model that changes those results fails visibly. Verification creates fresh state automatically.

## Individual transitions

```text
marketing-pipeline --state work/manual ingest fixtures/01-campaigns.json
marketing-pipeline --state work/manual ingest fixtures/02-paid.json
marketing-pipeline --state work/manual ingest fixtures/03-web.json
marketing-pipeline --state work/manual ingest fixtures/04-crm.json
marketing-pipeline --state work/manual plan --as-of 2026-09-04
marketing-pipeline --state work/manual build 1
marketing-pipeline --state work/manual publish 1
marketing-pipeline --state work/manual report
```

`plan` returns a run ID. Use that returned ID for subsequent commands; `1` above is only for a new directory. `plan --date 2026-09-01 --as-of 2026-09-04` explicitly rebuilds one date. Multiple `--date` options are allowed. `--full` rebuilds all historical dates and cannot be combined with dates. Only `publish` changes the report. The freshness date is explicit test/business context, not implicitly today's wall clock.

Exit 0 means the requested operation completed; a built candidate with blockers or rejected delivery exits 2 with JSON evidence. Argument/contract/gate failures also exit 2. Unexpected environment/database failures are nonzero. Deliberate crash injection exits 86. A valid delivery with quarantined rows remains an accepted operation; inspect `report` before treating the resulting measures as complete.

## Recovery decisions

| Observation | Action |
|---|---|
| Process died after landing or during admission | Resubmit the exact original file. Without a receipt, the batch is processed; with a receipt, it is replayed |
| Process died during build | Run `build` for the same pinned run ID; transaction rollback left it planned |
| Process died after build or publication commit | Retry the same command; persisted state determines the outcome |
| Source epoch or base publication changed | Create a new plan; do not force-publish the old one |
| Stale/missing coverage | Obtain a valid producer delivery or explicit empty coverage delivery; use a new plan |
| Unknown campaign ID | Repair reference data or correct the source relationship; use a new plan |
| Quarantined row | Repair upstream and deliver under a new batch ID; preserve the original quarantine |
| Incompatible schema | Implement and test an explicit contract migration before new delivery admission |
| Hash mismatch or missing landing object | Stop and restore the exact original object from a trusted copy; do not accept a renamed replacement |
| Writer file-lock error | Close the other writer and retry; this local implementation does not run multiple writer processes concurrently |

The state directory contains `warehouse.duckdb` (and sometimes its WAL), plus `landing/<SHA-256>.json`. Preserve both warehouse and landing files when backing up a closed state directory. Independent copies made while writing are not a supported backup protocol. Restore/backup disaster recovery has not been exercised. Unreceipted `.json` objects are reported; abandoned `.tmp` files are ignored. Automatic garbage collection is intentionally absent.

## Verification and delivery

```text
python scripts/verify.py
python scripts/package.py --output ../Richard_Butts_MarTech_Data_Reliability_Finished.zip
```

Packaging checks source and generated-evidence hashes against the last verification, regenerates its self-excluding manifest/tree, checks ZIP CRC and compares every archived file with the repository. Runtime databases, virtual environments, caches and build outputs are excluded. The adjacent ZIP SHA-256 covers the archive, while the manifest covers every delivered file except itself.
