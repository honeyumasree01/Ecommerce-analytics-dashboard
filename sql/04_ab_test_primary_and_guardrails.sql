-- A/B test (conceptual template): Control (A) vs Variant (B)
--
-- This project uses deterministic/simulated assignment when experiment data is absent:
--   variant = md5(user_id) % 2
--
-- Primary metric:
--   cart_to_purchase_conversion = purchase within 7 days of user's first cart event
--
-- Guardrails:
--   week-1 retention (any event in [first_event+7d, first_event+14d))
--   time-to-activation (time from first event to purchase within 24h)

WITH
first_event AS (
  SELECT
    user_id,
    MIN(event_timestamp) AS first_event_ts
  FROM events
  GROUP BY user_id
),
first_cart AS (
  SELECT
    user_id,
    MIN(event_timestamp) AS first_cart_ts
  FROM events
  WHERE event_type = 'cart'
  GROUP BY user_id
),
cart_population AS (
  SELECT user_id, first_cart_ts
  FROM first_cart
),
variant_assignment AS (
  SELECT
    user_id,
    CASE
      WHEN (ABS(hash(user_id)) % 2) = 0 THEN 'A_control'
      ELSE 'B_treatment'
    END AS variant,
    'checkout_optimization' AS experiment_name
  FROM cart_population
),
primary_success AS (
  SELECT
    cp.user_id,
    MAX(CASE
      WHEN e.event_type = 'purchase'
       AND e.event_timestamp >= cp.first_cart_ts
       AND e.event_timestamp <  cp.first_cart_ts + INTERVAL '7 days'
      THEN 1 ELSE 0 END) AS purchase_within_7d
  FROM cart_population cp
  LEFT JOIN events e
    ON cp.user_id = e.user_id
  GROUP BY cp.user_id
),
week1_active AS (
  SELECT
    fe.user_id,
    MAX(CASE
      WHEN e.event_timestamp >= fe.first_event_ts + INTERVAL '7 days'
       AND e.event_timestamp <  fe.first_event_ts + INTERVAL '14 days'
      THEN 1 ELSE 0 END) AS week1_active
  FROM first_event fe
  LEFT JOIN events e
    ON fe.user_id = e.user_id
  GROUP BY fe.user_id
),
time_to_activation AS (
  SELECT
    fe.user_id,
    MIN(CASE
      WHEN e.event_type = 'purchase'
       AND e.event_timestamp >= fe.first_event_ts
       AND e.event_timestamp <  fe.first_event_ts + INTERVAL '24 hours'
      THEN EXTRACT(EPOCH FROM (e.event_timestamp - fe.first_event_ts)) / 3600.0
    END) AS time_to_activation_hours
  FROM first_event fe
  LEFT JOIN events e
    ON fe.user_id = e.user_id
  GROUP BY fe.user_id
)
SELECT
  va.variant,
  COUNT(DISTINCT va.user_id) AS total_users,
  SUM(ps.purchase_within_7d) AS success_users,
  1.0 * SUM(ps.purchase_within_7d) / COUNT(DISTINCT va.user_id) AS conversion_rate,
  AVG(1.0 * wa.week1_active) AS week1_retention_rate,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tta.time_to_activation_hours) AS median_time_to_activation_hours
FROM variant_assignment va
LEFT JOIN primary_success ps
  ON va.user_id = ps.user_id
LEFT JOIN week1_active wa
  ON va.user_id = wa.user_id
LEFT JOIN time_to_activation tta
  ON va.user_id = tta.user_id
GROUP BY va.variant
ORDER BY va.variant;

