-- transform/models/marts/dim_product.sql
-- Product dimension: one row per product_key.
-- Tracks first_seen / last_seen / is_active.
-- DESIGN §8.3 mart.dim_product.

{{
  config(
    materialized='table',
    schema='mart',
    sort=['retailer_id'],
    dist='product_key'
  )
}}

with source as (

    select
        product_key,
        retailer_id,
        meta_item_id,
        mixpanel_sku,
        redshift_sku,
        product_name,
        brand,
        category_raw                                       as category,
        price,
        availability,
        image_url,
        url,
        -- several Meta items (variants / catalogs) can share one retailer_id => one dim row per product_key
        row_number() over (partition by product_key order by meta_item_id) as _rn

    from {{ ref('int_product_key_map') }}

),

-- Track when each product was first and last seen in the catalog
catalog_dates as (

    select
        c.retailer_id,
        min(c.snapshot_date)    as first_seen,
        max(c.snapshot_date)    as last_seen

    from {{ source('raw_meta', 'catalog_products') }} c
    where c.retailer_id is not null
    group by 1

)

select
    s.product_key,
    s.retailer_id,
    s.meta_item_id,
    s.mixpanel_sku,
    s.redshift_sku,
    s.product_name,
    s.brand,
    s.category,
    s.price,
    s.availability,
    s.image_url,
    s.url,
    d.first_seen,
    d.last_seen,
    -- is_active = seen in the most recent catalog snapshot
    case when d.last_seen = (select max(snapshot_date) from {{ source('raw_meta', 'catalog_products') }})
         then true else false end as is_active

from source s
left join catalog_dates d on s.retailer_id = d.retailer_id
where s._rn = 1
