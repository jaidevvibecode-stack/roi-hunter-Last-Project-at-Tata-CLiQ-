"""
backend/schemas/responses.py
-----------------------------
Response models for EVERY endpoint. They (1) validate what the API returns, (2) define the OpenAPI schema, and
(3) are the single source for the frontend's TypeScript types (`npm run gen:api` -> frontend/lib/api-types.ts).
Money/ratio fields are floats in JSON; ratios are NULL (never 0/inf) when undefined.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Meta(Strict):
    data_source: Literal["demo", "redshift"]
    env: str
    attribution_model: str | None = None
    lookback_days: int | None = None


class Health(Strict):
    status: str
    data_source: Literal["demo", "redshift"]


class Metric(Strict):
    value: float | None = None
    delta_pct: float | None = Field(default=None, description="(current - prior) / prior * 100")


class KpiSet(Strict):
    spend: Metric
    impressions: Metric
    link_clicks: Metric
    orders: Metric
    units: Metric
    revenue: Metric
    ctr: Metric
    cpm: Metric
    cpc: Metric
    roas: Metric
    cvr: Metric
    aov: Metric


class TrendPoint(Strict):
    date: str
    spend: float
    impressions: float
    link_clicks: float
    orders: float
    revenue: float
    roas: float | None = None


class Product(Strict):
    product_key: str
    retailer_id: str
    product_name: str
    brand: str | None = None
    category: str | None = None
    availability: str | None = None
    image_url: str | None = None
    spend: float
    impressions: float
    link_clicks: float
    clicks_all: float
    orders: float
    units: float
    revenue: float
    ctr: float | None = None
    cpm: float | None = None
    cost_per_impression: float | None = None
    cpc: float | None = None
    roas: float | None = None
    cvr: float | None = None
    aov: float | None = None
    spend_share: float | None = None
    attribution_model: str
    lookback_days: int
    segment: str | None = None


class ParetoPoint(Strict):
    sku_pct: float
    cum_share: float


class Pareto(Strict):
    curve: list[ParetoPoint]
    skus_for_80pct: int | None = None
    share_of_skus_for_80pct: float | None = None


class SegmentRow(Strict):
    segment: str
    products: int
    spend: float
    revenue: float
    roas: float | None = None
    spend_share: float


class Period(Strict):
    start: str
    end: str


class OverviewResponse(Strict):
    meta: Meta
    period: Period
    kpis: KpiSet
    unallocated_spend: float | None = None
    unmapped_spend: float | None = Field(default=None, description="Product-level spend whose product_id is not in the catalog (not in the product table)")
    trend: list[TrendPoint]
    top_products_by_spend: list[Product]
    top_products_by_roas: list[Product]
    pareto_spend: Pareto
    pareto_revenue: Pareto
    segment_summary: list[SegmentRow]
    attribution_model: str
    lookback_days: int


class ProductsResponse(Strict):
    meta: Meta
    page: int
    page_size: int
    total: int
    data: list[Product]


class BreakdownRow(Strict):
    name: str
    campaign_id: str | None = None
    spend: float
    impressions: float
    link_clicks: float
    orders: float
    revenue: float
    roas: float | None = None


class ProductDetailResponse(Strict):
    meta: Meta
    product: Product
    trend: list[TrendPoint]
    breakdown: list[BreakdownRow]


class ProductTrendResponse(Strict):
    meta: Meta
    product_key: str
    trend: list[TrendPoint]


class ProductBreakdownResponse(Strict):
    meta: Meta
    product_key: str
    by: Literal["campaign", "adset", "ad"]
    breakdown: list[BreakdownRow]


class TrendsResponse(Strict):
    meta: Meta
    series: list[TrendPoint]


class CampaignOption(Strict):
    id: str
    name: str
    account_id: str | None = None


class FilterOptionsResponse(Strict):
    meta: Meta
    accounts: list[str]
    campaigns: list[CampaignOption]
    categories: list[str]
    brands: list[str]
    availability: list[str]


class AttributionRow(Strict):
    product_key: str
    retailer_id: str
    product_name: str
    spend: float
    revenue_m1: float
    revenue_m2: float
    revenue_m3: float
    revenue_m4: float
    roas_m1: float | None = None
    roas_m2: float | None = None
    roas_m3: float | None = None
    roas_m4: float | None = None


class AttributionCompareResponse(Strict):
    meta: Meta
    page: int
    page_size: int
    total: int
    data: list[AttributionRow]


class SegmentsResponse(Strict):
    meta: Meta
    summary: list[SegmentRow]
    products: list[Product]


class TopProduct(Strict):
    product_key: str
    retailer_id: str
    product_name: str
    spend: float
    roas: float | None = None


class Recommendation(Strict):
    rule_id: str
    severity: Literal["critical", "opportunity", "info"]
    action: str
    reason: str
    product_count: int
    spend_affected: float
    revenue_affected: float
    top_products: list[TopProduct]
    retailer_ids: list[str]


class RecommendationsResponse(Strict):
    meta: Meta
    recommendations: list[Recommendation]
    write_back_enabled: Literal[False] = Field(description="Always false: this system never writes to ad platforms")


class DQCheck(Strict):
    check_name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    details: dict[str, Any]
    run_at: str | None = None


class ReconciliationRow(Strict):
    report_date: str
    ad_level_catalog_spend: float
    product_level_spend: float
    unallocated_spend: float


class DataQualityResponse(Strict):
    meta: Meta
    checks: list[DQCheck]
    spend_match_rate: float | None = None
    revenue_match_rate: float | None = None
    reconciliation: list[ReconciliationRow]
    last_run: str | None = None


class SourceFreshness(Strict):
    source: str
    last_run_at: str | None = None
    latest_data_date: str | None = None
    status: str


class FreshnessResponse(Strict):
    meta: Meta
    as_of: str
    sources: list[SourceFreshness]
