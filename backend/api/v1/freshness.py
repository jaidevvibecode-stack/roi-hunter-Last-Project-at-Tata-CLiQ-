"""GET /meta/freshness — last successful run per source."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import envelope
from backend.core.auth import require_user
from backend.data import get_source
from backend.data.base import DataSource
from backend.schemas.responses import FreshnessResponse

router = APIRouter()


@router.get("/meta/freshness", response_model=FreshnessResponse)
def get_freshness(
    source: Annotated[DataSource, Depends(get_source)],
    _user: Annotated[str, Depends(require_user)],
) -> dict:
    return envelope(source.name, None, as_of=datetime.now(timezone.utc).isoformat(), **source.freshness())
