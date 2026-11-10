-- transform/models/intermediate/int_attribution_m1.sql
-- Attribution Model M1: Same-SKU click attribution (default).
-- Logic: Purchase of SKU X within N days after a Meta ad click session
--        whose landing product = SKU X. Credit to that ad_id + SKU X; if several clicks qualify, the LAST click
--        before the purchase wins (one credit per order line).
-- ASSUMPTION to verify in spike P0.6: UTM parameters AND the SKU are present on the SAME product-view event.
--        If the site only carries UTMs on the landing event, M1 will be sparse (M2/M4 are less sensitive).
-- DESIGN §5 Model M1.

{{
  config(
    materialized='table',
    schema='int'
  )
}}

/*
  Prerequisites (verified in Phase 0):
  P1 — utm_content = <ad.id> on landing URL
  P2 — landing event carries SKU
  P3 — purchase event carries SKU, quantity, price, order_id

  If P1 is missing: only M3/M4 are possible. This model will return empty.
  The calling mart will fall back to available models per 03_CONTEXT.md.
*/

with click_sessions as (

    -- Sessions where a user clicked a Meta ad that landed on a specific SKU
    select
        distinct_id_hash,
        utm_content                             as ad_id,  -- <ad.id>
        sku                                     as landing_sku,
        event_time                              as click_time

    from {{ ref('stg_mixpanel__events') }}
    where utm_source in {{ sql_list(var('meta_utm_sources')) }}
      and utm_content is not null               -- ad_id present
      and sku is not null                       -- landing SKU present (P2)
      and event = '{{ var("product_view_event") }}'

),

purchases as (

    -- Purchase line items with SKU and order_id
    select
        distinct_id_hash,
        order_id,
        sku                                     as purchased_sku,
        price,
        quantity,
        price * quantity                        as line_revenue,
        event_time                              as purchase_time

    from {{ ref('stg_mixpanel__events') }}
    where event = '{{ var("purchase_event") }}'
      and sku is not null
      and order_id is not null
      and price is not null
      and quantity is not null

),

-- M1: Join click to same-SKU purchase within lookback window
-- Lookback window = var('default_lookback_days') = 7
m1_attributed as (

    select
        p.order_id,
        p.purchased_sku,
        c.ad_id,
        c.click_time,
        p.purchase_time,
        p.line_revenue,
        p.quantity,
        date(p.purchase_time)                   as report_date,
        -- Dedup: one order line credited once (the last matching click)
        row_number() over (
            partition by p.order_id, p.purchased_sku
            order by c.click_time desc          -- last click before purchase
        ) as _credit_rank

    from purchases p
    join click_sessions c
      on  c.distinct_id_hash = p.distinct_id_hash
      and c.landing_sku = p.purchased_sku        -- same SKU
      and c.click_time < p.purchase_time         -- click before purchase
      and c.click_time >= {{ dbt.dateadd('day', -var('default_lookback_days'), 'p.purchase_time') }}  -- within lookback window

)

select
    report_date,
    ad_id,
    purchased_sku                               as mixpanel_sku,
    'M1'                                        as attribution_model,
    {{ var('default_lookback_days') }}          as lookback_days,
    count(distinct order_id)                    as orders,
    sum(quantity)                               as units,
    cast(sum(line_revenue) as decimal(18,6))    as revenue

from m1_attributed
where _credit_rank = 1

group by 1, 2, 3, 4, 5
