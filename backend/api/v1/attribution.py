"""GET /attribution/compare — per-product ROAS under all attribution models (M1–M4)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import envelope, get_filters
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.queries.common import CommonFilters
from backend.schemas.responses import AttributionCompareResponse

router = APIRouter()


@router.get("/attribution/compare", response_model=AttributionCompareResponse)
def get_attribution_compare(
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    _user: Annotated[str, Depends(require_user)],
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    res = source.attribution_compare(filters, page, page_size)
    return envelope(source.name, filters, page=page, page_size=page_size, **res)
