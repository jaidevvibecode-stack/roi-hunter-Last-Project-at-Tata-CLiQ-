"""
ingestion/common/models.py
---------------------------
Pydantic models for raw ingestion records, ops schema rows, and shared types.
Money = Decimal(18,6). Dates = UTC datetime / date.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────────────────────────────────────

class IngestionStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class CheckpointStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class DQStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


# ── Ops records ───────────────────────────────────────────────────────────────

class IngestionRun(BaseModel):
    """Maps to ops.ingestion_runs."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str  # e.g. "meta_insights", "meta_catalog", "mixpanel"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: IngestionStatus = IngestionStatus.RUNNING
    date_from: date | None = None
    date_to: date | None = None
    rows_loaded: int = 0
    error: str | None = None


class IngestionCheckpoint(BaseModel):
    """Maps to ops.ingestion_checkpoints — tracks resumable progress."""

    source: str
    account_id: str
    chunk_key: str  # e.g. "2024-01-15" or "2024-01-15|campaign_123"
    date: date
    status: CheckpointStatus = CheckpointStatus.PENDING
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DQResult(BaseModel):
    """Maps to ops.dq_results."""

    check_name: str
    run_at: datetime = Field(default_factory=datetime.utcnow)
    status: DQStatus
    observed: Decimal | None = None
    threshold: Decimal | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ── Raw Meta records ──────────────────────────────────────────────────────────

class RawAdInsightRow(BaseModel):
    """One row of raw_meta.ad_insights_daily (Pull A)."""

    account_id: str
    date_start: date
    campaign_id: str
    adset_id: str
    ad_id: str
    campaign_name: str = ""
    adset_name: str = ""
    ad_name: str = ""
    account_currency: str = ""
    spend: Decimal = Decimal("0")
    impressions: int = 0
    clicks: int = 0
    inline_link_clicks: int = 0
    reach: int = 0
    frequency: Decimal = Decimal("0")
    actions: list[dict[str, Any]] = Field(default_factory=list)
    action_values: list[dict[str, Any]] = Field(default_factory=list)
    purchase_roas: list[dict[str, Any]] = Field(default_factory=list)
    attribution_setting: str = ""
    api_version: str = ""
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    run_id: str = ""


class RawAdProductInsightRow(BaseModel):
    """One row of raw_meta.ad_product_insights_daily (Pull B — product breakdown)."""

    account_id: str
    date_start: date
    campaign_id: str
    adset_id: str
    ad_id: str
    product_id_raw: str  # exactly as returned by Meta — do NOT normalise here
    spend: Decimal = Decimal("0")
    impressions: int = 0
    clicks: int = 0
    inline_link_clicks: int = 0
    api_version: str = ""
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    run_id: str = ""


class RawCatalogProductRow(BaseModel):
    """One row of raw_meta.catalog_products."""

    snapshot_date: date
    catalog_id: str
    id: str  # Meta's internal catalog item ID
    retailer_id: str = ""  # advertiser's SKU
    retailer_product_group_id: str = ""
    name: str = ""
    brand: str = ""
    category: str = ""
    product_type: str = ""
    price: str = ""  # stored as string, e.g. "999 INR"
    sale_price: str = ""
    currency: str = ""
    availability: str = ""
    url: str = ""
    image_url: str = ""
    custom_label_0: str = ""
    custom_label_1: str = ""
    custom_label_2: str = ""
    custom_label_3: str = ""
    custom_label_4: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)  # full raw response
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class RawAdSnapshotRow(BaseModel):
    """One row of raw_meta.ads_snapshot."""

    snapshot_date: date
    level: str  # "campaign" | "adset" | "ad"
    id: str
    parent_id: str = ""
    name: str = ""
    status: str = ""
    effective_status: str = ""
    objective: str = ""
    product_set_id: str = ""
    url_tags: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


# ── Raw Mixpanel records ──────────────────────────────────────────────────────

class RawMixpanelEventRow(BaseModel):
    """One row of raw_mixpanel.events."""

    event: str
    event_time: datetime
    distinct_id: str  # NOTE: do not log this; treated as PII-adjacent
    insert_id: str  # $insert_id for deduplication
    properties: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
