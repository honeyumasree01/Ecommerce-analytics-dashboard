-- Funnel drop-off: view -> cart -> purchase (user-level)
--
-- Strict conversion logic used in this project:
--   Cart -> Purchase (strict) = users who have at least one cart AND at least one purchase.
--
-- Expected tables:
--   events(user_id, event_type, event_timestamp, ... )

WITH
view_users AS (
  SELECT DISTINCT user_id
  FROM events
  WHERE event_type = 'view'
),
cart_users AS (
  SELECT DISTINCT user_id
  FROM events
  WHERE event_type = 'cart'
),
purchase_users AS (
  SELECT DISTINCT user_id
  FROM events
  WHERE event_type = 'purchase'
)
SELECT
  (SELECT COUNT(*) FROM view_users) AS view_users,
  (SELECT COUNT(*) FROM cart_users) AS cart_users,
  (SELECT COUNT(*) FROM purchase_users) AS purchase_users,

  -- Rates
  (1.0 * (SELECT COUNT(*) FROM cart_users JOIN view_users USING (user_id)) / NULLIF((SELECT COUNT(*) FROM view_users), 0)) AS view_to_cart_conversion,
  (1.0 * (SELECT COUNT(*) FROM purchase_users JOIN cart_users USING (user_id)) / NULLIF((SELECT COUNT(*) FROM cart_users), 0)) AS cart_to_purchase_conversion_strict,
  (1.0 * (SELECT COUNT(*) FROM purchase_users JOIN view_users USING (user_id)) / NULLIF((SELECT COUNT(*) FROM view_users), 0)) AS view_to_purchase_conversion_overall;

