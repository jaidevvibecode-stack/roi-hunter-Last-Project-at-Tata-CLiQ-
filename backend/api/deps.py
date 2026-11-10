"""Shared FastAPI dependencies: validated filters, auth, data source, response envelope."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException, Query

from backend.core.settings import get_settings
from backend.queries.common import SUPPORTED_LOOKBACK_DAYS, CommonFilters

MAX_RANGE_DAYS = 400


def get_filters(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    account_ids: list[str] = Query(default=[], alias="account_ids[]", max_length=50),
    campaign_ids: list[str] = Query(default=[], alias="campaign_ids[]", max_length=50),
    adset_ids: list[str] = Query(default=[], alias="adset_ids[]", max_length=50),
    ad_ids: list[str] = Query(default=[], alias="ad_ids[]", max_length=50),
    brands: list[str] = Query(default=[], alias="brands[]", max_length=50),
    categories: list[str] = Query(default=[], alias="categories[]", max_length=50),
    availability: list[str] = Query(default=[], alias="availability[]", max_length=5),
    attribution_model: str = Query(default="M1", pattern="^M[1-4]$"),
    lookback_days: int = Query(default=7),
    currency: str = Query(default="INR", pattern="^[A-Z]{3}$"),
    search: str = Query(default="", max_length=100),
) -> CommonFilters:
    if lookback_days not in SUPPORTED_LOOKBACK_DAYS:
        raise HTTPException(status_code=422, detail=f"lookback_days must be one of {list(SUPPORTED_LOOKBACK_DAYS)} (the marts compute only these windows)")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must be >= start_date")
    if end_date - start_date > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status_code=422, detail=f"date range limited to {MAX_RANGE_DAYS} days")
    return CommonFilters(
        start_date=start_date, end_date=end_date, account_ids=account_ids, campaign_ids=campaign_ids,
        adset_ids=adset_ids, ad_ids=ad_ids, brands=brands, categories=categories,
        availability=availability, attribution_model=attribution_model,
        lookback_days=lookback_days, currency=currency, search=search,
    )


def envelope(source_name: str, f: CommonFilters | None, **payload: Any) -> dict[str, Any]:
    """Every response states its data source — demo data can never pass as real."""
    meta: dict[str, Any] = {"data_source": source_name, "env": get_settings().env}
    if f is not None:
        meta |= {"attribution_model": f.attribution_model, "lookback_days": f.lookback_days}
    return {"meta": meta, **payload}
