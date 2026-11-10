"""
ingestion/jobs.py
------------------
Orchestration of ingestion jobs: fetch -> idempotent load -> checkpoint -> run record.

Design rules (DESIGN §7, plan P1.1/P1.3):
  * IDEMPOTENT: every (source, account, day) chunk is loaded with delete-then-insert in one transaction, so
    re-running a day never duplicates rows.
  * RESUMABLE: finished chunks are recorded in ops.ingestion_checkpoints and skipped on re-run (unless force).
  * ISOLATED FAILURES: one failing chunk is recorded and does not abort the other chunks; the run is marked
    PARTIAL/FAILED so schedulers and alerts can react.
  * Fetchers are injected, so everything here is unit-testable without Meta / Mixpanel.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from ingestion.common.models import (
    CheckpointStatus,
    DQResult,
    DQStatus,
    IngestionCheckpoint,
    IngestionRun,
    IngestionStatus,
    RawAdInsightRow,
    RawAdProductInsightRow,
    RawAdSnapshotRow,
    RawCatalogProductRow,
    RawMixpanelEventRow,
)
from ingestion.common.redshift import RedshiftLoader

log = logging.getLogger(__name__)


@dataclass
class JobResult:
    source: str
    run_id: str
    rows_loaded: int = 0
    chunks_done: int = 0
    chunks_skipped: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def to_tuples(records: Sequence[BaseModel]) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Pydantic rows -> (columns, tuples). dict/list fields are stored as JSON text."""
    if not records:
        return [], []
    cols = list(type(records[0]).model_fields)
    rows = []
    for r in records:
        d = r.model_dump()
        rows.append(tuple(json.dumps(d[c], default=str, sort_keys=True) if isinstance(d[c], (dict, list)) else d[c] for c in cols))
    return cols, rows


def _model_columns(model: type[BaseModel]) -> list[str]:
    return list(model.model_fields)


def _run_chunks(
    loader: RedshiftLoader,
    source: str,
    chunks: Sequence[tuple[str, str, date]],          # (account_id, chunk_key, day)
    work: Callable[[str, date], int],                 # returns rows loaded for that chunk
    date_from: date,
    date_to: date,
    force: bool,
) -> JobResult:
    run = IngestionRun(source=source, date_from=date_from, date_to=date_to)
    loader.upsert_run(run)
    res = JobResult(source=source, run_id=run.run_id)
    for account_id, chunk_key, day in chunks:
        if not force and loader.checkpoint_done(source, account_id, chunk_key):
            res.chunks_skipped += 1
            continue
        try:
            n = work(account_id, day)
            res.rows_loaded += n
            res.chunks_done += 1
            loader.upsert_checkpoint(IngestionCheckpoint(
                source=source, account_id=account_id, chunk_key=chunk_key, date=day, status=CheckpointStatus.DONE))
        except Exception as exc:  # noqa: BLE001 — isolate chunk failures, record, continue
            msg = f"{account_id}/{chunk_key}: {exc.__class__.__name__}: {exc}"
            log.error("chunk failed", extra={"source": source, "chunk": chunk_key})
            res.failures.append(msg[:500])
            loader.upsert_checkpoint(IngestionCheckpoint(
                source=source, account_id=account_id, chunk_key=chunk_key, date=day, status=CheckpointStatus.FAILED))
    run.finished_at = datetime.utcnow()
    run.rows_loaded = res.rows_loaded
    if res.ok:
        run.status = IngestionStatus.SUCCESS
    else:
        run.status = IngestionStatus.PARTIAL if res.chunks_done else IngestionStatus.FAILED
        run.error = "; ".join(res.failures)[:60000]
    loader.upsert_run(run)
    return res


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return datetime.combine(day, time.min), datetime.combine(day, time.max)


# ── Meta insights (Pull A / Pull B) ────────────────────────────────────────────

_SPLITTABLE = ("too much data", "reduce the amount of data", "timed out", "timeout", "job failed", "job skipped")


def _splittable(exc: BaseException) -> bool:
    """Errors that mean "this report is too big for one async job" (Meta gives no stable error code for it)."""
    return isinstance(exc, TimeoutError) or any(m in str(exc).lower() for m in _SPLITTABLE)


def fetch_product_with_split(
    loader: RedshiftLoader,
    account_id: str,
    day: date,
    run_id: str,
    fetch_one: Callable[..., Sequence[RawAdProductInsightRow]],
) -> list[RawAdProductInsightRow]:
    """
    Pull B for one account-day with automatic splitting (plan P1.4): whole account first; if Meta rejects the job
    as too large, retry per campaign, and per ad set inside any campaign that is still too large.
    Campaign / ad set ids come from the Pull A rows already loaded for that day (run Pull A first).
    """
    try:
        return list(fetch_one(account_id, day, run_id))
    except (RuntimeError, TimeoutError) as exc:
        if not _splittable(exc):
            raise
        log.warning("Pull B too large — splitting by campaign", extra={"account_id": account_id, "date": str(day)})
    campaigns = loader.distinct_values("raw_meta.ad_insights_daily", "campaign_id", day, account_id)
    if not campaigns:
        raise RuntimeError("Pull B too large and no Pull A rows for this day to split on — run Pull A first")
    out: list[RawAdProductInsightRow] = []
    for cid in campaigns:
        try:
            out += fetch_one(account_id, day, run_id, campaign_id=cid)
        except (RuntimeError, TimeoutError) as exc:
            if not _splittable(exc):
                raise
            adsets = loader.distinct_values("raw_meta.ad_insights_daily", "adset_id", day, account_id, ("campaign_id", cid))
            for sid in adsets:
                out += fetch_one(account_id, day, run_id, adset_id=sid)
    return out


def run_meta_insights(
    loader: RedshiftLoader,
    level: str,                                       # "ad" (Pull A) | "product" (Pull B)
    accounts: Sequence[str],
    days: Sequence[date],
    fetch: Callable[[str, date, str], Sequence[BaseModel]] | None = None,
    force: bool = False,
) -> JobResult:
    if level not in ("ad", "product"):
        raise ValueError(level)
    table, model, source = (
        ("raw_meta.ad_insights_daily", RawAdInsightRow, "meta_insights")
        if level == "ad"
        else ("raw_meta.ad_product_insights_daily", RawAdProductInsightRow, "meta_product_insights")
    )
    if fetch is None:
        from ingestion.meta import insights

        fetch = (lambda a, d, rid: insights.fetch_ad_level(a, d, rid)) if level == "ad" else \
                (lambda a, d, rid: fetch_product_with_split(loader, a, d, rid, insights.fetch_product_level))
    cols_all = _model_columns(model)
    run_id = str(uuid.uuid4())

    def work(account_id: str, day: date) -> int:
        records = list(fetch(account_id, day, run_id))
        cols, rows = to_tuples(records)
        # Even an empty day must clear stale rows (Meta restates): replace with the new (possibly empty) set.
        return loader.replace_partition(table, "date_start", day, day, cols or cols_all, rows,
                                        extra_filter=("account_id", account_id))

    chunks = [(a, str(d), d) for a in accounts for d in days]
    return _run_chunks(loader, source, chunks, work, min(days), max(days), force)


# ── Meta objects + catalog snapshots ───────────────────────────────────────────

def run_meta_objects(
    loader: RedshiftLoader,
    accounts: Sequence[str],
    snapshot_date: date,
    fetch: Callable[[str, date], Sequence[RawAdSnapshotRow]] | None = None,
) -> JobResult:
    if fetch is None:
        from ingestion.meta import objects

        fetch = lambda a, d: objects.snapshot_objects(a, d)  # noqa: E731
    from ingestion.meta.objects import audit_utm_coverage

    def work(account_id: str, day: date) -> int:
        records = list(fetch(account_id, day))
        cols, rows = to_tuples(records)
        n = loader.replace_partition("raw_meta.ads_snapshot", "snapshot_date", day, day,
                                     cols or _model_columns(RawAdSnapshotRow), rows)
        cov = audit_utm_coverage(records)
        pct = cov.get("coverage_pct")
        loader.write_dq_result(DQResult(
            check_name="utm_content_coverage",
            status=DQStatus.OK if pct == 100 else DQStatus.WARN,
            observed=None if pct is None else Decimal(str(pct)),
            threshold=Decimal("100"), details=cov))
        return n

    return _run_chunks(loader, "meta_objects", [(a, str(snapshot_date), snapshot_date) for a in accounts],
                       work, snapshot_date, snapshot_date, force=True)


def run_meta_catalog(
    loader: RedshiftLoader,
    catalog_ids: Sequence[str],
    snapshot_date: date,
    fetch: Callable[[str, date], Sequence[RawCatalogProductRow]] | None = None,
) -> JobResult:
    if fetch is None:
        from ingestion.meta import catalog

        fetch = lambda c, d: catalog.snapshot_catalog(c, d)  # noqa: E731

    def work(catalog_id: str, day: date) -> int:
        records = list(fetch(catalog_id, day))
        cols, rows = to_tuples(records)
        return loader.replace_partition("raw_meta.catalog_products", "snapshot_date", day, day,
                                        cols or _model_columns(RawCatalogProductRow), rows,
                                        extra_filter=("catalog_id", catalog_id))

    return _run_chunks(loader, "meta_catalog", [(c, str(snapshot_date), snapshot_date) for c in catalog_ids],
                       work, snapshot_date, snapshot_date, force=True)


# ── Mixpanel events ────────────────────────────────────────────────────────────

def run_mixpanel(
    loader: RedshiftLoader,
    days: Sequence[date],
    fetch: Callable[[date], list[dict[str, Any]]] | None = None,
    force: bool = False,
) -> JobResult:
    from ingestion.mixpanel.events import DEFAULT_PROPERTY_MAP, parse_events

    if fetch is None:
        from ingestion.mixpanel.client import MixpanelExportClient

        client_cm = MixpanelExportClient()
        client = client_cm.__enter__()
        fetch = lambda d: client.export_day(d, DEFAULT_PROPERTY_MAP.export_events)  # type: ignore[assignment]  # noqa: E731
    else:
        client_cm = None
    try:
        def work(_account: str, day: date) -> int:
            events: list[RawMixpanelEventRow] = parse_events(fetch(day))  # type: ignore[misc]
            cols, rows = to_tuples(events)
            lo, hi = _day_bounds(day)
            return loader.replace_partition("raw_mixpanel.events", "event_time", lo, hi,
                                            cols or _model_columns(RawMixpanelEventRow), rows)

        return _run_chunks(loader, "mixpanel", [("project", str(d), d) for d in days], work,
                           min(days), max(days), force)
    finally:
        if client_cm is not None:
            client_cm.__exit__(None, None, None)


def days_between(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end before start")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
