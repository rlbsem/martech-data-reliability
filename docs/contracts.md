# Delivery and data contracts

Every input is one UTF-8 JSON object containing exactly `source`, `batch_id`, `schema_version`, `covered_through`, `rows`. Source is one of `campaigns`, `paid_media`, `web`, `crm`. IDs contain 1..80 ASCII letters, digits, underscores or hyphens. Dates are valid calendar dates formatted YYYY-MM-DD. Duplicate JSON keys and nonfinite values reject the entire envelope.

Every row contains `id`, integer `revision` from 1 through 10^12, and `op` (`upsert` or `delete`). Booleans and floating-point numbers are not accepted as integers. Delete rows contain exactly those three fields. Upsert rows additionally require:

| Source | Fields | Rules |
|---|---|---|
| campaigns v1 | name | String with 1..120 nonblank-trimmed characters |
| paid_media v1 | day, campaign_id, cost_cents, impressions, clicks | USD cents by contract; integer quantities 0..10^12; clicks <= impressions |
| paid_media v2 | v1 fields + currency | Explicit currency must be USD; normalized v1/v2 records compare identically |
| web v1 | day, campaign_id, conversions | Conversion flag is integer 0 or 1 |
| crm v1 | day, campaign_id, revenue_cents | Closed-won revenue in USD cents, integer 0..10^12 |

Upserts are complete replacements, not patches. Unknown or missing fields quarantine a row; unknown schema versions reject a delivery. A row date beyond that delivery's declared coverage is quarantined. Timestamps, conversion windows, foreign currencies, arbitrary custom fields and nested customer profiles are outside this contract.

`covered_through` means the synthetic producer asserts that its feed was delivered through that date. Empty valid deliveries may advance it. It is separate from maximum event date: a quiet feed can be fresh. A feed with quarantined records can also be fresh but incomplete. The demonstration intentionally permits this qualified publication; it is not a financial close control. A failed schema delivery never proves coverage.

An identical revision may repeat in another delivery. A conflicting revision rejects its whole delivery to avoid arrival-order authority. For quarantined data, repair the producer and deliver a new batch ID. Quarantine records remain visible permanently; there is no API to erase or relabel them as successful.

Input examples live in [fixtures](../fixtures/01-campaigns.json). The [fixture generator](../scripts/make_fixtures.py) deterministically authors the ten synthetic files and does not execute the pipeline. The repository verification executes those stored files through the real admission path.
