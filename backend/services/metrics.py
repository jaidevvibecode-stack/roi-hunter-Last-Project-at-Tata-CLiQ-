"""Derived metrics — always recomputed from sums, never averaged (03_CONTEXT §4)."""
from __future__ import annotations


def _div(n: float, d: float) -> float | None:
    return n / d if d else None


def derive(spend: float, impressions: float, link_clicks: float, orders: float, revenue: float) -> dict[str, float | None]:
    return {
        "ctr": _div(link_clicks, impressions),
        "cpm": spend / impressions * 1000 if impressions else None,
        "cost_per_impression": _div(spend, impressions),
        "cpc": _div(spend, link_clicks),
        "roas": _div(revenue, spend),
        "cvr": _div(orders, link_clicks),
        "aov": _div(revenue, orders),
    }


def delta_pct(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return (current - prior) / prior * 100
