-- transform/models/staging/stg_meta__ad_product_insights.sql
-- Staging model for raw_meta.ad_product_insights_daily (Pull B).
-- Parses product_id_raw → meta_item_id, casts types, deduplicates.
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
        date_start                                           as report_date,
        campaign_id,
        adset_id,
        ad_id,
        product_id_raw,
        -- Parse rule: TBD from spike P0.4 — documented in 03_CONTEXT.md F9.
        -- Placeholder: treat product_id_raw as the meta_item_id directly.
        -- Update this logic once spike confirms the actual format.
        product_id_raw                                       as meta_item_id,
        cast(spend           as decimal(18,6))               as spend,
        cast(impressions     as bigint)                      as impressions,
        cast(clicks          as bigint)                      as clicks_all,
        cast(inline_link_clicks as bigint)                   as link_clicks,
        api_version,
        ingested_at,
        run_id,
        -- Deduplication: keep the latest ingested row per (date, ad_id, product_id_raw)
        row_number() over (
            partition by date_start, ad_id, product_id_raw
            order by ingested_at desc
        ) as _row_num

    from {{ source('raw_meta', 'ad_product_insights_daily') }}

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
    product_id_raw,
    meta_item_id,
    spend,
    impressions,
    clicks_all,
    link_clicks,
    api_version,
    ingested_at,
    run_id

from source
where _row_num = 1
  and spend >= 0          -- guard against negative spend (data quality)
  and impressions >= 0
