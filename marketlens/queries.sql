-- Aggregate each source to the same grain BEFORE joining to prevent spend fan-out.
-- Parameters are inclusive start, inclusive end, optional channel (empty = all).
WITH sales_daily AS (
  SELECT date,channel,campaign,COUNT(*) AS orders,
         SUM(gross_cents) AS gross_cents,SUM(refund_cents) AS refund_cents,
         SUM(gross_cents-refund_cents) AS revenue_cents
  FROM sales WHERE date BETWEEN :start AND :end AND (:channel='' OR channel=:channel)
  GROUP BY date,channel,campaign
), ads_daily AS (
  SELECT date,channel,campaign,SUM(spend_cents) AS spend_cents,
         SUM(impressions) AS impressions,SUM(clicks) AS clicks,SUM(conversions) AS conversions
  FROM ads WHERE date BETWEEN :start AND :end AND (:channel='' OR channel=:channel)
  GROUP BY date,channel,campaign
), grain AS (
  SELECT date,channel,campaign FROM sales_daily
  UNION SELECT date,channel,campaign FROM ads_daily
)
SELECT g.date,g.channel,g.campaign,
       COALESCE(s.orders,0) AS orders,COALESCE(s.gross_cents,0) AS gross_cents,
       COALESCE(s.refund_cents,0) AS refund_cents,COALESCE(s.revenue_cents,0) AS revenue_cents,
       COALESCE(a.spend_cents,0) AS spend_cents,COALESCE(a.impressions,0) AS impressions,
       COALESCE(a.clicks,0) AS clicks,COALESCE(a.conversions,0) AS conversions,
       CASE WHEN a.date IS NULL AND g.channel IN ('paid search','paid social') THEN 1 ELSE 0 END
         AS missing_ad_days,
       CASE WHEN s.date IS NULL THEN 1 ELSE 0 END AS ad_only_days
FROM grain g LEFT JOIN sales_daily s USING(date,channel,campaign)
LEFT JOIN ads_daily a USING(date,channel,campaign)
ORDER BY g.date,g.channel,g.campaign;
