"""
backend/queries/common.py
--------------------------
Shared query utilities: common filter builder, sort whitelist, parameterised SQL.
DESIGN §10 — parameterised SQL only; whitelist sort columns; no string concatenation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Lookback windows the marts actually compute (dbt var `default_lookback_days`; a test keeps them in sync).
# Other windows would silently return empty/zero revenue, so the API refuses them instead of faking it.
SUPPORTED_LOOKBACK_DAYS: tuple[int, ...] = (7,)

# ── Sort column whitelist ──────────────────────────────────────────────────────
# Only columns in this set may be used in ORDER BY to prevent SQL injection.
SORTABLE_COLUMNS: frozenset[str] = frozenset({
    "spend", "impressions", "link_clicks", "clicks_all",
    "ctr", "cpm", "cost_per_impression", "cpc",
    "orders", "units", "revenue", "roas", "spend_share",
    "product_name", "brand", "retailer_id", "report_date",
})


def validate_sort_column(column: str) -> str:
    """Raise ValueError if column is not in the whitelist."""
    if column not in SORTABLE_COLUMNS:
        raise ValueError(
            f"Invalid sort column: {column!r}. "
            f"Allowed: {sorted(SORTABLE_COLUMNS)}"
        )
    return column


@dataclass
class CommonFilters:
    """Common query filter parameters shared across all endpoints."""

    start_date: date
    end_date: date
    compare_start: date | None = None
    compare_end: date | None = None
    account_ids: list[str] = field(default_factory=list)
    campaign_ids: list[str] = field(default_factory=list)
    adset_ids: list[str] = field(default_factory=list)
    ad_ids: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    availability: list[str] = field(default_factory=list)
    attribution_model: str = "M1"
    lookback_days: int = 7
    currency: str = "INR"

    search: str = ""

    def build_where_clause(self, include_model: bool = True) -> tuple[str, list[Any]]:
        """
        Build a parameterised WHERE clause fragment and its bound parameters.
        Returns (sql_fragment, params_list).
        Uses %s placeholders compatible with redshift_connector.
        """
        conditions: list[str] = ["report_date >= %s", "report_date <= %s", "lookback_days = %s"]
        params: list[Any] = [self.start_date, self.end_date, self.lookback_days]
        if include_model:
            conditions.append("attribution_model = %s")
            params.append(self.attribution_model)

        if self.account_ids:
            placeholders = ", ".join(["%s"] * len(self.account_ids))
            conditions.append(f"account_id IN ({placeholders})")
            params.extend(self.account_ids)

        if self.campaign_ids:
            placeholders = ", ".join(["%s"] * len(self.campaign_ids))
            conditions.append(f"campaign_id IN ({placeholders})")
            params.extend(self.campaign_ids)

        if self.adset_ids:
            placeholders = ", ".join(["%s"] * len(self.adset_ids))
            conditions.append(f"adset_id IN ({placeholders})")
            params.extend(self.adset_ids)

        if self.ad_ids:
            placeholders = ", ".join(["%s"] * len(self.ad_ids))
            conditions.append(f"ad_id IN ({placeholders})")
            params.extend(self.ad_ids)

        if self.categories:
            placeholders = ", ".join(["%s"] * len(self.categories))
            conditions.append(f"lower(category) IN ({placeholders})")
            params.extend([c.lower() for c in self.categories])

        if self.search:
            # Escape LIKE wildcards so user input is matched literally
            esc = self.search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(lower(product_name) LIKE %s OR lower(retailer_id) LIKE %s)")
            params.extend([f"%{esc}%", f"%{esc}%"])

        if self.brands:
            placeholders = ", ".join(["%s"] * len(self.brands))
            conditions.append(f"lower(brand) IN ({placeholders})")
            params.extend([b.lower() for b in self.brands])

        if self.availability:
            placeholders = ", ".join(["%s"] * len(self.availability))
            conditions.append(f"availability IN ({placeholders})")
            params.extend(self.availability)

        return " AND ".join(conditions), params
