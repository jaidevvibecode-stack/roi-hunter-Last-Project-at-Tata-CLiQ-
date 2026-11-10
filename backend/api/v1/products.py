"""
GET /products, /products/{key}, /products/{key}/trend, /products/{key}/breakdown
DESIGN §10, §11 page 2. Sort columns are whitelisted; all SQL is parameterised.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from backend.api.deps import envelope, get_filters
from backend.core.audit import audited
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.queries.common import CommonFilters, validate_sort_column
from backend.schemas.responses import (
    ProductBreakdownResponse,
    ProductDetailResponse,
    ProductsResponse,
    ProductTrendResponse,
)

router = APIRouter()
ProductKey = Annotated[str, Path(pattern="^[A-Za-z0-9_-]{1,64}$")]


@router.get("/products", response_model=ProductsResponse)
def get_products(
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
    sort: str = Query(default="spend"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=100, ge=1, le=500),
) -> dict:
    try:
        validate_sort_column(sort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with audited(user, "products", sort=sort, page=page) as a:
        res = source.products(filters, sort, order, page, page_size)
        a["rows"] = len(res["data"])
    return envelope(source.name, filters, page=page, page_size=page_size, **res)


@router.get("/products/{product_key}", response_model=ProductDetailResponse)
def get_product_detail(
    product_key: ProductKey,
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
) -> dict:
    with audited(user, "product_detail"):
        detail = source.product_detail(filters, product_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="Product not found in selected range")
    return envelope(source.name, filters, **detail)


@router.get("/products/{product_key}/trend", response_model=ProductTrendResponse)
def get_product_trend(
    product_key: ProductKey,
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
) -> dict:
    with audited(user, "product_trend"):
        trend = source.daily_series(filters, product_key)
    return envelope(source.name, filters, product_key=product_key, trend=trend)


@router.get("/products/{product_key}/breakdown", response_model=ProductBreakdownResponse)
def get_product_breakdown(
    product_key: ProductKey,
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
    by: Literal["campaign", "adset", "ad"] = Query(default="campaign"),
) -> dict:
    with audited(user, "product_breakdown", by=by):
        rows = source.breakdown(filters, product_key, by)
    return envelope(source.name, filters, product_key=product_key, by=by, breakdown=rows)
