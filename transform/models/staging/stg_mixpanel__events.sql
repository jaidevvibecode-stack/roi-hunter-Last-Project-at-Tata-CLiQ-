-- transform/models/staging/stg_mixpanel__events.sql
-- Staging model for raw Mixpanel events.
-- Extracts typed columns from the properties SUPER column.
-- Property names come from dbt vars mirrored from config/mixpanel_mapping.yml (PLACEHOLDERS until spike P0.6).
-- DESIGN §9.

{{
  config(
    materialized='view',
    schema='stg'
  )
}}

/*
  Property names are PLACEHOLDERS until spike P0.6 / Q5 — change them in config/mixpanel_mapping.yml + dbt vars only.
*/

with source as (

    select
        event,
        event_time,
        distinct_id,
        insert_id,
        properties,
        ingested_at,
        row_number() over (
            partition by insert_id
            order by ingested_at desc
        ) as _row_num

    from {{ source('raw_mixpanel', 'events') }}

    {% if is_incremental() %}
    where event_time >= {{ dbt.dateadd('day', -var('restatement_days'), 'current_date') }}
    {% endif %}

),

final as (

    select
        event,
        event_time,
        -- Store distinct_id as a hash to avoid propagating PII beyond this model
        md5(distinct_id)                                             as distinct_id_hash,
        insert_id,

        -- NOTE: Redshift's json_extract_path_text returns '' (not NULL) for a missing key, so every text
        -- property is wrapped in nullif(trim(..), '') — otherwise every `is not null` filter downstream is a no-op.
        -- UTM / click linkage (DESIGN §5 prerequisite P1)
        nullif(trim({{ json_text('properties', var('mx_prop_utm_content')) }}), '')   as utm_content,
        nullif(trim({{ json_text('properties', var('mx_prop_utm_source')) }}), '')    as utm_source,
        nullif(trim({{ json_text('properties', var('mx_prop_utm_medium')) }}), '')    as utm_medium,
        nullif(trim({{ json_text('properties', var('mx_prop_utm_campaign')) }}), '')  as utm_campaign,
        nullif(trim({{ json_text('properties', var('mx_prop_fbclid')) }}), '')        as fbclid,

        -- Product fields
        nullif(trim({{ json_text('properties', var('mx_prop_sku')) }}), '')           as sku,
        nullif(trim({{ json_text('properties', var('mx_prop_order_id')) }}), '')      as order_id,
        nullif(cast({{ json_text('properties', var('mx_prop_price')) }} as decimal(18,6)), 0)  as price,
        nullif(cast({{ json_text('properties', var('mx_prop_quantity')) }} as integer), 0)     as quantity,

        ingested_at

    from source
    where _row_num = 1

)

select * from final
