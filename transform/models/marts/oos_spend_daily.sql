-- Spend on products that are OUT OF STOCK (wasted spend).
-- NOTE: availability is taken from the LATEST catalog snapshot. Exact day-by-day availability needs
-- availability history (Phase 2, P2.7). Treat as "currently out of stock but still received spend".
{{ config(materialized='table', schema='mart') }}

select
    m.report_date,
    m.product_key,
    d.retailer_id,
    d.product_name,
    sum(m.spend) as spend_on_oos
from {{ ref('product_performance_daily') }} m
join {{ ref('dim_product') }} d on d.product_key = m.product_key
where d.availability = 'out of stock'
  and m.attribution_model = 'M1'
  and m.lookback_days = {{ var('default_lookback_days') }}
  and m.spend > 0
group by 1, 2, 3, 4
