-- ID alignment health (DESIGN §5 P4, plan P1.8): how much spend / revenue joins across systems.
-- spend_match_rate  = Meta product-level spend whose meta_item_id maps to a catalog product.
-- revenue_match_rate = Mixpanel purchase revenue whose SKU maps to a catalog product.
{{ config(materialized='table', schema='mart') }}

with spend as (
    select
        p.report_date,
        sum(p.spend)                                                   as total_spend,
        sum(case when k.meta_item_id is not null then p.spend else 0 end) as matched_spend
    from {{ ref('stg_meta__ad_product_insights') }} p
    left join {{ ref('int_product_key_map') }} k on p.meta_item_id = k.meta_item_id
    group by 1
),

revenue as (
    select
        date(e.event_time)                                             as report_date,
        sum(e.price * e.quantity)                                      as total_revenue,
        sum(case when k.mixpanel_sku is not null then e.price * e.quantity else 0 end) as matched_revenue
    from {{ ref('stg_mixpanel__events') }} e
    left join (select distinct mixpanel_sku from {{ ref('int_product_key_map') }}) k on e.sku = k.mixpanel_sku
    where e.event = '{{ var("purchase_event") }}' and e.order_id is not null
      and e.sku is not null and e.price is not null and e.quantity is not null
    group by 1
)

select
    coalesce(s.report_date, r.report_date)                             as report_date,
    s.total_spend,
    s.matched_spend,
    case when s.total_spend > 0 then s.matched_spend / s.total_spend end       as spend_match_rate,
    r.total_revenue,
    r.matched_revenue,
    case when r.total_revenue > 0 then r.matched_revenue / r.total_revenue end as revenue_match_rate
from spend s
full outer join revenue r on s.report_date = r.report_date
