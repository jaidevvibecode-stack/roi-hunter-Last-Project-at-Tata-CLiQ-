"""
backend/data/redshift_source.py
--------------------------------
Production data source: parameterised, read-only SQL over the dbt marts
(mart.product_performance_daily, mart.dim_product, mart.spend_reconciliation, ops.*).

STATUS: code-complete, NOT yet validated against a live Redshift cluster
(blocked on access — see README "Project Status"). Column names follow the dbt
models in /transform; adjust there first if the spikes change them.

Only values from validated sources are interpolated into SQL (the fixed
'by' column map); everything user-controlled is bound via %s parameters.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from backend.core.db import run_select
from backend.data.base import DataSource
from backend.queries.common import CommonFilters

_FROM = "mart.product_performance_daily m JOIN mart.dim_product d ON d.product_key = m.product_key"
_BY_COLUMN = {"campaign": "m.campaign_id", "adset": "m.adset_id", "ad": "m.ad_id"}
_NUMERIC = ("spend", "impressions", "link_clicks", "clicks_all", "orders", "units", "revenue")


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _num(v) for k, v in row.items()}


def _json_details(raw: Any) -> dict[str, Any]:
    """ops.dq_results.details is JSON text (or SUPER); always hand the API a dict."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else {}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except ValueError:
        return {"raw": str(raw)}


class RedshiftDataSource(DataSource):
    name = "redshift"

    def product_aggregates(self, f: CommonFilters) -> list[dict[str, Any]]:
        where, params = f.build_where_clause()
        sql = f"""
            SELECT d.product_key, d.retailer_id, d.product_name, d.brand, d.category,
                   d.availability, d.image_url,
                   SUM(m.spend) AS spend, SUM(m.impressions) AS impressions,
                   SUM(m.link_clicks) AS link_clicks, SUM(m.clicks_all) AS clicks_all,
                   SUM(m.orders) AS orders, SUM(m.units) AS units, SUM(m.revenue) AS revenue
            FROM {_FROM}
            WHERE {where}
            GROUP BY 1, 2, 3, 4, 5, 6, 7
        """  # noqa: S608  # nosec B608 — fixed fragments; user values bound via %s
        rows = [_clean(r) for r in run_select(sql, params)]
        for r in rows:
            for k in _NUMERIC:
                r[k] = r[k] or 0
            r["attribution_model"], r["lookback_days"] = f.attribution_model, f.lookback_days
        return rows

    def daily_series(self, f: CommonFilters, product_key: str | None = None) -> list[dict[str, Any]]:
        where, params = f.build_where_clause()
        if product_key:
            where += " AND m.product_key = %s"
            params = [*params, product_key]
        sql = f"""
            SELECT m.report_date AS date, SUM(m.spend) AS spend, SUM(m.impressions) AS impressions,
                   SUM(m.link_clicks) AS link_clicks, SUM(m.orders) AS orders, SUM(m.revenue) AS revenue
            FROM {_FROM} WHERE {where} GROUP BY 1 ORDER BY 1
        """  # noqa: S608  # nosec B608
        out = []
        for r in run_select(sql, params):
            r = _clean(r)
            r["date"] = str(r["date"])
            r["roas"] = r["revenue"] / r["spend"] if r["spend"] else None
            out.append(r)
        return out

    def breakdown(self, f: CommonFilters, product_key: str, by: str) -> list[dict[str, Any]]:
        col = _BY_COLUMN[by]  # KeyError => caller validated 'by' via Literal; never user text in SQL
        where, params = f.build_where_clause()
        sql = f"""
            SELECT {col} AS name, SUM(m.spend) AS spend, SUM(m.impressions) AS impressions,
                   SUM(m.link_clicks) AS link_clicks, SUM(m.orders) AS orders, SUM(m.revenue) AS revenue
            FROM {_FROM} WHERE {where} AND m.product_key = %s
            GROUP BY 1 ORDER BY spend DESC LIMIT 200
        """  # noqa: S608  # nosec B608
        out = []
        for r in run_select(sql, [*params, product_key]):
            r = _clean(r)
            r["roas"] = r["revenue"] / r["spend"] if r["spend"] else None
            out.append(r)
        return out

    def filter_options(self, f: CommonFilters) -> dict[str, list[Any]]:
        where, params = f.build_where_clause(include_model=False)
        base = f"FROM {_FROM} WHERE {where}"
        q = lambda col: [r["v"] for r in run_select(  # noqa: E731
            f"SELECT DISTINCT {col} AS v {base} AND {col} IS NOT NULL ORDER BY 1 LIMIT 1000", params)]  # noqa: S608  # nosec B608
        return {
            "accounts": q("m.account_id"),
            "campaigns": [{"id": c, "name": c, "account_id": None} for c in q("m.campaign_id")],
            "categories": q("d.category"),
            "brands": q("d.brand"),
            "availability": q("d.availability"),
        }

    def attribution_matrix(self, f: CommonFilters) -> list[dict[str, Any]]:
        where, params = f.build_where_clause(include_model=False)
        cases = ", ".join(
            f"SUM(CASE WHEN m.attribution_model = '{m.upper()}' THEN m.revenue END) AS revenue_{m}"
            for m in ("m1", "m2", "m3", "m4")
        )
        sql = f"""
            SELECT d.product_key, d.retailer_id, d.product_name,
                   SUM(CASE WHEN m.attribution_model = 'M1' THEN m.spend END) AS spend, {cases}
            FROM {_FROM} WHERE {where} GROUP BY 1, 2, 3
        """  # noqa: S608  # nosec B608
        rows = [_clean(r) for r in run_select(sql, params)]
        for r in rows:
            for k in ("spend", "revenue_m1", "revenue_m2", "revenue_m3", "revenue_m4"):
                r[k] = r[k] or 0
        return rows

    def unallocated_spend(self, f: CommonFilters) -> float | None:
        rows = run_select(
            "SELECT SUM(unallocated_spend) AS v FROM mart.spend_reconciliation "
            "WHERE report_date >= %s AND report_date <= %s",
            [f.start_date, f.end_date],
        )
        return _num(rows[0]["v"]) if rows else None

    def unmapped_spend(self, f: CommonFilters) -> float | None:
        rows = run_select(
            "SELECT SUM(total_spend - matched_spend) AS v FROM mart.id_match_report "
            "WHERE report_date >= %s AND report_date <= %s",
            [f.start_date, f.end_date],
        )
        return _num(rows[0]["v"]) if rows else None

    def data_quality(self) -> dict[str, Any]:
        checks = run_select(
            "SELECT check_name, status, observed, threshold, details, run_at FROM ops.dq_results "
            "ORDER BY run_at DESC LIMIT 50"
        )
        recon = run_select(
            "SELECT report_date, ad_level_catalog_spend, product_level_spend, unallocated_spend "
            "FROM mart.spend_reconciliation ORDER BY report_date DESC LIMIT 30"
        )
        # Aggregate over the latest 30 loaded days (a single day's rate is noisy and can be NULL).
        match = run_select(
            "SELECT SUM(matched_spend) / NULLIF(SUM(total_spend), 0) AS spend_match_rate, "
            "SUM(matched_revenue) / NULLIF(SUM(total_revenue), 0) AS revenue_match_rate "
            "FROM mart.id_match_report "
            "WHERE report_date > (SELECT MAX(report_date) - 30 FROM mart.id_match_report)"
        )
        out_checks = []
        for c in checks:
            c = _clean(c)
            c["details"] = _json_details(c["details"])
            c["run_at"] = str(c["run_at"]) if c["run_at"] else None
            out_checks.append(c)
        return {
            "checks": out_checks,
            "spend_match_rate": _num(match[0]["spend_match_rate"]) if match else None,
            "revenue_match_rate": _num(match[0]["revenue_match_rate"]) if match else None,
            "reconciliation": [{**_clean(r), "report_date": str(r["report_date"])} for r in recon],
            "last_run": out_checks[0]["run_at"] if out_checks else None,
        }

    def freshness(self) -> dict[str, Any]:
        rows = run_select(
            "SELECT source, MAX(finished_at) AS last_run_at, MAX(date_to) AS latest_data_date "
            "FROM ops.ingestion_runs WHERE status = 'success' GROUP BY 1"
        )
        return {"sources": [
            {"source": r["source"], "last_run_at": str(r["last_run_at"]),
             "latest_data_date": str(r["latest_data_date"]), "status": "ok"} for r in rows]}
