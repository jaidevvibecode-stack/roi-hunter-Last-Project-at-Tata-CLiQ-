-- transform/models/marts/product_performance_daily.sql
-- THE MAIN SERVING TABLE. One row per (report_date × ad_id × product_key × attribution_model × lookback_days).
-- Joined metrics: delivery (spend, impressions, clicks) + attribution (revenue, orders, units).
-- Derived metrics: CTR, CPM, CPC, ROAS — computed from sums, never averaged.
-- DESIGN §8.3 mart.product_performance_daily.

{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['report_date', 'ad_id', 'product_key', 'attribution_model', 'lookback_days'],
    schema='mart',
    sort=['report_date'],
    dist='product_key'
  )
}}

with delivery as (

    select
        p.report_date,
        p.account_id,
        p.campaign_id,
        p.adset_id,
        p.ad_id,
        k.product_key,
        sum(p.spend)                                    as spend,
        sum(p.impressions)                              as impressions,
        sum(p.link_clicks)                              as link_clicks,
        sum(p.clicks_all)                               as clicks_all

    from {{ ref('stg_meta__ad_product_insights') }} p
    join {{ ref('int_product_key_map') }} k
      on p.meta_item_id = k.meta_item_id

    {% if is_incremental() %}
    where p.report_date >= {{ dbt.dateadd('day', -var('restatement_days'), 'current_date') }}
    {% endif %}

    group by 1, 2, 3, 4, 5, 6

),

-- One product_key per Mixpanel SKU (several catalog items can share a SKU)
sku_to_key as (
    select mixpanel_sku, min(product_key) as product_key
    from {{ ref('int_product_key_map') }}
    group by 1
),

-- Union all attribution models (each already at grain: report_date x ad_id x SKU)
attribution_all as (

    select a.report_date, a.ad_id, k.product_key, a.attribution_model, a.lookback_days, a.orders, a.units, a.revenue
    from {{ ref('int_attribution_m1') }} a join sku_to_key k on a.mixpanel_sku = k.mixpanel_sku

    union all

    select a.report_date, a.ad_id, k.product_key, a.attribution_model, a.lookback_days, a.orders, a.units, a.revenue
    from {{ ref('int_attribution_m2') }} a join sku_to_key k on a.mixpanel_sku = k.mixpanel_sku

    union all

    select report_date, ad_id, product_key, attribution_model, lookback_days, orders, units, revenue
    from {{ ref('int_attribution_m3') }}

    union all

    select a.report_date, a.ad_id, k.product_key, a.attribution_model, a.lookback_days, a.orders, a.units, a.revenue
    from {{ ref('int_attribution_m4') }} a join sku_to_key k on a.mixpanel_sku = k.mixpanel_sku
),

-- Every delivery row exists once per model, even with zero attributed orders.
-- (A plain LEFT JOIN would leave attribution_model NULL and the API filter would silently drop spend.)
model_spine as (
    select 'M1' as attribution_model union all select 'M2' union all select 'M3' union all select 'M4'
),

delivery_x_model as (
    select d.*, s.attribution_model, {{ var('default_lookback_days') }} as lookback_days
    from delivery d cross join model_spine s
),

ad_dim as (
    -- latest known campaign / ad set / account for each ad (for attributed rows that had no delivery that day)
    select ad_id, account_id, campaign_id, adset_id
    from (
        select ad_id, account_id, campaign_id, adset_id,
               row_number() over (partition by ad_id order by report_date desc) as _rn
        from {{ ref('stg_meta__ad_insights') }}
    ) t
    where _rn = 1
),

-- FULL OUTER JOIN: attributed revenue with no same-day product delivery (e.g. M2 halo, M4 last-touch credit
-- a product the ad did not show that day) must not be dropped — it appears with spend = 0.
joined as (

    select
        coalesce(d.report_date, a.report_date)             as report_date,
        coalesce(d.ad_id, a.ad_id)                         as ad_id,
        coalesce(d.product_key, a.product_key)             as product_key,
        coalesce(d.attribution_model, a.attribution_model) as attribution_model,
        coalesce(d.lookback_days, a.lookback_days)         as lookback_days,
        d.account_id, d.campaign_id, d.adset_id,
        coalesce(d.spend, 0)                               as spend,
        coalesce(d.impressions, 0)                         as impressions,
        coalesce(d.link_clicks, 0)                         as link_clicks,
        coalesce(d.clicks_all, 0)                          as clicks_all,
        coalesce(a.orders, 0)                              as orders,
        coalesce(a.units, 0)                               as units,
        coalesce(a.revenue, 0)                             as revenue

    from delivery_x_model d
    full outer join attribution_all a
      on  a.report_date        = d.report_date
      and a.ad_id              = d.ad_id
      and a.product_key        = d.product_key
      and a.attribution_model  = d.attribution_model
      and a.lookback_days      = d.lookback_days

),

final as (

    select
        j.report_date,
        coalesce(j.account_id,  x.account_id)              as account_id,
        coalesce(j.campaign_id, x.campaign_id)             as campaign_id,
        coalesce(j.adset_id,    x.adset_id)                as adset_id,
        j.ad_id,
        j.product_key,
        j.attribution_model,
        j.lookback_days,

        j.spend, j.impressions, j.link_clicks, j.clicks_all,
        j.orders, j.units, j.revenue,

        -- Derived metrics — computed from sums (DESIGN §4: never average ratios)
        case when j.impressions > 0 then j.link_clicks::decimal / j.impressions end    as ctr,
        case when j.impressions > 0 then j.clicks_all::decimal / j.impressions end     as ctr_all,
        case when j.impressions > 0 then j.spend / j.impressions * 1000 end            as cpm,
        case when j.impressions > 0 then j.spend / j.impressions end                   as cost_per_impression,
        case when j.link_clicks > 0 then j.spend / j.link_clicks end                   as cpc,
        case when j.spend > 0 then j.revenue / j.spend end                             as roas,
        case when j.link_clicks > 0 then j.orders::decimal / j.link_clicks end         as cvr,
        case when j.orders > 0 then j.revenue / j.orders end                           as aov,

        current_timestamp                                                              as updated_at

    from joined j
    left join ad_dim x on x.ad_id = j.ad_id

)

select * from final
