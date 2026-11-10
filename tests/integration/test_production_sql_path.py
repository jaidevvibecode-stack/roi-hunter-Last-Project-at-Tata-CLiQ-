"""
The backend's PRODUCTION data source (RedshiftDataSource -> validated read-only SQL -> marts) executed against the
dbt-built fixture warehouse, and the HTTP API on top of it. Numbers asserted are hand-computed (expected.json).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.core.db import UnsafeQueryError, run_select
from backend.data.redshift_source import RedshiftDataSource
from backend.main import create_app
from backend.queries.common import CommonFilters
from conftest import EXPECTED

pytestmark = pytest.mark.usefixtures("warehouse", "redshift_env")

WINDOW = {"start_date": "2026-03-01", "end_date": "2026-03-03"}
F = CommonFilters(start_date=date(2026, 3, 1), end_date=date(2026, 3, 3))


def test_product_aggregates_match_expected():
    got = {p["retailer_id"]: p for p in RedshiftDataSource().product_aggregates(F)}
    assert set(got) == set(EXPECTED["products_m1"])
    for sku, want in EXPECTED["products_m1"].items():
        for k, v in want.items():
            assert got[sku][k] == pytest.approx(v), (sku, k)
    assert got["SKU-A"]["category"] == "footwear" and got["SKU-B"]["availability"] == "out of stock"


def test_overview_kpis_and_ratios_from_sums():
    o = RedshiftDataSource().overview(F)
    k = o["kpis"]
    assert k["spend"]["value"] == pytest.approx(650)
    assert k["revenue"]["value"] == pytest.approx(230)
    assert k["roas"]["value"] == pytest.approx(230 / 650)
    assert k["ctr"]["value"] == pytest.approx(960 / 65000)
    assert k["cpm"]["value"] == pytest.approx(650 / 65000 * 1000)
    assert k["spend"]["delta_pct"] is None            # nothing in the prior period
    assert o["unallocated_spend"] == pytest.approx(9)  # 5 + 2 + 2
    assert o["unmapped_spend"] == pytest.approx(10)    # product m9 is not in the catalog: reported, not silently lost
    assert [t["date"] for t in o["trend"]] == ["2026-03-01", "2026-03-02", "2026-03-03"]


@pytest.mark.parametrize("model", ["M1", "M2", "M3", "M4"])
def test_each_attribution_model_revenue(model):
    from dataclasses import replace

    t = RedshiftDataSource()._totals(replace(F, attribution_model=model))
    want = EXPECTED["mart_totals_by_model"][model]
    assert t["revenue"] == pytest.approx(want["revenue"]) and t["orders"] == pytest.approx(want["orders"])
    assert t["spend"] == pytest.approx(want["spend"])  # spend identical regardless of model


def test_attribution_compare_has_all_four_models():
    rows = {r["retailer_id"]: r for r in RedshiftDataSource().attribution_compare(F, 1, 50)["data"]}
    a = rows["SKU-A"]
    assert (a["revenue_m1"], a["revenue_m2"], a["revenue_m3"], a["revenue_m4"]) == pytest.approx((150, 190, 320, 150))
    assert a["roas_m3"] == pytest.approx(320 / 310)


def test_filters_breakdown_trend_and_search():
    src = RedshiftDataSource()
    opts = src.filter_options(F)
    assert set(opts["brands"]) == {"aster", "zephyr", "veda", "orbit"} and "out of stock" in opts["availability"]
    key = next(p["product_key"] for p in src.product_aggregates(F) if p["retailer_id"] == "SKU-C")
    bd = src.breakdown(F, key, "ad")
    assert {r["name"] for r in bd} == {"ad2"} and bd[0]["spend"] == pytest.approx(210)
    assert sum(t["spend"] for t in src.daily_series(F, key)) == pytest.approx(210)
    only_a = CommonFilters(start_date=F.start_date, end_date=F.end_date, search="alpha")
    assert [p["retailer_id"] for p in src.product_aggregates(only_a)] == ["SKU-A"]
    oos = CommonFilters(start_date=F.start_date, end_date=F.end_date, availability=["out of stock"])
    assert [p["retailer_id"] for p in src.product_aggregates(oos)] == ["SKU-B"]


def test_search_wildcards_are_literal():
    src = RedshiftDataSource()
    for evil in ("%", "_", "x'; drop table mart.dim_product;--"):
        assert src.product_aggregates(CommonFilters(start_date=F.start_date, end_date=F.end_date, search=evil)) == []


def test_data_quality_and_freshness_shapes():
    dq = RedshiftDataSource().data_quality()
    assert dq["spend_match_rate"] == pytest.approx(650 / 660) and dq["revenue_match_rate"] == pytest.approx(325 / 335)
    assert len(dq["reconciliation"]) == 3
    assert RedshiftDataSource().freshness()["sources"] is not None


def test_segments_and_recommendations_through_source():
    seg = RedshiftDataSource().segments(F)
    assert sum(r["products"] for r in seg["summary"]) == 4
    recs = RedshiftDataSource().recommendations(F)
    assert any(r["rule_id"] == "oos_spend" and r["retailer_ids"] == ["SKU-B"] for r in recs)


def test_db_layer_refuses_writes_even_if_asked():
    with pytest.raises(UnsafeQueryError):
        run_select("DELETE FROM mart.dim_product")
    with pytest.raises(UnsafeQueryError):
        run_select("SELECT * FROM raw_meta.ad_insights_daily")
    with pytest.raises(UnsafeQueryError):
        run_select("SELECT 1; SELECT 2")


def test_session_is_read_only_at_the_database_level():
    """Defence in depth: even a statement that slipped past the guard cannot write (READ ONLY session)."""
    from backend.core.db import _connect

    conn = _connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception, match="read-only"):
            cur.execute("CREATE TABLE ops.should_not_exist (a int)")
    finally:
        conn.close()


def test_http_api_end_to_end_on_production_path():
    c = TestClient(create_app())
    qs = "&".join(f"{k}={v}" for k, v in WINDOW.items())
    ov = c.get(f"/api/v1/overview?{qs}").json()
    assert ov["meta"]["data_source"] == "redshift" and ov["kpis"]["spend"]["value"] == pytest.approx(650)
    pr = c.get(f"/api/v1/products?{qs}&sort=roas&order=desc").json()
    assert pr["total"] == 4 and pr["data"][0]["retailer_id"] == "SKU-A"
    assert c.get(f"/api/v1/products?{qs}&sort=spend;drop").status_code == 400
    csv = c.get(f"/api/v1/export/products.csv?{qs}").text.splitlines()
    assert csv[0].startswith("product_key,") and len(csv) == 5
    assert c.get("/api/v1/data-quality").status_code == 200


def test_unqualified_tables_cannot_reach_other_schemas_search_path_is_mart_and_ops(warehouse):
    """Defence in depth beyond the regex guard: an unqualified name resolves only in mart/ops, never public."""
    with warehouse.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS public.leak_probe (secret text)")
        cur.execute("INSERT INTO public.leak_probe VALUES ('x')")
    try:
        assert run_select("SELECT product_key FROM dim_product LIMIT 1")        # mart resolves unqualified
        with pytest.raises(Exception, match="does not exist"):
            run_select("SELECT secret FROM leak_probe")                          # public does NOT
    finally:
        with warehouse.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS public.leak_probe")
