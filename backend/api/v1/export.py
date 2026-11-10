"""GET /export/products.csv — streaming CSV. Cells are neutralised against spreadsheet formula injection."""
from __future__ import annotations

import csv
import io
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.api.deps import get_filters
from backend.core.audit import audited
from backend.core.auth import require_user
from backend.core.settings import get_settings
from backend.data import get_source
from backend.data.base import DataSource
from backend.queries.common import CommonFilters, validate_sort_column

router = APIRouter()

HEADERS = [
    "product_key", "retailer_id", "product_name", "brand", "category", "availability",
    "spend", "impressions", "link_clicks", "ctr", "cpm", "cost_per_impression",
    "cpc", "orders", "units", "revenue", "roas", "spend_share",
    "attribution_model", "lookback_days",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    """Prefix risky strings with an apostrophe so Excel/Sheets never evaluate them as formulas."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return "" if value is None else value


def stream_csv(rows: Iterator[dict[str, Any]]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    yield buf.getvalue()
    for row in rows:
        buf.seek(0)
        buf.truncate()
        writer.writerow([safe_cell(row.get(h)) for h in HEADERS])
        yield buf.getvalue()


@router.get(
    "/export/products.csv",
    response_class=StreamingResponse,
    responses={200: {"description": "CSV of the current filtered product table", "content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_products_csv(
    filters: Annotated[CommonFilters, Depends(get_filters)],
    source: Annotated[DataSource, Depends(get_source)],
    user: Annotated[str, Depends(require_user)],
    sort: str = Query(default="spend"),
) -> StreamingResponse:
    try:
        validate_sort_column(sort)
    except ValueError:
        sort = "spend"
    limit = get_settings().export_max_rows
    with audited(user, "export_products_csv", limit=limit):
        rows = source.export_rows(filters, sort, limit)
        return StreamingResponse(
            stream_csv(rows), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=products.csv"},
        )
