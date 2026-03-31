-- Cohort retention (week-1)
--
-- Locked definitions:
--   Cohort = user's first event date
--   Week-1 active = user has any event in [first_event_ts + 7d, first_event_ts + 14d)
--
-- Expected table:
--   events(user_id, event_type, event_timestamp)

WITH first_event AS (
  SELECT
    user_id,
    MIN(event_timestamp) AS first_event_ts,
    CAST(MIN(event_timestamp) AS DATE) AS cohort_date
  FROM events
  GROUP BY user_id
),
week1_active AS (
  SELECT
    e.user_id
  FROM events e
  JOIN first_event f
    ON e.user_id = f.user_id
  WHERE
    e.event_timestamp >= f.first_event_ts + INTERVAL '7 days'
    AND e.event_timestamp <  f.first_event_ts + INTERVAL '14 days'
  GROUP BY e.user_id
)
SELECT
  CAST(first_event.cohort_date AS VARCHAR) AS cohort_month,
  COUNT(*) AS cohort_users,
  SUM(CASE WHEN week1_active.user_id IS NOT NULL THEN 1 ELSE 0 END) AS week1_users,
  1.0 * SUM(CASE WHEN week1_active.user_id IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS week1_retention_rate
FROM first_event
LEFT JOIN week1_active
  ON first_event.user_id = week1_active.user_id
GROUP BY cohort_month
ORDER BY cohort_month;

