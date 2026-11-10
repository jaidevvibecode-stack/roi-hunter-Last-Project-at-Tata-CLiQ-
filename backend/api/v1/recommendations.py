"""GET /recommendations — rule-based suggestions. RECOMMENDATION ONLY: nothing is written to Meta."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import envelope, get_filters
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.queries.common import CommonFilters
from backend.schemas.responses import RecommendationsResponse

router = APIRouter()


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    _user: Annotated[str, Depends(require_user)],
) -> dict:
    return envelope(source.name, filters, recommendations=source.recommendations(filters),
                    write_back_enabled=False)
