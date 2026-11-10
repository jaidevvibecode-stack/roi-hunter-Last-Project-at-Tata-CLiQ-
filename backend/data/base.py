"""
backend/data/base.py
---------------------
DataSource interface + shared business logic. Concrete sources only supply raw
aggregates (demo: synthetic generator, redshift: SQL over the dbt marts);
metrics, deltas, segmentation, rules and Pareto are computed once, here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import timedelta
from typing import Any, Iterator

from backend.queries.common import SORTABLE_COLUMNS, CommonFilters
from backend.services.metrics import delta_pct, derive
from backend.services.rules import build_recommendations, pareto
from backend.services.segmentation import segment_products, summarize

_SUMS = ("spend", "impressions", "link_clicks", "clicks_all", "orders", "units", "revenue")


def _enrich(row: dict[str, Any], total_spend: float) -> dict[str, Any]:
    out = {**row, **derive(row["spend"], row["impressions"], row["link_clicks"], row["orders"], row["revenue"])}
    out["spend_share"] = row["spend"] / total_spend if total_spend else None
    return out


class DataSource(ABC):
    name: str = "base"

    # ── supplied by concrete sources ──────────────────────────────────────────
    @abstractmethod
    def product_aggregates(self, f: CommonFilters) -> list[dict[str, Any]]:
        """One row per product: identity attrs + summed spend/impressions/link_clicks/clicks_all/orders/units/revenue."""

    @abstractmethod
    def daily_series(self, f: CommonFilters, product_key: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def breakdown(self, f: CommonFilters, product_key: str, by: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def filter_options(self, f: CommonFilters) -> dict[str, list[Any]]: ...

    @abstractmethod
    def attribution_matrix(self, f: CommonFilters) -> list[dict[str, Any]]:
        """Per product: spend + revenue/orders under each of M1..M4."""

    @abstractmethod
    def unallocated_spend(self, f: CommonFilters) -> float | None: ...

    @abstractmethod
    def unmapped_spend(self, f: CommonFilters) -> float | None:
        """Meta product-level spend whose product_id is NOT in the catalog/map: absent from the product table, so
        it must be reported separately or the dashboard silently under-counts spend."""

    @abstractmethod
    def data_quality(self) -> dict[str, Any]: ...

    @abstractmethod
    def freshness(self) -> dict[str, Any]: ...

    # ── shared logic ──────────────────────────────────────────────────────────
    def _enriched_products(self, f: CommonFilters) -> list[dict[str, Any]]:
        rows = self.product_aggregates(f)
        total = sum(r["spend"] for r in rows)
        return [_enrich(r, total) for r in rows]

    def _totals(self, f: CommonFilters) -> dict[str, float]:
        rows = self.product_aggregates(f)
        return {k: float(sum(r[k] for r in rows)) for k in _SUMS}

    def _prior_filters(self, f: CommonFilters) -> CommonFilters:
        span = (f.end_date - f.start_date).days + 1
        return replace(f, start_date=f.start_date - timedelta(days=span), end_date=f.start_date - timedelta(days=1))

    def products(self, f: CommonFilters, sort: str, order: str, page: int, page_size: int) -> dict[str, Any]:
        assert sort in SORTABLE_COLUMNS
        rows = self._enriched_products(f)
        reverse = order == "desc"
        # NULLs always sort last regardless of direction
        present = [r for r in rows if r.get(sort) is not None]
        missing = [r for r in rows if r.get(sort) is None]
        present.sort(key=lambda r: r[sort], reverse=reverse)
        rows = present + missing
        start = (page - 1) * page_size
        return {"data": rows[start : start + page_size], "total": len(rows)}

    def overview(self, f: CommonFilters) -> dict[str, Any]:
        cur, prior = self._totals(f), self._totals(self._prior_filters(f))
        cur_d = derive(cur["spend"], cur["impressions"], cur["link_clicks"], cur["orders"], cur["revenue"])
        pri_d = derive(prior["spend"], prior["impressions"], prior["link_clicks"], prior["orders"], prior["revenue"])
        values = {**cur, **cur_d}
        priors = {**prior, **pri_d}
        kpis = {
            k: {"value": values.get(k), "delta_pct": delta_pct(values.get(k), priors.get(k))}
            for k in ("spend", "impressions", "link_clicks", "orders", "units", "revenue",
                      "ctr", "cpm", "cpc", "roas", "cvr", "aov")
        }
        products = self._enriched_products(f)
        with_roas = [p for p in products if p["roas"] is not None and p["spend"] >= 500]
        return {
            "period": {"start": str(f.start_date), "end": str(f.end_date)},
            "kpis": kpis,
            "unallocated_spend": self.unallocated_spend(f),
            "unmapped_spend": self.unmapped_spend(f),
            "trend": self.daily_series(f),
            "top_products_by_spend": sorted(products, key=lambda p: p["spend"], reverse=True)[:8],
            "top_products_by_roas": sorted(with_roas, key=lambda p: p["roas"], reverse=True)[:8],
            "pareto_spend": pareto(products, "spend"),
            "pareto_revenue": pareto(products, "revenue"),
            "segment_summary": summarize(segment_products(products)),
            "attribution_model": f.attribution_model,
            "lookback_days": f.lookback_days,
        }

    def product_detail(self, f: CommonFilters, product_key: str) -> dict[str, Any] | None:
        rows = [p for p in self._enriched_products(f) if p["product_key"] == product_key]
        if not rows:
            return None
        return {"product": rows[0], "trend": self.daily_series(f, product_key),
                "breakdown": self.breakdown(f, product_key, "campaign")}

    def trends(self, f: CommonFilters) -> list[dict[str, Any]]:
        return self.daily_series(f)

    def segments(self, f: CommonFilters) -> dict[str, Any]:
        segmented = segment_products(self._enriched_products(f))
        return {"summary": summarize(segmented), "products": segmented}

    def recommendations(self, f: CommonFilters) -> list[dict[str, Any]]:
        return build_recommendations(segment_products(self._enriched_products(f)))

    def attribution_compare(self, f: CommonFilters, page: int, page_size: int) -> dict[str, Any]:
        rows = sorted(self.attribution_matrix(f), key=lambda r: r["spend"], reverse=True)
        for r in rows:
            for m in ("m1", "m2", "m3", "m4"):
                r[f"roas_{m}"] = r[f"revenue_{m}"] / r["spend"] if r["spend"] else None
        start = (page - 1) * page_size
        return {"data": rows[start : start + page_size], "total": len(rows)}

    def export_rows(self, f: CommonFilters, sort: str, limit: int) -> Iterator[dict[str, Any]]:
        res = self.products(f, sort, "desc", 1, limit)
        yield from res["data"]
