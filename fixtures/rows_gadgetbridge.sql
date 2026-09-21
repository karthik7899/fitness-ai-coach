-- The canonical rows a Gadgetbridge import must produce.
SELECT date
       || ',' || metric
       || ',' || CAST(value AS TEXT)
       || ',' || unit
       AS line
FROM daily_metrics
WHERE source = 'gadgetbridge'
ORDER BY date, metric
