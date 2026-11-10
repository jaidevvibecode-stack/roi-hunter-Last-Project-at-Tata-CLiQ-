-- transform/models/staging/stg_meta__catalog_products.sql
-- Latest catalog snapshot per product.
-- DESIGN §9.

{{
  config(
    materialized='view',
    schema='stg'
  )
}}

with latest_snapshot as (

    select
        *,
        row_number() over (
            partition by catalog_id, id
            order by snapshot_date desc
        ) as _row_num

    from {{ source('raw_meta', 'catalog_products') }}

),

final as (

    select
        catalog_id,
        id                              as meta_item_id,
        retailer_id,
        retailer_product_group_id,
        lower(trim(name))               as product_name,
        lower(trim(brand))              as brand,
        lower(trim(category))           as category_raw,
        lower(trim(product_type))       as product_type_raw,
        price,
        sale_price,
        currency,
        availability,
        url,
        image_url,
        custom_label_0,
        custom_label_1,
        custom_label_2,
        custom_label_3,
        custom_label_4,
        snapshot_date,
        ingested_at

    from latest_snapshot
    where _row_num = 1

)

select * from final
