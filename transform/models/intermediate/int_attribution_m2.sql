-- Attribution Model M2: Halo / session basket.
-- Logic: a Meta click that landed on SKU X gets credit for the WHOLE order (all items) placed by the same
--        user within the lookback window. Credit goes to (ad_id, landing SKU X); one click credited per order
--        (the last click before purchase). DESIGN §5 Model M2. UI label: "Halo".
{{ config(materialized='table', schema='int') }}

with clicks as (
    select distinct_id_hash, utm_content as ad_id, sku as landing_sku, event_time as click_time
    from {{ ref('stg_mixpanel__events') }}
    where utm_source in {{ sql_list(var('meta_utm_sources')) }}
      and utm_content is not null and sku is not null
      and event = '{{ var("product_view_event") }}'
),

order_items as (
    select distinct_id_hash, order_id, sku, quantity, price * quantity as line_revenue, event_time as purchase_time
    from {{ ref('stg_mixpanel__events') }}
    where event = '{{ var("purchase_event") }}'
      and order_id is not null and sku is not null and price is not null and quantity is not null
),

orders as (
    select distinct_id_hash, order_id, min(purchase_time) as purchase_time,
           sum(quantity) as units, sum(line_revenue) as revenue
    from order_items
    group by 1, 2
),

credited as (
    select
        o.order_id, c.ad_id, c.landing_sku, o.units, o.revenue,
        date(o.purchase_time) as report_date,
        row_number() over (partition by o.order_id order by c.click_time desc) as _rank
    from orders o
    join clicks c
      on  c.distinct_id_hash = o.distinct_id_hash
      and c.click_time < o.purchase_time
      and c.click_time >= {{ dbt.dateadd('day', -var('default_lookback_days'), 'o.purchase_time') }}
)

select
    report_date,
    ad_id,
    landing_sku                       as mixpanel_sku,
    'M2'                              as attribution_model,
    {{ var('default_lookback_days') }} as lookback_days,
    count(distinct order_id)          as orders,
    sum(units)                        as units,
    cast(sum(revenue) as decimal(18,6)) as revenue
from credited
where _rank = 1
group by 1, 2, 3, 4, 5
