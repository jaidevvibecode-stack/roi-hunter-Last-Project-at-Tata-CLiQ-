"""
ingestion/meta/insights.py
---------------------------
Meta Insights ingestion — Pull A (ad-level) and Pull B (ad × product breakdown).

Pull A: async report per (account, date), level=ad, no breakdown.
Pull B: async report per (account, date), level=ad, breakdowns=product_id.

Both use the async Insights flow:
  POST /act_{id}/insights  → report_run_id
  GET  /{report_run_id}    → poll async_status == "Job Complete"
  GET  /{report_run_id}/insights → paginate results

Chunking strategy (DESIGN §7.1):
  - If a report fails due to size/timeout → split by campaign, then by ad set.
  - Concurrency capped at MetaSettings.max_concurrent_jobs per account.
  - Rate-limit headers checked after every poll cycle.

Restatement windows:
  - Daily run: re-pull trailing 7 days.
  - Weekly run: re-pull trailing 28 days.
  - Backfill CLI: arbitrary range, chunked, resumable via checkpoints.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterator

from facebook_business.adobjects.adreportrun import AdReportRun

from ingestion.common.config import MetaSettings, get_settings
from ingestion.common.models import RawAdInsightRow, RawAdProductInsightRow
from ingestion.common.retry import retry_meta
from ingestion.meta.client import get_ad_account

log = logging.getLogger(__name__)

# ── Field lists (DESIGN §7.1) ─────────────────────────────────────────────────

PULL_A_FIELDS = [
    "account_id", "account_currency",
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "date_start",
    "spend", "impressions", "clicks", "inline_link_clicks",
    "reach", "frequency",
    "actions", "action_values", "purchase_roas",
]

PULL_B_FIELDS = [
    "account_id",
    "campaign_id", "adset_id", "ad_id",
    "date_start",
    "spend", "impressions", "clicks", "inline_link_clicks",
    # Include actions/action_values only to verify they're absent at product level (spike P0.3)
    "actions", "action_values",
]

POLL_INITIAL_DELAY_S = 2  # most small day-reports finish quickly: look early instead of waiting a full interval
POLL_INTERVAL_S = 10   # seconds between later poll attempts
POLL_MAX_ATTEMPTS = 60 # 60 × 10s = 10 minutes max wait


# ── Async report helpers ───────────────────────────────────────────────────────

def windows_of(meta: MetaSettings) -> list[str]:
    return [w.strip() for w in meta.attribution_windows.split(",") if w.strip()]


def attribution_label(meta: MetaSettings) -> str:
    """What conversion-attribution setting a pull used — stored with every row so M3/ROAS can be reconciled."""
    if meta.use_unified_attribution:
        return "unified (ad account setting)"
    w = windows_of(meta)
    return "windows:" + ",".join(w) if w else "api-default"


def _build_params(
    date_str: str,
    use_product_breakdown: bool,
    campaign_id: str | None = None,
    adset_id: str | None = None,
) -> dict[str, Any]:
    meta = get_settings().meta
    params: dict[str, Any] = {
        "level": "ad",
        "time_increment": "1",
        "time_range": {"since": date_str, "until": date_str},
        "use_unified_attribution_setting": meta.use_unified_attribution,
        "action_report_time": "impression",
        "fields": PULL_B_FIELDS if use_product_breakdown else PULL_A_FIELDS,
    }
    if not meta.use_unified_attribution and windows_of(meta):
        params["action_attribution_windows"] = windows_of(meta)
    if use_product_breakdown:
        params["breakdowns"] = ["product_id"]
    filtering: list[dict[str, Any]] = []
    if campaign_id:
        filtering.append({"field": "campaign.id", "operator": "EQUAL", "value": campaign_id})
    if adset_id:
        filtering.append({"field": "adset.id", "operator": "EQUAL", "value": adset_id})
    if filtering:
        params["filtering"] = filtering
    return params


@retry_meta()
def _create_async_report(
    account_id: str,
    params: dict[str, Any],
) -> str:
    """Submit an async report job; return report_run_id."""
    acct = get_ad_account(account_id)
    report_run = acct.create_ad_report_run(params=params)
    return str(report_run["id"])


def _poll_until_complete(
    report_run_id: str,
    account_id: str,
) -> AdReportRun:
    """Block until the async report is complete or raise on permanent failure."""
    for attempt in range(POLL_MAX_ATTEMPTS):
        time.sleep(POLL_INITIAL_DELAY_S if attempt == 0 else POLL_INTERVAL_S)
        report_run = AdReportRun(report_run_id)
        report_run.api_get(fields=["async_status", "async_percent_completion"])
        status: str = report_run.get("async_status", "")
        pct: int = report_run.get("async_percent_completion", 0)

        log.debug(
            "Poll async report",
            extra={
                "report_run_id": report_run_id,
                "account_id": account_id,
                "status": status,
                "pct": pct,
                "attempt": attempt,
            },
        )

        if status == "Job Complete":
            return report_run
        if status in ("Job Failed", "Job Skipped"):
            raise RuntimeError(
                f"Async report {report_run_id} ended with status={status!r}"
            )

    raise TimeoutError(
        f"Async report {report_run_id} did not complete after "
        f"{POLL_MAX_ATTEMPTS * POLL_INTERVAL_S}s"
    )


def _paginate_results(
    report_run: AdReportRun,
    account_id: str,
) -> Iterator[dict[str, Any]]:
    """Paginate through completed report results; yield one row at a time."""
    cursor = report_run.get_insights()
    while cursor:
        # The SDK cursor may expose response headers for rate-limit monitoring
        # (verified in spike; add header extraction here once we know the cursor API)
        for row in cursor:
            yield dict(row)
        if not cursor.load_next_page():
            break


# ── Pull A ─────────────────────────────────────────────────────────────────────

def fetch_ad_level(
    account_id: str,
    report_date: date,
    run_id: str | None = None,
) -> list[RawAdInsightRow]:
    """
    Pull A: ad-level daily insights for one account and one date.
    Returns a list of RawAdInsightRow ready for storage.
    """
    run_id = run_id or str(uuid.uuid4())
    api_version = get_settings().meta.api_version
    date_str = str(report_date)

    params = _build_params(date_str, use_product_breakdown=False)
    log.info(
        "Pull A: submitting async report",
        extra={"account_id": account_id, "date": date_str, "run_id": run_id},
    )
    report_run_id = _create_async_report(account_id, params)
    report_run = _poll_until_complete(report_run_id, account_id)

    rows: list[RawAdInsightRow] = []
    for raw in _paginate_results(report_run, account_id):
        rows.append(
            RawAdInsightRow(
                account_id=raw.get("account_id", account_id),
                date_start=date.fromisoformat(raw["date_start"]),
                campaign_id=raw.get("campaign_id", ""),
                adset_id=raw.get("adset_id", ""),
                ad_id=raw.get("ad_id", ""),
                campaign_name=raw.get("campaign_name", ""),
                adset_name=raw.get("adset_name", ""),
                ad_name=raw.get("ad_name", ""),
                account_currency=raw.get("account_currency", ""),
                spend=Decimal(raw.get("spend", "0") or "0"),
                impressions=int(raw.get("impressions", 0) or 0),
                clicks=int(raw.get("clicks", 0) or 0),
                inline_link_clicks=int(raw.get("inline_link_clicks", 0) or 0),
                reach=int(raw.get("reach", 0) or 0),
                frequency=Decimal(raw.get("frequency", "0") or "0"),
                actions=raw.get("actions", []),
                action_values=raw.get("action_values", []),
                purchase_roas=raw.get("purchase_roas", []),
                attribution_setting=attribution_label(get_settings().meta),
                api_version=api_version,
                run_id=run_id,
            )
        )

    log.info(
        "Pull A: complete",
        extra={"account_id": account_id, "date": date_str, "rows": len(rows), "run_id": run_id},
    )
    return rows


# ── Pull B ─────────────────────────────────────────────────────────────────────

def fetch_product_level(
    account_id: str,
    report_date: date,
    run_id: str | None = None,
    campaign_id: str | None = None,
    adset_id: str | None = None,
) -> list[RawAdProductInsightRow]:
    """
    Pull B: ad × product daily insights for one account and one date.
    Pass campaign_id/adset_id to narrow the scope on retry (auto-split strategy).
    """
    run_id = run_id or str(uuid.uuid4())
    api_version = get_settings().meta.api_version
    date_str = str(report_date)

    params = _build_params(
        date_str,
        use_product_breakdown=True,
        campaign_id=campaign_id,
        adset_id=adset_id,
    )
    log.info(
        "Pull B: submitting async report",
        extra={
            "account_id": account_id,
            "date": date_str,
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "run_id": run_id,
        },
    )

    try:
        report_run_id = _create_async_report(account_id, params)
        report_run = _poll_until_complete(report_run_id, account_id)
    except RuntimeError as exc:
        if "too much data" in str(exc).lower() or "timeout" in str(exc).lower():
            log.warning(
                "Pull B report too large — auto-split required",
                extra={"account_id": account_id, "date": date_str},
            )
            # Callers should implement campaign/adset-level split and re-call
            raise
        raise

    rows: list[RawAdProductInsightRow] = []
    for raw in _paginate_results(report_run, account_id):
        rows.append(
            RawAdProductInsightRow(
                account_id=raw.get("account_id", account_id),
                date_start=date.fromisoformat(raw["date_start"]),
                campaign_id=raw.get("campaign_id", ""),
                adset_id=raw.get("adset_id", ""),
                ad_id=raw.get("ad_id", ""),
                product_id_raw=raw.get("product_id", ""),  # exact value — field name TBD in spike
                spend=Decimal(raw.get("spend", "0") or "0"),
                impressions=int(raw.get("impressions", 0) or 0),
                clicks=int(raw.get("clicks", 0) or 0),
                inline_link_clicks=int(raw.get("inline_link_clicks", 0) or 0),
                api_version=api_version,
                run_id=run_id,
            )
        )

    log.info(
        "Pull B: complete",
        extra={"account_id": account_id, "date": date_str, "rows": len(rows), "run_id": run_id},
    )
    return rows


# ── Date range helpers ─────────────────────────────────────────────────────────

def trailing_dates(n: int) -> list[date]:
    """Return the last n calendar dates (yesterday to n days ago)."""
    yesterday = date.today() - timedelta(days=1)
    return [yesterday - timedelta(days=i) for i in range(n)]


def date_range(start: date, end: date) -> list[date]:
    """Return all dates from start to end inclusive."""
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]
