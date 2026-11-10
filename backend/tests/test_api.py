from __future__ import annotations

import pytest

ENDPOINTS = ["overview", "products", "trends", "filters/options", "attribution/compare",
             "segments", "recommendations", "data-quality", "meta/freshness"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_endpoint_ok_and_labelled_demo(client, window, path):
    r = client.get(f"/api/v1/{path}?{window}")
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["data_source"] == "demo"


def test_overview_totals_equal_product_table(client, window):
    ov = client.get(f"/api/v1/overview?{window}").json()
    prods = client.get(f"/api/v1/products?{window}&page_size=500").json()
    total_pages = (prods["total"] + 499) // 500
    spend = sum(p["spend"] for p in prods["data"])
    for pg in range(2, total_pages + 1):
        spend += sum(p["spend"] for p in client.get(f"/api/v1/products?{window}&page_size=500&page={pg}").json()["data"])
    assert ov["kpis"]["spend"]["value"] == pytest.approx(spend)


def test_ratios_recomputed_from_sums(client, window):
    k = client.get(f"/api/v1/overview?{window}").json()["kpis"]
    assert k["roas"]["value"] == pytest.approx(k["revenue"]["value"] / k["spend"]["value"])
    assert k["ctr"]["value"] == pytest.approx(k["link_clicks"]["value"] / k["impressions"]["value"])


def test_sort_and_pagination(client, window):
    d = client.get(f"/api/v1/products?{window}&sort=roas&order=asc&page_size=20").json()["data"]
    vals = [p["roas"] for p in d if p["roas"] is not None]
    assert vals == sorted(vals)


def test_models_differ(client, window):
    m1 = client.get(f"/api/v1/overview?{window}&attribution_model=M1").json()["kpis"]["revenue"]["value"]
    m2 = client.get(f"/api/v1/overview?{window}&attribution_model=M2").json()["kpis"]["revenue"]["value"]
    assert m1 != m2


def test_product_detail_and_404(client, window):
    key = client.get(f"/api/v1/products?{window}&page_size=1").json()["data"][0]["product_key"]
    assert client.get(f"/api/v1/products/{key}?{window}").status_code == 200
    assert client.get(f"/api/v1/products/{key}/breakdown?{window}&by=ad").status_code == 200
    assert client.get(f"/api/v1/products/nonexistent?{window}").status_code == 404


def test_segments_cover_all_products(client, window):
    s = client.get(f"/api/v1/segments?{window}").json()
    assert sum(r["products"] for r in s["summary"]) == len(s["products"])


def test_recommendations_are_read_only(client, window):
    r = client.get(f"/api/v1/recommendations?{window}").json()
    assert r["write_back_enabled"] is False


def test_bad_inputs_rejected(client, window):
    assert client.get("/api/v1/overview?start_date=2026-02-01&end_date=2026-01-01").status_code == 422
    assert client.get(f"/api/v1/overview?{window}&attribution_model=M9").status_code == 422
    assert client.get("/api/v1/overview?start_date=2020-01-01&end_date=2026-01-01").status_code == 422
