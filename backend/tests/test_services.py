from __future__ import annotations

import pytest

from backend.services.metrics import delta_pct, derive
from backend.services.rules import build_recommendations, pareto
from backend.services.segmentation import segment_products

CFG = {"target_roas": 3.0, "high_spend_percentile": 0.5, "min_spend_for_classification": 100}
# spends >=100: [200,200,1000,1000] -> percentile_cont(.5) = 600


def P(key, spend, roas, availability="in stock"):
    return {"product_key": key, "retailer_id": key, "product_name": key, "spend": spend,
            "revenue": spend * (roas or 0), "roas": roas, "availability": availability}


def test_derive_zero_division_is_null():
    d = derive(0, 0, 0, 0, 0)
    assert all(v is None for v in d.values())


def test_derive_values():
    d = derive(100, 10_000, 200, 4, 400)
    assert d["cpm"] == pytest.approx(10) and d["ctr"] == pytest.approx(0.02) and d["roas"] == 4


def test_delta_pct():
    assert delta_pct(110, 100) == pytest.approx(10)
    assert delta_pct(5, 0) is None and delta_pct(None, 3) is None


def test_segmentation_quadrants():
    prods = [P("a", 1000, 5), P("b", 1000, 1), P("c", 200, 5), P("d", 200, 1), P("e", 50, 9)]
    seg = {p["product_key"]: p["segment"] for p in segment_products(prods, CFG)}
    assert seg == {"a": "Stars", "b": "Bleeders", "c": "Hidden Gems", "d": "Zombies", "e": "Insufficient data"}


def test_recommendations_oos_and_ordering():
    prods = segment_products([P("a", 1000, 5), P("b", 1000, 1), P("x", 300, 5, "out of stock")], CFG)
    recs = build_recommendations(prods)
    ids = [r["rule_id"] for r in recs]
    assert "oos_spend" in ids and "review_bleeders" in ids
    assert recs[0]["severity"] == "critical"
    assert all(r["retailer_ids"] for r in recs)


def test_pareto():
    p = pareto([{"spend": v} for v in [80, 10, 5, 3, 2]])
    assert p["skus_for_80pct"] == 1


def test_percentile_matches_sql_percentile_cont():
    from backend.services.segmentation import percentile_cont

    assert percentile_cont([50, 80, 210, 310], 0.5) == 145          # (80+210)/2
    assert percentile_cont([10], 0.8) == 10
    assert percentile_cont([1, 2, 3, 4, 5], 0.8) == 4.2
