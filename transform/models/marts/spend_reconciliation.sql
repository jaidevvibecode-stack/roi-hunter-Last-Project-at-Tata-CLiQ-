-- transform/models/marts/spend_reconciliation.sql
-- Spend reconciliation: ad-level catalog spend vs Σ product-level spend.
-- Shows unallocated_spend per day (DESIGN §4, §12).

{{
  config(
    materialized='table',
    schema='mart'
  )
}}

with ad_level as (

    select
        report_date,
        sum(spend)      as ad_level_catalog_spend

    from {{ ref('stg_meta__ad_insights') }}
    -- Filter to catalog ads only (ads with product_set_id in ad set snapshot)
    -- Simplified: include all ad spend until catalog ad detection is added
    group by 1

),

product_level as (

    select
        report_date,
        sum(spend)      as product_level_spend

    from {{ ref('stg_meta__ad_product_insights') }}
    group by 1

)

select
    a.report_date,
    a.ad_level_catalog_spend,
    coalesce(p.product_level_spend, 0)                                          as product_level_spend,
    a.ad_level_catalog_spend - coalesce(p.product_level_spend, 0)               as unallocated_spend,
    case when a.ad_level_catalog_spend > 0
         then (a.ad_level_catalog_spend - coalesce(p.product_level_spend, 0))
              / a.ad_level_catalog_spend * 100
         else null end                                                           as unallocated_pct

from ad_level a
left join product_level p on a.report_date = p.report_date
order by a.report_date desc
