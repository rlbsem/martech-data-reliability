# Why a seventh repository

**What important hiring question can this new repository answer that none of the six existing repositories already answer convincingly?**

Can Richard operate the source-to-warehouse boundary: turn unreliable recurring commercial data deliveries into a reconciled analytical table, preserve explainable loss and corrections, and recover ingestion and historical rebuilds without exposing a partial publication?

The six local repositories' READMEs and test inventories were inspected before implementation. Temporal audience and migration code/tests were also checked for overlap in late-arrival and crash behavior. Those repositories already make strong use of transactions and replay. Those mechanisms alone would not justify a seventh project. The distinguishing artifact here is a **multi-source analytical mart with executable contracts, input conservation, independently checked SQL aggregation and controlled partition rebuilds**.

| Existing repository | Existing proof | Additional proof here |
|---|---|---|
| martech-estate-impact | Evidence reconstruction, dependency and counterfactual architecture analysis | Actual data deliveries transformed into analytical measures |
| martech-stack-economics | Constrained cost/capacity optimization with independent accounting | Observed feed quality and warehouse data recovery, without an optimization problem |
| enterprise-martech-ai-control-plane | Authoritative customer state and controlled downstream actions | Analytical publication from recurring batch feeds, without authority/consent/action governance |
| enterprise-agent-runtime-evaluation | Model behavior, grounded tools and release evaluation | Deterministic data processing without an agent or model inference |
| martech-migration-assurance | Semantic platform replacement, cutover and rollback | Ongoing source ingestion and report rebuilding, without switching a system of record |
| temporal-customer-audiences | Two-time audience decisions, expiry and destination reconciliation | Multiple source grains, data contracts and campaign/day warehouse aggregation, without membership evaluation |

The new project strengthens Marketing Data Engineer and Analytics Engineer applications most directly. Data Platform and Cloud Integration roles gain evidence of recovery boundaries, source lineage and a realistic discussion of warehouse translation. MarTech/CDP engineers, architects and technically deep RevOps/GTM practitioners gain a concrete basis for discussing whether reported campaign data is usable. It does not establish production cloud operations, live connector expertise or distributed scale.

Narrowing decisions: four small feeds, one analytical mart, one process writer and one independent oracle. No customer identity layer, audience policy, approvals, optimization, LLM, migration router, message broker or decorative orchestration UI. Those would dilute the distinctive proof and repeat existing work.
