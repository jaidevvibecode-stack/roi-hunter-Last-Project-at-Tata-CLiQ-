"""GET /overview — KPI totals with period-over-period deltas, trend, Pareto, segments."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import envelope, get_filters
from backend.core.audit import audited
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.queries.common import CommonFilters
from backend.schemas.responses import OverviewResponse

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
) -> dict:
    with audited(user, "overview", start=filters.start_date, end=filters.end_date) as a:
        data = source.overview(filters)
        a["rows"] = len(data["trend"])
    return envelope(source.name, filters, **data)
