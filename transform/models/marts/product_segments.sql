-- Product segmentation (ROI-Hunter-style quadrants) over the 30 days ending at the latest loaded date, model M1 / default lookback.
-- Thresholds come from dbt vars (mirror of config/segments.yml, which drives the API).
-- Stars: high spend & ROAS >= target | Bleeders: high spend & low ROAS
-- Hidden Gems: low spend & ROAS >= target | Zombies: low spend & low ROAS
{{ config(materialized='table', schema='mart') }}

with agg as (
    select
        product_key,
        sum(spend)   as spend,
        sum(revenue) as revenue,
        sum(orders)  as orders
    from {{ ref('product_performance_daily') }}
    where attribution_model = 'M1'
      and lookback_days = {{ var('default_lookback_days') }}
      and report_date > {{ dbt.dateadd('day', -30, '(select max(report_date) from ' ~ ref('product_performance_daily') ~ ')') }}
    group by 1
),

cut as (
    select percentile_cont({{ var('high_spend_percentile') }}) within group (order by spend) as spend_cut
    from agg
    where spend >= {{ var('min_spend_for_classification') }}
)

select
    a.product_key,
    a.spend,
    a.revenue,
    a.orders,
    case when a.spend > 0 then a.revenue / a.spend end as roas,
    case
        when a.spend < {{ var('min_spend_for_classification') }} then 'Insufficient data'
        when a.spend >= c.spend_cut and a.revenue / a.spend >= {{ var('target_roas') }} then 'Stars'
        when a.spend >= c.spend_cut then 'Bleeders'
        when a.revenue / a.spend >= {{ var('target_roas') }} then 'Hidden Gems'
        else 'Zombies'
    end as segment,
    (select max(report_date) from {{ ref('product_performance_daily') }}) as as_of_date
from agg a cross join cut c
