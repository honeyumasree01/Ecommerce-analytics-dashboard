-- Event sanity checks (expected for this project)
-- Validate: no missing keys, no unexpected event_type values, timestamps parse.
--
-- Assumed tables:
--   events(event_id, user_id, product_id, event_type, event_timestamp)

-- 1) Missing values in required columns
SELECT
  SUM(CASE WHEN user_id IS NULL OR TRIM(user_id) = '' THEN 1 ELSE 0 END) AS missing_user_id,
  SUM(CASE WHEN event_type IS NULL OR TRIM(event_type) = '' THEN 1 ELSE 0 END) AS missing_event_type,
  SUM(CASE WHEN event_timestamp IS NULL THEN 1 ELSE 0 END) AS missing_event_timestamp
FROM events;

-- 2) Unexpected event types
SELECT event_type, COUNT(*) AS cnt
FROM events
WHERE event_type NOT IN ('view', 'cart', 'purchase', 'wishlist')
GROUP BY event_type;

-- 3) Timestamp format parse sanity (DB-specific; DuckDB/PG recommended)
-- Example idea: try_cast / cast to timestamp and ensure no failures.

