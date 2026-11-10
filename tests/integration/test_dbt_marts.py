"""dbt marts built from hand-built fixtures must equal the hand-computed expectations (tests/fixtures/expected.json)."""
from __future__ import annotations

import pytest

from backend.services.segmentation import segment_products
from conftest import EXPECTED


def test_mart_totals_per_model(rows):
    got = {
        r[0]: dict(zip(("spend", "impressions", "link_clicks", "orders", "units", "revenue"), map(float, r[1:]), strict=True))
        for r in rows("""select attribution_model, sum(spend), sum(impressions), sum(link_clicks), sum(orders), sum(units), sum(revenue)
                         from mart.product_performance_daily group by 1""")
    }
    assert got == {m: {k: float(v) for k, v in vals.items()} for m, vals in EXPECTED["mart_totals_by_model"].items()}


def test_every_attributed_row_matches(rows):
    got = sorted(
        (r[0], str(r[1]), r[2], r[3], float(r[4]), int(r[5]), int(r[6]), float(r[7]))
        for r in rows("""select p.attribution_model, p.report_date, p.ad_id, d.retailer_id, p.spend, p.orders, p.units, p.revenue
                         from mart.product_performance_daily p join mart.dim_product d using (product_key)
                         where p.revenue > 0 or p.orders > 0""")
    )
    want = sorted((m, d, ad, sku, float(sp), o, u, float(rev)) for m, d, ad, sku, sp, o, u, rev in EXPECTED["mart_rows_with_revenue"])
    assert got == want


def test_attributed_revenue_is_never_dropped_when_product_had_no_delivery(rows):
    """M4 credits SKU-D / SKU-C on ad1 on days ad1 did not deliver them: revenue must survive with spend = 0."""
    zero_spend = rows("""select d.retailer_id, p.revenue from mart.product_performance_daily p join mart.dim_product d using (product_key)
                         where p.attribution_model = 'M4' and p.spend = 0 and p.revenue > 0 order by 1""")
    assert [(a, float(b)) for a, b in zero_spend] == [("SKU-C", 40.0), ("SKU-D", 30.0)]


def test_products_without_attribution_still_have_spend_in_every_model(rows):
    """Regression: a plain LEFT JOIN left attribution_model NULL and the API filter silently dropped spend."""
    (n,) = rows("select count(*) from mart.product_performance_daily where attribution_model is null")[0]
    assert n == 0
    per_model = {m: float(s) for m, s in rows("select attribution_model, sum(spend) from mart.product_performance_daily group by 1")}
    assert set(per_model.values()) == {650.0}


def test_spend_reconciliation(rows):
    got = {str(r[0]): [float(r[1]), float(r[2]), float(r[3])] for r in rows(
        "select report_date, ad_level_catalog_spend, product_level_spend, unallocated_spend from mart.spend_reconciliation")}
    assert got == {d: [float(x) for x in v] for d, v in EXPECTED["spend_reconciliation"].items()}


def test_id_match_report(rows):
    got = {str(r[0]): dict(zip(("total_spend", "matched_spend", "total_revenue", "matched_revenue"), (float(x) for x in r[1:]), strict=True))
           for r in rows("""select report_date, total_spend, matched_spend, total_revenue, matched_revenue
                            from mart.id_match_report where report_date <= '2026-03-03'""")}
    assert got == {d: {k: float(v) for k, v in vals.items()} for d, vals in EXPECTED["id_match"].items()}


def test_dedupe_and_filters_in_staging(rows):
    assert [float(r[0]) for r in rows("select spend from stg.stg_meta__ad_insights where ad_id = 'ad1' and report_date = '2026-03-01'")] == [155.0]
    assert rows("select count(*) from stg.stg_meta__ad_insights where spend < 0")[0][0] == 0
    # duplicate $insert_id p1 collapses to one row; missing order_id is NULL, not ''
    assert rows("select count(*) from stg.stg_mixpanel__events where insert_id = 'p1'")[0][0] == 1
    assert rows("select count(*) from stg.stg_mixpanel__events where order_id = ''")[0][0] == 0
    assert rows("select availability from stg.stg_meta__catalog_products where meta_item_id = 'm1'")[0][0] == "in stock"


def test_oos_spend(rows):
    got = {f"{r[0]}|{r[1]}": float(r[2]) for r in rows("select report_date, retailer_id, spend_on_oos from mart.oos_spend_daily")}
    assert got == {k: float(v) for k, v in EXPECTED["oos_spend"].items()}


def test_segments_sql_matches_expected_and_python_service(rows):
    sql = {r[0]: r[1] for r in rows("select d.retailer_id, s.segment from mart.product_segments s join mart.dim_product d using (product_key)")}
    assert sql == EXPECTED["segments_m1"]

    # The API's Python segmentation must agree with the dbt mart on the same data and thresholds.
    prods = [
        {"retailer_id": sku, "spend": float(sp), "revenue": float(rev), "roas": float(rev) / float(sp) if float(sp) else None}
        for sku, sp, rev in rows("""select d.retailer_id, s.spend, s.revenue from mart.product_segments s join mart.dim_product d using (product_key)""")
    ]
    cfg = {**EXPECTED["segments_vars"], "target_roas": EXPECTED["segments_vars"]["target_roas"]}
    py = {p["retailer_id"]: p["segment"] for p in segment_products(prods, cfg)}
    assert py == sql


@pytest.mark.parametrize("sku,vals", EXPECTED["products_m1"].items())
def test_m1_product_totals(rows, sku, vals):
    r = rows("""select sum(p.spend), sum(p.revenue), sum(p.orders), sum(p.link_clicks) from mart.product_performance_daily p
                join mart.dim_product d using (product_key) where d.retailer_id = %s and p.attribution_model = 'M1'""", (sku,))[0]
    assert [float(x) for x in r] == [float(vals[k]) for k in ("spend", "revenue", "orders", "link_clicks")]
