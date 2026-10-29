# Operational delivery acceptance

This extension runs the existing data application through isolated delivery and recovery checks. It preserves the original contracts, financial grain, SQL, controller and historical evidence. No external marketing vendor, cloud service, customer data or public deployment is involved.

## Executed records

- [Current full regression, deterministic demos and existing browser evidence](../operations/run03/verification.json): 68 original tests and 48 operating/contract tests; eight original process-death experiments; 30 HTTP scenario assertions; 73 browser assertions and ten automated accessibility states. The [independent source-row comparisons](../operations/run03/acceptance.json) remain inspectable.
- [Operational application acceptance](run01/verification.json): actual loopback service requests, mutation denials, source outage, console restart, raw-input corruption, private backup/restore and a held restore after source coverage changes. The test suite separately exercises a real advanced source delivery/receipt against an older backed-up journal.
- [Structured request observations](run01/request-telemetry.json) contain allowlisted route/status/timing fields and server-generated request IDs. Headers, query values, payloads, credentials and remote addresses are excluded. Same-port restart logs are appended and each log is read once; IDs must remain unique.
- [Artifact inventory](run01/artifact-integrity.json), [preserved historical files](preserved-files.json) and [current public package manifest](package-manifest.json) are independently checked by `scripts/check_delivery.py`. Source records bind the actual execution checkpoint plus every executed code/configuration file's SHA-256. Later documentation/evidence commits do not imply another model, vendor or cloud execution.
- [Runtime advisory audit](runtime-audit.json): the executed pip-audit 2.9.0 check reported no known advisory for pinned DuckDB 1.3.2 at the time of the check. This is an application dependency audit, not an operating-system scan or proof of vulnerability absence.
- [Private backup inventory](run01/publication-backup-manifest.json) records actual captured file hashes without distributing database files or credentials. [Independent local teardown](run01/independent-teardown.json) observed zero listeners across four owned endpoints and zero exact-workspace service processes. A separate TCP-refusal probe timed out and was not used as absence proof.

The financial outputs remain **USD $410 reported spend, six observed conversions and USD $1,150 reported closed-won value**. Independent raw-source arithmetic agrees with SQL. CRM value is neither cash nor recognized revenue; no commercial outcome is claimed.

## Genuine browser captures

[Desktop readiness](run01/operations-ready-1440.png) · [Mobile readiness](run01/operations-ready-390.png) · [320px readiness](run01/operations-ready-320.png) · [Desktop outage](run01/operations-source-outage-1440.png) · [Mobile outage](run01/operations-source-outage-390.png) · [320px outage](run01/operations-source-outage-320.png).

All six images come directly from the running application, at their named viewport widths. The outage is induced in an actual independently persisted source service. The browser still displays the previous publication, while the operating check states that it is not ready. Automated WCAG A/AA checks retain incomplete observations and recheck each affected node in view; these are not independent human usability acceptance.

## Failed checks and corrections

1. [Initial Windows backup tests](failed-backup-01.json) recorded three failures out of twelve tests. SQLite connection context managers left live handles, preventing final directory rename with WinError 5. Explicit connection closure corrected the failure. Raw test logs remain private because assertion diagnostics can include runtime configuration.
2. [First operational browser check](failed-accessibility-01.json) stopped at an actual `scrollable-region-focusable` violation. Structured output is now keyboard-focusable and has an explicit labeled region role. Final browser verification includes visibility follow-ups, not an automatic waiver of incomplete audits.
3. The first restricted Windows invocation could not create pytest's default temporary directory, and restricted child services did not become reachable. Fresh workspace-local test directories and authorized local process execution resolved the environment boundary; these observations are not application failures or passes.

Historical failures under `docs/evidence/operations` and all 51 previously committed evidence/image files remain unchanged. The newly recorded regression run lives in `run03`; it does not replace the preserved `run01` or `run02` records.

## Container and hosted boundaries

**Actual Linux deployment passed:** [sanitized execution record](container-run01/verification.json) · [initial readiness](container-run01/initial-readiness.json) · [source outage](container-run01/source-outage.json) · [recovered readiness](container-run01/recovered-readiness.json) · [independent teardown](container-run01/teardown.json).

[GitHub run 40800672690](https://github.com/rlbsem/martech-data-reliability/actions/runs/40800672690) executed head `2f1728e78972f77e0f097cda6659471b0eb09784`. Independent inspection of its downloaded artifact verified six containers against their actual image/configuration, resource bounds, non-root identities, private source ports and read-only console mounts. Backup captured 25 state files; isolated restore verified unchanged totals, made zero source writes and did not resume a controller. Stopping the website source produced 503 readiness; restart recovered the same publication and inventory. Teardown found zero project containers, volumes and networks.

The record preserves hashes of all ten extracted upstream artifact files, the GitHub-reported archive digest and exact job/run identities. The archive digest is attributed to GitHub, not misrepresented as a locally recomputed ZIP hash. Raw Docker inspection/log files remain in the CI artifact; the committed subset excludes ephemeral addresses and volume identifiers. To repeat the independent review, download the `container-delivery` artifact from that run, compare the recorded file hashes and inspect `containers.json`, `image.json` and the four committed readiness/teardown records. Later evidence-only commits preserve the executed application/configuration bytes; exact final-head checks are available on the PR.

The `Operational delivery` workflow resolves the actual Compose configuration, builds the pinned image, starts isolated non-root services, verifies read-only mounts, executes backup/restore, stops a source, checks 503 readiness with live inspection, restarts services and independently checks project container/volume/network teardown. Its downloadable `container-delivery` artifact records image/configuration, readiness observations, bounded logs, dependency audit and residual checks. Exact-head CI status must be inspected on the pull request; the local Windows process record is not container execution.

Docker was unavailable in the local Windows environment. Container execution therefore belongs to the separate Linux GitHub Actions record. No authenticated Internet-facing dynamic deployment is configured or authorized; an approved host and ingress/authentication/TLS design remain necessary. GitHub Pages is not substituted for dynamic application acceptance.

This verifies finite synthetic publication recovery against surviving independent sources. It does not establish source-system disaster recovery, image-version migration/rollback compatibility, native vendor integration, production availability or business uplift. No human tester or independent security audit is claimed.

[Architecture](../../operational-delivery.md) · [Operating procedures and reproduction](../../deployment-runbook.md).
