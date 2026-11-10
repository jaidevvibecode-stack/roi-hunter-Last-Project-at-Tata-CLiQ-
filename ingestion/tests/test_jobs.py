"""Ingestion orchestration against a real (Postgres) database: idempotency, checkpoints, failure isolation."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import psycopg2
import pytest

from ingestion.common.models import (
    RawAdInsightRow,
    RawAdProductInsightRow,
    RawCatalogProductRow,
    RawMixpanelEventRow,
)
from ingestion.common.redshift import RedshiftLoader
from ingestion.jobs import run_meta_catalog, run_meta_insights, run_mixpanel, to_tuples
from ingestion.testing.fixtures import dsn, load

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    try:
        c = psycopg2.connect(dsn(), connect_timeout=3)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres stand-in: {exc.__class__.__name__}")
    load(c, {"raw_meta.ad_insights_daily": [], "raw_meta.ad_product_insights_daily": [],
             "raw_meta.catalog_products": [], "raw_mixpanel.events": []})
    with c.cursor() as cur:
        for t in ("ingestion_runs", "ingestion_checkpoints", "dq_results"):
            cur.execute(f"TRUNCATE ops.{t}")  # noqa: S608  # nosec B608
    c.commit()
    yield c
    c.close()


def count(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def ad_rows(day: date, n: int = 2, spend: str = "10") -> list[RawAdInsightRow]:
    return [RawAdInsightRow(account_id="act_1", date_start=day, campaign_id="c", adset_id="s", ad_id=f"ad{i}",
                            spend=Decimal(spend), impressions=100, actions=[{"action_type": "purchase", "value": "1"}])
            for i in range(n)]


def test_reload_same_day_is_idempotent_and_restatement_wins(conn):
    loader = RedshiftLoader(conn)
    day = date(2026, 3, 1)
    run_meta_insights(loader, "ad", ["act_1"], [day], fetch=lambda a, d, r: ad_rows(d, 2, "10"))
    assert count(conn, "select count(*) from raw_meta.ad_insights_daily") == 2
    # Meta restates: same day re-pulled with different numbers and FEWER rows -> old rows must be gone
    run_meta_insights(loader, "ad", ["act_1"], [day], fetch=lambda a, d, r: ad_rows(d, 1, "99"), force=True)
    assert count(conn, "select count(*) from raw_meta.ad_insights_daily") == 1
    assert count(conn, "select spend from raw_meta.ad_insights_daily") == 99


def test_empty_day_clears_stale_rows(conn):
    loader = RedshiftLoader(conn)
    day = date(2026, 3, 1)
    run_meta_insights(loader, "ad", ["act_1"], [day], fetch=lambda a, d, r: ad_rows(d))
    run_meta_insights(loader, "ad", ["act_1"], [day], fetch=lambda a, d, r: [], force=True)
    assert count(conn, "select count(*) from raw_meta.ad_insights_daily") == 0


def test_partition_replace_is_scoped_to_account(conn):
    loader = RedshiftLoader(conn)
    day = date(2026, 3, 1)
    run_meta_insights(loader, "ad", ["act_1", "act_2"], [day], fetch=lambda a, d, r: [
        r_.model_copy(update={"account_id": a}) for r_ in ad_rows(d, 1)])
    run_meta_insights(loader, "ad", ["act_1"], [day], fetch=lambda a, d, r: [], force=True)
    assert count(conn, "select count(*) from raw_meta.ad_insights_daily where account_id='act_2'") == 1


def test_checkpoints_make_runs_resumable(conn):
    loader = RedshiftLoader(conn)
    days = [date(2026, 3, 1), date(2026, 3, 2)]
    calls: list[date] = []

    def fetch(a, d, r):
        calls.append(d)
        return ad_rows(d, 1)

    first = run_meta_insights(loader, "ad", ["act_1"], days, fetch=fetch)
    assert first.chunks_done == 2 and first.ok
    second = run_meta_insights(loader, "ad", ["act_1"], days, fetch=fetch)
    assert second.chunks_skipped == 2 and second.chunks_done == 0 and len(calls) == 2   # nothing re-fetched
    third = run_meta_insights(loader, "ad", ["act_1"], days, fetch=fetch, force=True)
    assert third.chunks_done == 2 and len(calls) == 4


def test_failed_chunk_is_isolated_recorded_and_retried_next_run(conn):
    loader = RedshiftLoader(conn)
    days = [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)]

    def flaky(a, d, r):
        if d == date(2026, 3, 2):
            raise TimeoutError("async report timed out")
        return ad_rows(d, 1)

    res = run_meta_insights(loader, "ad", ["act_1"], days, fetch=flaky)
    assert not res.ok and res.chunks_done == 2 and len(res.failures) == 1
    assert count(conn, "select count(*) from raw_meta.ad_insights_daily") == 2
    with conn.cursor() as cur:
        cur.execute("select status from ops.ingestion_runs")
        assert cur.fetchone()[0] == "partial"
        cur.execute("select status from ops.ingestion_checkpoints where chunk_key = '2026-03-02'")
        assert cur.fetchone()[0] == "failed"
    # next run (no force): only the failed chunk is retried
    fixed = run_meta_insights(loader, "ad", ["act_1"], days, fetch=lambda a, d, r: ad_rows(d, 1))
    assert fixed.ok and fixed.chunks_done == 1 and fixed.chunks_skipped == 2


def test_run_record_upserts_not_duplicates(conn):
    loader = RedshiftLoader(conn)
    run_meta_insights(loader, "ad", ["act_1"], [date(2026, 3, 1)], fetch=lambda a, d, r: ad_rows(d))
    assert count(conn, "select count(*) from ops.ingestion_runs") == 1   # start row replaced by finish row
    assert count(conn, "select rows_loaded from ops.ingestion_runs") == 2


def test_product_level_and_catalog_and_mixpanel_loads(conn):
    loader = RedshiftLoader(conn)
    day = date(2026, 3, 1)
    run_meta_insights(loader, "product", ["act_1"], [day], fetch=lambda a, d, r: [
        RawAdProductInsightRow(account_id=a, date_start=d, campaign_id="c", adset_id="s", ad_id="ad1", product_id_raw="m1",
                               spend=Decimal("5"), impressions=10)])
    assert count(conn, "select count(*) from raw_meta.ad_product_insights_daily") == 1

    cat = [RawCatalogProductRow(snapshot_date=day, catalog_id="cat1", id="m1", retailer_id="SKU-A", raw={"x": 1})]
    run_meta_catalog(loader, ["cat1"], day, fetch=lambda c, d: cat)
    run_meta_catalog(loader, ["cat1"], day, fetch=lambda c, d: cat)           # re-run same snapshot
    assert count(conn, "select count(*) from raw_meta.catalog_products") == 1

    raw = [{"event": "Order Completed", "properties": {"time": 1772352000, "distinct_id": "u1", "$insert_id": "i1",
                                                        "order_id": "o1", "email": "a@b.com"}},
           {"event": "Order Completed", "properties": {"time": 1772352000, "distinct_id": "u1", "$insert_id": "i1"}}]  # dup
    run_mixpanel(loader, [date(2026, 3, 1)], fetch=lambda d: raw)
    run_mixpanel(loader, [date(2026, 3, 1)], fetch=lambda d: raw, force=True)
    assert count(conn, "select count(*) from raw_mixpanel.events") == 1
    assert "a@b.com" not in str(count(conn, "select properties from raw_mixpanel.events"))   # PII stripped


def test_to_tuples_serialises_nested_fields_as_json():
    cols, rows = to_tuples([RawMixpanelEventRow(event="e", event_time=datetime(2026, 3, 1), distinct_id="u", insert_id="i",
                                                properties={"b": 1, "a": [1, 2]})])
    props = rows[0][cols.index("properties")]
    assert props == '{"a": [1, 2], "b": 1}'


# ── automatic splitting of oversized Pull B reports ───────────────────────────
from ingestion.jobs import fetch_product_with_split  # noqa: E402


def prod(ad, pid, camp="c1", adset="s1", spend="1"):
    return RawAdProductInsightRow(account_id="act_1", date_start=date(2026, 3, 1), campaign_id=camp, adset_id=adset, ad_id=ad,
                                  product_id_raw=pid, spend=Decimal(spend))


def seed_pull_a(loader, conn):
    rows = [RawAdInsightRow(account_id="act_1", date_start=date(2026, 3, 1), campaign_id=c, adset_id=s, ad_id=f"{c}{s}", spend=Decimal("1"))
            for c, s in (("c1", "s1"), ("c1", "s2"), ("c2", "s3"))]
    run_meta_insights(loader, "ad", ["act_1"], [date(2026, 3, 1)], fetch=lambda a, d, r: rows)


def test_split_by_campaign_when_account_report_is_too_big(conn):
    loader = RedshiftLoader(conn)
    seed_pull_a(loader, conn)
    calls = []

    def fetch_one(acct, day, rid, campaign_id=None, adset_id=None):
        calls.append((campaign_id, adset_id))
        if campaign_id is None and adset_id is None:
            raise RuntimeError("Async report r1 ended with status='Job Failed' (too much data)")
        return [prod("ad", f"p-{campaign_id}", camp=campaign_id)]

    rows = fetch_product_with_split(loader, "act_1", date(2026, 3, 1), "run", fetch_one)
    assert [r.product_id_raw for r in rows] == ["p-c1", "p-c2"]
    assert calls == [(None, None), ("c1", None), ("c2", None)]


def test_split_falls_through_to_adsets_for_a_campaign_that_is_still_too_big(conn):
    loader = RedshiftLoader(conn)
    seed_pull_a(loader, conn)

    def fetch_one(acct, day, rid, campaign_id=None, adset_id=None):
        if adset_id is None and campaign_id in (None, "c1"):
            raise TimeoutError("report did not complete")
        return [prod("ad", f"p-{campaign_id or adset_id}")]

    rows = fetch_product_with_split(loader, "act_1", date(2026, 3, 1), "run", fetch_one)
    assert sorted(r.product_id_raw for r in rows) == ["p-c2", "p-s1", "p-s2"]


def test_unrelated_errors_are_not_swallowed_by_the_splitter(conn):
    loader = RedshiftLoader(conn)

    def boom(acct, day, rid, campaign_id=None, adset_id=None):
        raise RuntimeError("Invalid OAuth access token")

    with pytest.raises(RuntimeError, match="OAuth"):
        fetch_product_with_split(loader, "act_1", date(2026, 3, 1), "run", boom)


def test_cannot_split_without_pull_a_rows(conn):
    loader = RedshiftLoader(conn)

    def too_big(acct, day, rid, campaign_id=None, adset_id=None):
        raise RuntimeError("too much data")

    with pytest.raises(RuntimeError, match="run Pull A first"):
        fetch_product_with_split(loader, "act_1", date(2026, 3, 1), "run", too_big)
