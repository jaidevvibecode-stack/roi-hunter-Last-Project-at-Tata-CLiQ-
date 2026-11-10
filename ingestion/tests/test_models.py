"""
ingestion/tests/test_models.py
--------------------------------
Tests for data model correctness:
- Decimal money (no float rounding)
- Deduplication in parse_events
- PII stripping in Mixpanel event parser
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingestion.common.models import (
    RawAdInsightRow,
    RawAdProductInsightRow,
)
from ingestion.mixpanel.events import parse_events


def test_spend_is_decimal() -> None:
    row = RawAdInsightRow(
        account_id="act_123",
        date_start=date(2024, 1, 15),
        campaign_id="c1",
        adset_id="as1",
        ad_id="a1",
        spend=Decimal("999.999999"),
    )
    # Decimal arithmetic must be exact
    assert row.spend == Decimal("999.999999")
    assert isinstance(row.spend, Decimal)
    # Float comparison would fail here — that's intentional
    assert row.spend != 999.999999  # float has rounding error


def test_product_insight_preserves_raw_product_id() -> None:
    """product_id_raw must be stored exactly as received — normalisation happens in dbt."""
    raw_val = "g_12345_en_US|Some product name"
    row = RawAdProductInsightRow(
        account_id="act_123",
        date_start=date(2024, 1, 15),
        campaign_id="c1",
        adset_id="as1",
        ad_id="a1",
        product_id_raw=raw_val,
        spend=Decimal("0"),
    )
    assert row.product_id_raw == raw_val


def _make_mp_raw(
    event: str,
    insert_id: str,
    epoch: int = 1705276800,  # 2024-01-15 00:00:00 UTC
    extra_props: dict | None = None,
) -> dict:
    props: dict = {"time": epoch, "distinct_id": "user_abc", "$insert_id": insert_id}
    if extra_props:
        props.update(extra_props)
    return {"event": event, "properties": props}


def test_mixpanel_deduplication() -> None:
    raw = [
        _make_mp_raw("Purchase", "id_001"),
        _make_mp_raw("Purchase", "id_001"),  # duplicate
        _make_mp_raw("Purchase", "id_002"),
    ]
    rows = parse_events(raw)
    assert len(rows) == 2


def test_mixpanel_pii_stripped() -> None:
    raw = [
        _make_mp_raw(
            "Purchase",
            "id_003",
            extra_props={"$email": "user@example.com", "phone": "9999999999", "sku": "SKU123"},
        )
    ]
    rows = parse_events(raw)
    assert len(rows) == 1
    props = rows[0].properties
    assert "$email" not in props
    assert "phone" not in props
    assert "sku" in props  # non-PII preserved


def test_mixpanel_missing_insert_id_skipped() -> None:
    raw = [{"event": "Purchase", "properties": {"time": 1705276800, "distinct_id": "u1"}}]
    rows = parse_events(raw)
    assert rows == []
