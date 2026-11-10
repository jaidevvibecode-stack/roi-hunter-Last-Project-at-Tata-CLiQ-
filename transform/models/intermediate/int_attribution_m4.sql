-- Attribution Model M4: Purchased-SKU, last paid touch = Meta.
-- Logic: each purchased line item (SKU X) is credited to Meta only if the user's LAST paid touch
--        (any paid channel) before purchase, within the lookback window, was a Meta ad click.
--        Credit goes to (that ad_id, purchased SKU X). DESIGN §5 Model M4. UI label: "Last paid touch".
{{ config(materialized='table', schema='int') }}

with touches as (
    -- every event that carries paid-campaign UTM data counts as a paid touch (any source)
    select distinct_id_hash, utm_source, utm_content as ad_id, event_time as touch_time
    from {{ ref('stg_mixpanel__events') }}
    where utm_source is not null and utm_medium in {{ sql_list(var('paid_utm_mediums')) }}
),

purchases as (
    select distinct_id_hash, order_id, sku as purchased_sku, quantity,
           price * quantity as line_revenue, event_time as purchase_time
    from {{ ref('stg_mixpanel__events') }}
    where event = '{{ var("purchase_event") }}'
      and order_id is not null and sku is not null and price is not null and quantity is not null
),

last_touch as (
    select
        p.order_id, p.purchased_sku, p.quantity, p.line_revenue,
        date(p.purchase_time) as report_date,
        t.utm_source, t.ad_id,
        row_number() over (partition by p.order_id, p.purchased_sku order by t.touch_time desc) as _rank
    from purchases p
    join touches t
      on  t.distinct_id_hash = p.distinct_id_hash
      and t.touch_time < p.purchase_time
      and t.touch_time >= {{ dbt.dateadd('day', -var('default_lookback_days'), 'p.purchase_time') }}
)

select
    report_date,
    ad_id,
    purchased_sku                      as mixpanel_sku,
    'M4'                               as attribution_model,
    {{ var('default_lookback_days') }} as lookback_days,
    count(distinct order_id)           as orders,
    sum(quantity)                      as units,
    cast(sum(line_revenue) as decimal(18,6)) as revenue
from last_touch
where _rank = 1
  and utm_source in {{ sql_list(var('meta_utm_sources')) }}
  and ad_id is not null
group by 1, 2, 3, 4, 5
