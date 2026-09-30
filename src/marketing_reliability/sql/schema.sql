CREATE TABLE IF NOT EXISTS meta (epoch BIGINT NOT NULL, active_run BIGINT);
INSERT INTO meta SELECT 0, NULL WHERE NOT EXISTS (SELECT 1 FROM meta);
CREATE TABLE IF NOT EXISTS deliveries (
  hash VARCHAR PRIMARY KEY, source VARCHAR, batch_id VARCHAR,
  status VARCHAR NOT NULL, reason VARCHAR, coverage VARCHAR, row_count BIGINT NOT NULL,
  UNIQUE(source, batch_id)
);
CREATE TABLE IF NOT EXISTS row_receipts (
  hash VARCHAR, line BIGINT, disposition VARCHAR, reason VARCHAR, raw VARCHAR,
  PRIMARY KEY(hash, line)
);
CREATE TABLE IF NOT EXISTS versions (
  source VARCHAR, id VARCHAR, revision BIGINT, op VARCHAR, day VARCHAR, campaign_id VARCHAR,
  cost_cents BIGINT, impressions BIGINT, clicks BIGINT, conversions BIGINT, revenue_cents BIGINT,
  name VARCHAR, payload VARCHAR, hash VARCHAR, line BIGINT,
  PRIMARY KEY(source, id, revision)
);
CREATE VIEW IF NOT EXISTS latest AS
SELECT * EXCLUDE (rank) FROM (
  SELECT *, row_number() OVER (PARTITION BY source, id ORDER BY revision DESC) AS rank
  FROM versions
) WHERE rank = 1;
CREATE TABLE IF NOT EXISTS coverage (source VARCHAR PRIMARY KEY, through_day VARCHAR);
CREATE TABLE IF NOT EXISTS dirty (day VARCHAR PRIMARY KEY);
CREATE TABLE IF NOT EXISTS runs (
  id BIGINT PRIMARY KEY, epoch BIGINT, base BIGINT, as_of VARCHAR, implementation VARCHAR,
  scope VARCHAR, status VARCHAR, evidence VARCHAR
);
CREATE TABLE IF NOT EXISTS run_inputs AS SELECT CAST(NULL AS BIGINT) AS run_id, * FROM latest WHERE false;
CREATE TABLE IF NOT EXISTS run_coverage (run_id BIGINT, source VARCHAR, through_day VARCHAR);
CREATE TABLE IF NOT EXISTS mart (
  run_id BIGINT, day VARCHAR, campaign_id VARCHAR, campaign_name VARCHAR,
  cost_cents HUGEINT, impressions HUGEINT, clicks HUGEINT, conversions HUGEINT, revenue_cents HUGEINT,
  PRIMARY KEY(run_id, day, campaign_id)
);
CREATE VIEW IF NOT EXISTS published_campaign_daily AS
SELECT m.* EXCLUDE (run_id) FROM mart m JOIN meta ON m.run_id = meta.active_run;
