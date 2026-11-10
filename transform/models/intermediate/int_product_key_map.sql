-- transform/models/intermediate/int_product_key_map.sql
-- Maps meta_item_id ↔ retailer_id ↔ mixpanel SKU ↔ redshift SKU.
-- Generates a surrogate product_key.
-- Optionally joins to seeds/sku_mapping.csv for manual overrides.
-- DESIGN §9 int_product_key_map, §5 prerequisite P4.

{{
  config(
    materialized='table',
    schema='int'
  )
}}

with catalog as (

    select
        meta_item_id,
        retailer_id,
        product_name,
        brand,
        category_raw,
        product_type_raw,
        price,
        availability,
        image_url,
        url

    from {{ ref('stg_meta__catalog_products') }}
    where retailer_id is not null and retailer_id != ''

),

-- Optional manual SKU mapping seed (overrides auto-join)
-- Populated once ID alignment audit (P0.8) is complete
seed_map as (

    select
        meta_item_id,
        retailer_id                      as override_retailer_id,
        mixpanel_sku                     as override_mixpanel_sku,
        redshift_sku                     as override_redshift_sku
    from {{ ref('sku_mapping') }}
    where meta_item_id is not null

),

-- Join catalog to seed overrides (seed takes precedence)
mapped as (

    select
        c.meta_item_id,
        coalesce(s.override_retailer_id, c.retailer_id)     as retailer_id,
        coalesce(s.override_mixpanel_sku, c.retailer_id)    as mixpanel_sku,
        coalesce(s.override_redshift_sku, c.retailer_id)    as redshift_sku,
        c.product_name,
        c.brand,
        c.category_raw,
        c.product_type_raw,
        c.price,
        c.availability,
        c.image_url,
        c.url

    from catalog c
    left join seed_map s on c.meta_item_id = s.meta_item_id

)

select
    -- Surrogate key: stable hash of retailer_id
    {{ dbt_utils.generate_surrogate_key(['retailer_id']) }}  as product_key,
    meta_item_id,
    retailer_id,
    mixpanel_sku,
    redshift_sku,
    product_name,
    brand,
    category_raw,
    price,
    availability,
    image_url,
    url

from mapped
