-- transform/models/staging/stg_meta__ad_insights.sql
-- Staging model for raw_meta.ad_insights_daily (Pull A).
-- Extracts Meta-reported purchase metrics from the actions/action_values SUPER columns.
-- DESIGN §9.

{{
  config(
    materialized='view',
    schema='stg'
  )
}}

with source as (

    select
        account_id,
        date_start                                              as report_date,
        campaign_id,
        adset_id,
        ad_id,
        account_currency,
        cast(spend              as decimal(18,6))               as spend,
        cast(impressions        as bigint)                      as impressions,
        cast(clicks             as bigint)                      as clicks_all,
        cast(inline_link_clicks as bigint)                      as link_clicks,
        cast(reach              as bigint)                      as reach,
        cast(frequency          as decimal(12,6))               as frequency,

        -- Meta-reported purchases / value (NOT available at product_id level — DESIGN §3 F2)
        coalesce(cast({{ action_value('actions', 'purchase') }} as decimal(18,6)), 0)::bigint as meta_purchases,
        coalesce(cast({{ action_value('action_values', 'purchase') }} as decimal(18,6)), 0)   as meta_purchase_value,

        attribution_setting,
        api_version,
        ingested_at,
        run_id,

        row_number() over (
            partition by date_start, ad_id
            order by ingested_at desc
        ) as _row_num

    from {{ source('raw_meta', 'ad_insights_daily') }}

    {% if is_incremental() %}
    where date_start >= {{ dbt.dateadd('day', -var('restatement_days'), 'current_date') }}
    {% endif %}

)

select
    account_id,
    report_date,
    campaign_id,
    adset_id,
    ad_id,
    account_currency,
    spend,
    impressions,
    clicks_all,
    link_clicks,
    reach,
    frequency,
    meta_purchases,
    meta_purchase_value,
    attribution_setting,
    api_version,
    ingested_at,
    run_id

from source
where _row_num = 1
  and spend >= 0
