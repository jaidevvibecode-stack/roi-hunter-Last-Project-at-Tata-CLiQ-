# ID alignment audit — P0.8

**Status: waiting for real data.** The *measurement* is automated; only the *result* is missing.

| Source | Total SKUs | Match rate to Meta `retailer_id` | Format difference |
|--------|-----------|-------------------------------|-------------------|
| Meta catalog `retailer_id` | — | — (baseline) | — |
| Mixpanel `sku` property | — | — | — |
| Redshift orders sku | — | — | — |

## How it is measured (already built)
- `mart.id_match_report` — daily share of Meta product-level **spend** and Mixpanel purchase **revenue** whose id maps to a catalog product.
- DQ checks `spend_id_match_rate` (≥ 95%, error) and `revenue_id_match_rate` (≥ 90%, error) — `config/dq_checks.yml`.
- Override mechanism: `transform/seeds/sku_mapping.csv` (header-only today) takes precedence in `int_product_key_map`.
- The Meta `product_id_raw` → `meta_item_id` parse rule is a **placeholder** (`stg_meta__ad_product_insights.sql`) until spike P0.4.

## When access arrives
Run the spikes, fill the table above, then either normalise in the staging models or populate the seed. Log the decision in `03_CONTEXT.md`.
