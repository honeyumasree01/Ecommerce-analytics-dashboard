-- Conversion rate by segment (cart -> purchase, strict)
--
-- Segments:
--  1) gender (from users table)
--  2) primary cart category (mode category among a user's cart events)
--
-- Strict metric:
--   cart_to_purchase_conversion = users with >=1 cart AND >=1 purchase
--
-- Expected tables:
--   users(user_id, gender, ...)
--   events(user_id, product_id, event_type, event_timestamp, ...)
--   products(product_id, category, ...)

WITH
cart_users AS (
  SELECT DISTINCT user_id
  FROM events
  WHERE event_type = 'cart'
),
purchase_users AS (
  SELECT DISTINCT user_id
  FROM events
  WHERE event_type = 'purchase'
),
gender_segment AS (
  SELECT
    u.gender AS segment_value,
    COUNT(DISTINCT c.user_id) AS cart_users,
    COUNT(DISTINCT CASE WHEN p.user_id IS NOT NULL THEN c.user_id END) AS purchased_users
  FROM cart_users c
  JOIN users u
    ON c.user_id = u.user_id
  LEFT JOIN purchase_users p
    ON c.user_id = p.user_id
  GROUP BY u.gender
),
cart_events AS (
  SELECT
    e.user_id,
    pr.category
  FROM events e
  JOIN products pr
    ON e.product_id = pr.product_id
  WHERE e.event_type = 'cart'
),
primary_cart_category AS (
  -- Pick the most frequent category across cart events per user
  SELECT
    user_id,
    category AS segment_value
  FROM (
    SELECT
      user_id,
      category,
      ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY cnt DESC) AS rn
    FROM (
      SELECT user_id, category, COUNT(*) AS cnt
      FROM cart_events
      GROUP BY user_id, category
    )
  ) t
  WHERE rn = 1
),
category_segment AS (
  SELECT
    pcc.segment_value,
    COUNT(DISTINCT c.user_id) AS cart_users,
    COUNT(DISTINCT CASE WHEN pu.user_id IS NOT NULL THEN c.user_id END) AS purchased_users
  FROM cart_users c
  JOIN primary_cart_category pcc
    ON c.user_id = pcc.user_id
  LEFT JOIN purchase_users pu
    ON c.user_id = pu.user_id
  GROUP BY pcc.segment_value
)
SELECT
  'gender' AS segment_type,
  segment_value,
  cart_users,
  purchased_users,
  1.0 * purchased_users / NULLIF(cart_users, 0) AS cart_to_purchase_conversion
FROM gender_segment

UNION ALL

SELECT
  'primary_cart_category' AS segment_type,
  segment_value,
  cart_users,
  purchased_users,
  1.0 * purchased_users / NULLIF(cart_users, 0) AS cart_to_purchase_conversion
FROM category_segment

ORDER BY segment_type, cart_users DESC;

