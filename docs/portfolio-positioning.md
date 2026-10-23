# Source-to-warehouse reliability: architectural scope

This project focuses on a recurring operational problem: commercial data arrives at different grains, with duplicate deliveries, corrected records, missing references, and variable source freshness. A report is published only after contracts, conservation checks, independent aggregation, and recovery tests establish what was admitted and what remains unresolved.

The key implementation is a **multi-source analytical mart with executable data contracts, source-to-output lineage, controlled partition rebuilding, and an independent validation path**. It is distinct from modeling customer activation, application migration, or AI decisioning.

## Relationship to adjacent engineering systems

| Related system | Its primary responsibility | Distinct responsibility here |
|---|---|---|
| [MarTech Estate Impact](https://github.com/rlbsem/martech-estate-impact) | Reconstruct application dependencies and evaluate architecture changes | Reconcile actual ingested records into an analytical publication |
| [MarTech Stack Economics](https://github.com/rlbsem/martech-stack-economics) | Model feasible cost, capacity, and routing decisions | Enforce observed feed quality and correct historical data processing |
| [Enterprise MarTech / AI Control Plane](https://github.com/rlbsem/enterprise-martech-ai-control-plane) | Govern authoritative customer state and downstream actions | Publish reliable warehouse measures from recurring source deliveries |
| [Enterprise Agent Runtime & Evaluation](https://github.com/rlbsem/enterprise-agent-runtime-evaluation) | Evaluate model behavior and release governance | Deterministic analytical data processing |
| [MarTech Migration Assurance](https://github.com/rlbsem/martech-migration-assurance) | Preserve meaning across platform replacement and rollback | Preserve analytical correctness during ongoing ingestion and backfills |
| [Temporal Customer Audiences](https://github.com/rlbsem/temporal-customer-audiences) | Resolve effective-time and knowledge-time eligibility | Resolve different source grains, contracts, and campaign/day metrics |

## Deliberate implementation scope

The demonstration uses four small source feeds, one analytical mart, a single writer, and an independently calculated result. Identity resolution, audience activation, platform cutover, agent inference, and vendor orchestration are separate concerns. The bounded scope makes ingestion, correction, and publication failure modes directly testable.

[Architecture](architecture.md) · [Executed evidence](evidence/report.md) · [Validation and tradeoffs](validation.md)
