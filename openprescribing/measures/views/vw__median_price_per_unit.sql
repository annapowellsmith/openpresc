-- This SQL is checked in to the git repo at measure_sql/vw__median_price_per_unit.sql.
-- Do not make changes directly in BQ!  Instead, change the version in the repo and run
--
--     ./manage.py create_bq_measure_views

WITH prices_per_unit AS (
  SELECT
    month AS date,
    bnf_code,
    IEEE_DIVIDE(net_cost,quantity) AS price_per_unit
  FROM
    {project}.{hscic}.normalised_prescribing
  WHERE quantity > 0  -- See # 1373
)

SELECT
  DISTINCT date,
  bnf_code,
  percentile_cont(price_per_unit, 0.5) OVER (PARTITION BY date, bnf_code) AS median_price_per_unit
FROM
  prices_per_unit
ORDER BY
  bnf_code,
  date
