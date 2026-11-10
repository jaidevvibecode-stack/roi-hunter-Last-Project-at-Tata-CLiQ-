"""GET /data-quality — DQ checks, match rates, spend reconciliation."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import envelope
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.schemas.responses import DataQualityResponse

router = APIRouter()


@router.get("/data-quality", response_model=DataQualityResponse)
def get_data_quality(
    source: Annotated[DataSource, Depends(get_source)],
    _user: Annotated[str, Depends(require_user)],
) -> dict:
    return envelope(source.name, None, **source.data_quality())
