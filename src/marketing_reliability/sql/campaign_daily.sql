-- Each source is reduced to day/campaign BEFORE combining facts of different grains.
-- No attribution model is inferred: campaign_id is a supplied source relationship.
WITH measures AS (
  SELECT day, campaign_id,
    sum(coalesce(cost_cents, 0)) AS cost_cents,
    sum(coalesce(impressions, 0)) AS impressions,
    sum(coalesce(clicks, 0)) AS clicks,
    sum(coalesce(conversions, 0)) AS conversions,
    sum(coalesce(revenue_cents, 0)) AS revenue_cents
  FROM run_inputs
  WHERE run_id = ? AND source <> 'campaigns' AND op = 'upsert'
    AND day IN (SELECT unnest(?::VARCHAR[]))
  GROUP BY day, campaign_id
), campaigns AS (
  SELECT id, name FROM run_inputs WHERE run_id = ? AND source = 'campaigns' AND op = 'upsert'
)
SELECT m.day, m.campaign_id, c.name AS campaign_name,
  m.cost_cents, m.impressions, m.clicks, m.conversions, m.revenue_cents
FROM measures m JOIN campaigns c ON m.campaign_id = c.id
ORDER BY m.day, m.campaign_id;
