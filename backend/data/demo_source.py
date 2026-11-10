"""
backend/data/demo_source.py
----------------------------
SYNTHETIC data source used for local demos and tests (DATA_SOURCE=demo).
Deterministic (seeded). Products, brands, spend and revenue are FICTIONAL —
this is NOT Tata data and says nothing about real performance. Every API
response carries meta.data_source="demo" and the UI shows a DEMO DATA badge.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterator
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from backend.data.base import DataSource
from backend.queries.common import CommonFilters

_BRANDS = ["Aster", "Nova Wear", "Kiran & Co", "Urban Loom", "Meridian", "Saffron Lane",
           "Orbit", "Veda", "Lumen", "Harbor", "Zephyr", "Tarang"]
_CATEGORIES = {
    "Footwear": ["Sneakers", "Loafers", "Sandals", "Boots"],
    "Apparel": ["Kurta", "Shirt", "Jacket", "Dress"],
    "Watches": ["Chronograph", "Smartwatch", "Analog Watch"],
    "Handbags": ["Tote", "Sling Bag", "Backpack"],
    "Beauty": ["Serum", "Perfume", "Lipstick"],
    "Electronics": ["Earbuds", "Speaker", "Power Bank"],
}
_CAMPAIGNS = [
    ("act_demo_1", "cmp_101", "DPA | Always-on | Footwear"),
    ("act_demo_1", "cmp_102", "DPA | Always-on | Apparel"),
    ("act_demo_1", "cmp_103", "DPA | Festive Sale | All"),
    ("act_demo_1", "cmp_104", "DPA | Retargeting | 7d"),
    ("act_demo_2", "cmp_201", "DPA | Luxury | Watches & Bags"),
    ("act_demo_2", "cmp_202", "DPA | Beauty | Prospecting"),
    ("act_demo_2", "cmp_203", "DPA | Electronics | Broad"),
    ("act_demo_2", "cmp_204", "DPA | Retargeting | 28d"),
]
_MODEL_MULT = {"m1": 0.72, "m2": 1.28, "m3": 1.0, "m4": 0.88}
_DAYS = 90


class DemoDataSource(DataSource):
    name = "demo"

    def __init__(self) -> None:
        rng = random.Random(20260923)
        self.end = date.today() - timedelta(days=1)
        self.start = self.end - timedelta(days=_DAYS - 1)
        self._catalog: list[dict[str, Any]] = []
        for i in range(400):
            cat = rng.choice(list(_CATEGORIES))
            brand = rng.choice(_BRANDS)
            kind = rng.choice(_CATEGORIES[cat])
            rid = f"TC{rng.randint(100000, 999999)}"
            self._catalog.append({
                "product_key": hashlib.sha256(f"{rid}-{i}".encode()).hexdigest()[:16],
                "retailer_id": rid,
                "product_name": f"{brand} {kind} {rng.choice(['Classic', 'Pro', 'Lite', 'Edge', 'Max'])}",
                "brand": brand,
                "category": cat,
                "availability": "in stock" if rng.random() > 0.08 else "out of stock",
                "image_url": None,
                "_pop": rng.lognormvariate(0, 1.1),
                "_quality": max(0.4, rng.lognormvariate(math.log(3.0), 0.55)),
                "_ctr": rng.uniform(0.008, 0.032),
                "_cpm": rng.uniform(90, 260),
                "_aov": rng.uniform(900, 9000),
                "_camps": rng.sample(range(len(_CAMPAIGNS)), k=rng.choice([1, 1, 2])),
            })
        self.rows: list[dict[str, Any]] = []
        for pi, p in enumerate(self._catalog):
            for ci in p["_camps"]:
                for d in range(_DAYS):
                    day = self.start + timedelta(days=d)
                    season = 1.0 + 0.25 * (day.weekday() >= 5) + 0.35 * d / _DAYS
                    spend = max(0.0, 120 * p["_pop"] * season * rng.uniform(0.6, 1.4) / len(p["_camps"]))
                    if spend < 3:
                        continue
                    impressions = int(spend / p["_cpm"] * 1000)
                    clicks = int(impressions * p["_ctr"] * rng.uniform(0.8, 1.2))
                    rev_base = spend * p["_quality"] * rng.uniform(0.6, 1.5)
                    row: dict[str, Any] = {
                        "date": day, "pi": pi, "ci": ci,
                        "spend": spend, "impressions": impressions,
                        "link_clicks": clicks, "clicks_all": int(clicks * 1.35),
                    }
                    for m, mult in _MODEL_MULT.items():
                        rev = rev_base * mult
                        row[f"rev_{m}"] = rev
                        row[f"ord_{m}"] = rev / p["_aov"]
                        row[f"units_{m}"] = rev / p["_aov"] * rng.uniform(1.0, 1.4)
                    self.rows.append(row)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _match(self, f: CommonFilters, r: dict[str, Any]) -> bool:
        if not (f.start_date <= r["date"] <= f.end_date):
            return False
        p = self._catalog[r["pi"]]
        acct, cid, _ = _CAMPAIGNS[r["ci"]]
        if f.account_ids and acct not in f.account_ids:
            return False
        if f.campaign_ids and cid not in f.campaign_ids:
            return False
        if f.brands and p["brand"].lower() not in {b.lower() for b in f.brands}:
            return False
        if f.categories and p["category"].lower() not in {c.lower() for c in f.categories}:
            return False
        if f.availability and p["availability"] not in f.availability:
            return False
        if f.search:
            s = f.search.lower()
            if s not in p["product_name"].lower() and s not in p["retailer_id"].lower():
                return False
        return True

    def _rows(self, f: CommonFilters, product_key: str | None = None) -> Iterator[dict[str, Any]]:
        for r in self.rows:
            if product_key and self._catalog[r["pi"]]["product_key"] != product_key:
                continue
            if self._match(f, r):
                yield r

    @staticmethod
    def _attrib(f: CommonFilters, r: dict[str, Any]) -> tuple[float, float, float]:
        m = f.attribution_model.lower()
        return r[f"rev_{m}"], r[f"ord_{m}"], r[f"units_{m}"]

    # ── DataSource implementation ─────────────────────────────────────────────
    def product_aggregates(self, f: CommonFilters) -> list[dict[str, Any]]:
        acc: dict[int, dict[str, Any]] = {}
        for r in self._rows(f):
            a = acc.setdefault(r["pi"], dict.fromkeys(
                ("spend", "impressions", "link_clicks", "clicks_all", "orders", "units", "revenue"), 0.0))
            rev, orders, units = self._attrib(f, r)
            a["spend"] += r["spend"]; a["impressions"] += r["impressions"]
            a["link_clicks"] += r["link_clicks"]; a["clicks_all"] += r["clicks_all"]
            a["orders"] += orders; a["units"] += units; a["revenue"] += rev
        out = []
        for pi, a in acc.items():
            p = self._catalog[pi]
            ident = {k: v for k, v in p.items() if not k.startswith("_")}
            out.append({**ident, **a, "orders": round(a["orders"]), "units": round(a["units"]),
                        "attribution_model": f.attribution_model, "lookback_days": f.lookback_days})
        return out

    def daily_series(self, f: CommonFilters, product_key: str | None = None) -> list[dict[str, Any]]:
        days: dict[date, dict[str, float]] = {}
        for r in self._rows(f, product_key):
            d = days.setdefault(r["date"], dict.fromkeys(
                ("spend", "impressions", "link_clicks", "orders", "revenue"), 0.0))
            rev, orders, _ = self._attrib(f, r)
            d["spend"] += r["spend"]; d["impressions"] += r["impressions"]
            d["link_clicks"] += r["link_clicks"]; d["orders"] += orders; d["revenue"] += rev
        return [{"date": str(k), **v, "roas": v["revenue"] / v["spend"] if v["spend"] else None}
                for k, v in sorted(days.items())]

    def breakdown(self, f: CommonFilters, product_key: str, by: str) -> list[dict[str, Any]]:
        splits: dict[str, list[tuple[str | None, float]]] = {
            "campaign": [(None, 1.0)],
            "adset": [("Ad set A", 0.6), ("Ad set B", 0.4)],
            "ad": [("Carousel", 0.5), ("Single image", 0.3), ("Collection", 0.2)],
        }
        split = splits[by]
        acc: dict[int, dict[str, float]] = {}
        for r in self._rows(f, product_key):
            a = acc.setdefault(r["ci"], dict.fromkeys(("spend", "impressions", "link_clicks", "orders", "revenue"), 0.0))
            rev, orders, _ = self._attrib(f, r)
            a["spend"] += r["spend"]; a["impressions"] += r["impressions"]
            a["link_clicks"] += r["link_clicks"]; a["orders"] += orders; a["revenue"] += rev
        out: list[dict[str, Any]] = []
        for ci, a in acc.items():
            _acct, cid, cname = _CAMPAIGNS[ci]
            for label, share in split:
                vals = {k: v * share for k, v in a.items()}
                out.append({"campaign_id": cid, "name": cname if label is None else f"{cname} · {label}",
                            **vals, "roas": vals["revenue"] / vals["spend"] if vals["spend"] else None})
        return sorted(out, key=lambda x: x["spend"], reverse=True)

    def filter_options(self, f: CommonFilters) -> dict[str, list[Any]]:
        return {
            "accounts": sorted({c[0] for c in _CAMPAIGNS}),
            "campaigns": [{"id": c[1], "name": c[2], "account_id": c[0]} for c in _CAMPAIGNS],
            "categories": sorted(_CATEGORIES),
            "brands": sorted(_BRANDS),
            "availability": ["in stock", "out of stock"],
        }

    def attribution_matrix(self, f: CommonFilters) -> list[dict[str, Any]]:
        acc: dict[int, dict[str, float]] = {}
        for r in self._rows(f):
            a = acc.setdefault(r["pi"], {"spend": 0.0, **{f"revenue_{m}": 0.0 for m in _MODEL_MULT}})
            a["spend"] += r["spend"]
            for m in _MODEL_MULT:
                a[f"revenue_{m}"] += r[f"rev_{m}"]
        return [{"product_key": self._catalog[pi]["product_key"],
                 "retailer_id": self._catalog[pi]["retailer_id"],
                 "product_name": self._catalog[pi]["product_name"], **a} for pi, a in acc.items()]

    def unallocated_spend(self, f: CommonFilters) -> float | None:
        return sum(r["spend"] for r in self._rows(f)) * 0.021  # synthetic ~2.1% gap

    def unmapped_spend(self, f: CommonFilters) -> float | None:
        return sum(r["spend"] for r in self._rows(f)) * 0.009  # synthetic ~0.9%

    def data_quality(self) -> dict[str, Any]:
        pending = lambda name: {"check_name": name, "status": "pending", "observed": None,  # noqa: E731
                                "threshold": None, "details": {"note": "Awaiting integration — not yet measured"},
                                "run_at": None}
        recon = []
        for d in range(30):
            day = self.end - timedelta(days=29 - d)
            tot = sum(r["spend"] for r in self.rows if r["date"] == day)
            recon.append({"report_date": str(day), "ad_level_catalog_spend": tot,
                          "product_level_spend": tot * 0.979, "unallocated_spend": tot * 0.021})
        return {
            "checks": [pending(n) for n in (
                "meta_spend_vs_ads_manager", "utm_content_coverage", "sku_id_match_rate",
                "revenue_vs_source_of_truth", "mixpanel_purchase_event_completeness")],
            "spend_match_rate": None, "revenue_match_rate": None,
            "reconciliation": recon, "last_run": None,
        }

    def freshness(self) -> dict[str, Any]:
        return {"sources": [{"source": s, "last_run_at": None, "latest_data_date": None, "status": "pending"}
                            for s in ("meta_insights", "meta_catalog", "mixpanel", "redshift_orders")]}


@lru_cache
def get_demo_source() -> DemoDataSource:
    return DemoDataSource()
