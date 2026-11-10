"""
ingestion/meta/catalog.py
--------------------------
Snapshot Meta catalog products and product sets daily.
DESIGN §7.3 and §8.1 raw_meta.catalog_products.

Paginates /{catalog_id}/products with limit=500.
Stores a full daily snapshot (snapshot_date) — dbt dedupes to latest.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Iterator

from facebook_business.adobjects.productcatalog import ProductCatalog

from ingestion.common.models import RawCatalogProductRow
from ingestion.common.retry import retry_meta
from ingestion.meta.client import get_api

log = logging.getLogger(__name__)

CATALOG_PRODUCT_FIELDS = [
    "id",
    "retailer_id",
    "retailer_product_group_id",
    "name",
    "brand",
    "category",
    "product_type",
    "price",
    "sale_price",
    "currency",
    "availability",
    "url",
    "image_url",
    "custom_label_0",
    "custom_label_1",
    "custom_label_2",
    "custom_label_3",
    "custom_label_4",
]

PAGE_LIMIT = 500


@retry_meta()
def _get_catalog_product_page(catalog_id: str, after_cursor: str | None) -> dict[str, Any]:
    """Fetch one page of catalog products. Returns the raw JSON dict."""
    get_api()  # ensure initialised
    params: dict[str, Any] = {
        "fields": ",".join(CATALOG_PRODUCT_FIELDS),
        "limit": PAGE_LIMIT,
    }
    if after_cursor:
        params["after"] = after_cursor

    catalog = ProductCatalog(catalog_id)
    result = catalog.get_products(params=params)
    return result  # type: ignore[return-value]


def iter_catalog_products(catalog_id: str) -> Iterator[dict[str, Any]]:
    """Yield every product in the catalog, handling pagination."""
    after_cursor: str | None = None
    page_num = 0
    while True:
        page = _get_catalog_product_page(catalog_id, after_cursor)
        items = list(page)
        if not items:
            break
        page_num += 1
        log.debug(
            "Catalog page fetched",
            extra={"catalog_id": catalog_id, "page": page_num, "count": len(items)},
        )
        for item in items:
            yield dict(item)
        # Pagination cursor
        paging = getattr(page, "paging", None) or {}
        cursors = paging.get("cursors", {})
        after_cursor = cursors.get("after")
        if not paging.get("next") and not after_cursor:
            break
        if not after_cursor:
            # A `next` link without an `after` cursor cannot be followed; re-requesting page 1 would loop forever.
            log.warning("catalog pagination: next link without cursor — stopping", extra={"catalog_id": catalog_id})
            break


def snapshot_catalog(
    catalog_id: str,
    snapshot_date: date | None = None,
    run_id: str | None = None,
) -> list[RawCatalogProductRow]:
    """
    Full snapshot of one catalog on snapshot_date (defaults to today).
    Returns list of RawCatalogProductRow ready for storage.
    """
    snapshot_date = snapshot_date or date.today()
    run_id = run_id or str(uuid.uuid4())

    rows: list[RawCatalogProductRow] = []
    for item in iter_catalog_products(catalog_id):
        rows.append(
            RawCatalogProductRow(
                snapshot_date=snapshot_date,
                catalog_id=catalog_id,
                id=item.get("id", ""),
                retailer_id=item.get("retailer_id", ""),
                retailer_product_group_id=item.get("retailer_product_group_id", ""),
                name=item.get("name", ""),
                brand=item.get("brand", ""),
                category=item.get("category", ""),
                product_type=item.get("product_type", ""),
                price=item.get("price", ""),
                sale_price=item.get("sale_price", ""),
                currency=item.get("currency", ""),
                availability=item.get("availability", ""),
                url=item.get("url", ""),
                image_url=item.get("image_url", ""),
                custom_label_0=item.get("custom_label_0", ""),
                custom_label_1=item.get("custom_label_1", ""),
                custom_label_2=item.get("custom_label_2", ""),
                custom_label_3=item.get("custom_label_3", ""),
                custom_label_4=item.get("custom_label_4", ""),
                raw=item,
            )
        )

    log.info(
        "Catalog snapshot complete",
        extra={"catalog_id": catalog_id, "date": str(snapshot_date), "products": len(rows)},
    )
    return rows
