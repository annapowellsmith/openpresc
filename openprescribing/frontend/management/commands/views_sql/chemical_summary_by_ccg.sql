SELECT
  month AS processing_date,
  pct AS pct_id,
  SUBSTR(bnf_code, 1, 9) AS chemical_id,
  SUM(items) AS items,
  SUM(actual_cost) AS cost,
  CAST(SUM(quantity) AS INT64) AS quantity
FROM
  hscic.normalised_prescribing_standard
WHERE month > TIMESTAMP(DATE_SUB(DATE "{{this_month}}", INTERVAL 5 YEAR))
GROUP BY
  processing_date,
  pct_id,
  chemical_id
ORDER BY
  chemical_id, pct_id
