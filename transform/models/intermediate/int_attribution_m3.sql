-- transform/models/intermediate/int_attribution_m3.sql
-- Attribution Model M3: Proportional allocation of Meta-reported purchase value.
-- Logic: Meta ad-level action_values (purchase) allocated to products in that ad
--        by each product's share of link_clicks (fallback: impressions).
-- DESIGN §5 Model M3.
-- Label in UI: "Modelled" — this is a proxy, not a first-party observation.

{{
  config(
    materialized='table',
    schema='int'
  )
}}

with ad_level as (

    -- Meta-reported purchase value per ad per day (Pull A)
    select
        report_date,
        ad_id,
        meta_purchase_value,
        meta_purchases

    from {{ ref('stg_meta__ad_insights') }}
    where meta_purchase_value > 0

),

product_level as (

    -- Link clicks per (ad, product) per day (Pull B)
    -- Used as the allocation weight
    select
        report_date,
        ad_id,
        meta_item_id,
        link_clicks,
        impressions,
        spend

    from {{ ref('stg_meta__ad_product_insights') }}

),

product_with_key as (

    select
        p.report_date,
        p.ad_id,
        p.meta_item_id,
        m.product_key,
        m.mixpanel_sku,
        p.link_clicks,
        p.impressions,
        p.spend

    from product_level p
    left join {{ ref('int_product_key_map') }} m
      on p.meta_item_id = m.meta_item_id

),

-- Compute each product's share of clicks/impressions within the ad on that day
ad_product_totals as (

    select
        report_date,
        ad_id,
        meta_item_id,
        product_key,
        mixpanel_sku,
        link_clicks,
        impressions,
        spend,
        sum(link_clicks)   over (partition by report_date, ad_id) as ad_total_link_clicks,
        sum(impressions)   over (partition by report_date, ad_id) as ad_total_impressions

    from product_with_key

),

allocated as (

    select
        p.report_date,
        p.ad_id,
        p.product_key,
        p.mixpanel_sku,
        'M3'                                             as attribution_model,
        {{ var('default_lookback_days') }}               as lookback_days,
        -- Use link_click share; fall back to impression share when 0
        case
            when p.ad_total_link_clicks > 0
                then p.link_clicks::decimal / p.ad_total_link_clicks
            when p.ad_total_impressions > 0
                then p.impressions::decimal / p.ad_total_impressions
            else 0
        end                                              as allocation_weight,
        a.meta_purchase_value,
        a.meta_purchases

    from ad_product_totals p
    join ad_level a
      on  a.report_date = p.report_date
      and a.ad_id = p.ad_id

)

select
    report_date,
    ad_id,
    product_key,
    mixpanel_sku,
    attribution_model,
    lookback_days,
    -- Proportionally allocated orders and revenue
    -- These are modelled estimates — label them clearly in the UI
    round(sum(meta_purchases * allocation_weight))       as orders,
    cast(null as bigint)                                 as units,   -- not available from Meta
    cast(sum(meta_purchase_value * allocation_weight) as decimal(18,6)) as revenue

from allocated
where allocation_weight > 0

group by 1, 2, 3, 4, 5, 6
