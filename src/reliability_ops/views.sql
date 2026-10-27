CREATE TABLE IF NOT EXISTS ops_candidates(name VARCHAR PRIMARY KEY, run_id BIGINT UNIQUE,
  pins VARCHAR, accepted_hashes VARCHAR, gates VARCHAR, start_day VARCHAR, through_day VARCHAR);
CREATE VIEW IF NOT EXISTS ops_opportunity_day AS
SELECT run_id,day,campaign_id,count(*) AS opportunity_count,sum(revenue_cents) AS reported_closed_won_cents
FROM run_inputs WHERE source='crm' AND op='upsert' GROUP BY run_id,day,campaign_id;
CREATE VIEW IF NOT EXISTS ops_publication_history AS
SELECT c.name,r.id,r.base,r.status,r.as_of,c.gates,r.evidence FROM runs r
LEFT JOIN ops_candidates c ON c.run_id=r.id;
CREATE VIEW IF NOT EXISTS ops_contract_outcomes AS
SELECT d.source,r.disposition,count(*) AS rows FROM deliveries d JOIN row_receipts r USING(hash)
GROUP BY d.source,r.disposition;
