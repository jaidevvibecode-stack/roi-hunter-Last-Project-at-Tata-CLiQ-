"""Catalog pagination, ads/objects snapshots and the UTM coverage audit — faked SDK, no network."""
from __future__ import annotations

from datetime import date

import pytest

import ingestion.meta.catalog as cat
import ingestion.meta.objects as obj
from ingestion.common.models import RawAdSnapshotRow


class Page(list):
    def __init__(self, items, paging=None):
        super().__init__(items)
        self.paging = paging or {}


def pages(*ps):
    it = iter(ps)
    calls: list[str | None] = []

    def fake(catalog_id, after):
        calls.append(after)
        return next(it)

    return fake, calls


def test_pagination_follows_cursors_until_exhausted(monkeypatch):
    fake, calls = pages(
        Page([{"id": "1"}, {"id": "2"}], {"cursors": {"after": "C1"}, "next": "x"}),
        Page([{"id": "3"}], {"cursors": {"after": "C2"}, "next": "y"}),
        Page([{"id": "4"}], {}),
    )
    monkeypatch.setattr(cat, "_get_catalog_product_page", fake)
    assert [i["id"] for i in cat.iter_catalog_products("cat1")] == ["1", "2", "3", "4"]
    assert calls == [None, "C1", "C2"]


def test_empty_catalog_and_empty_page_terminate(monkeypatch):
    fake, _ = pages(Page([]))
    monkeypatch.setattr(cat, "_get_catalog_product_page", fake)
    assert list(cat.iter_catalog_products("cat1")) == []


def test_next_link_without_cursor_does_not_loop_forever(monkeypatch):
    calls = {"n": 0}

    def fake(catalog_id, after):
        calls["n"] += 1
        assert calls["n"] < 5, "infinite pagination loop"
        return Page([{"id": "1"}], {"next": "https://graph/next"})   # next but no cursors.after

    monkeypatch.setattr(cat, "_get_catalog_product_page", fake)
    assert [i["id"] for i in cat.iter_catalog_products("cat1")] == ["1"] and calls["n"] == 1


def test_snapshot_maps_sku_and_keeps_raw(monkeypatch):
    fake, _ = pages(Page([{"id": "m1", "retailer_id": "SKU-A", "name": "Alpha", "brand": "Aster", "availability": "in stock",
                           "price": "999 INR", "custom_label_0": "star"}], {}))
    monkeypatch.setattr(cat, "_get_catalog_product_page", fake)
    rows = cat.snapshot_catalog("cat1", date(2026, 3, 1), run_id="r1")
    assert (rows[0].id, rows[0].retailer_id, rows[0].catalog_id, rows[0].custom_label_0) == ("m1", "SKU-A", "cat1", "star")
    assert rows[0].snapshot_date == date(2026, 3, 1) and rows[0].raw["name"] == "Alpha"


# ── objects snapshot + UTM audit ──────────────────────────────────────────────
@pytest.fixture
def fake_objects(monkeypatch):
    monkeypatch.setattr(obj, "_fetch_campaigns", lambda a: [{"id": "c1", "name": "Camp", "status": "ACTIVE", "effective_status": "ACTIVE", "objective": "OUTCOME_SALES"}])
    monkeypatch.setattr(obj, "_fetch_adsets", lambda a: [{"id": "s1", "campaign_id": "c1", "name": "Set", "product_set_id": "ps1"}])
    monkeypatch.setattr(obj, "_fetch_ads", lambda a: [
        {"id": "ad1", "adset_id": "s1", "name": "A", "effective_status": "ACTIVE", "url_tags": "utm_source=facebook&utm_content={{ad.id}}"},
        {"id": "ad2", "adset_id": "s1", "name": "B", "effective_status": "ACTIVE", "url_tags": "utm_source=facebook"},
        {"id": "ad3", "adset_id": "s1", "name": "C", "effective_status": "PAUSED", "url_tags": ""},
    ])


def test_snapshot_builds_hierarchy(fake_objects):
    rows = obj.snapshot_objects("act_1", date(2026, 3, 1))
    assert [(r.level, r.id, r.parent_id) for r in rows] == [
        ("campaign", "c1", "act_1"), ("adset", "s1", "c1"), ("ad", "ad1", "s1"), ("ad", "ad2", "s1"), ("ad", "ad3", "s1")]
    assert [r for r in rows if r.level == "adset"][0].product_set_id == "ps1"


def test_utm_audit_counts_only_active_ads_and_gives_the_fix(fake_objects):
    cov = obj.audit_utm_coverage(obj.snapshot_objects("act_1", date(2026, 3, 1)))
    assert cov["total_active_ads"] == 2 and cov["with_ad_id_utm"] == 1 and cov["coverage_pct"] == 50.0   # paused ad ignored
    assert "utm_content={{ad.id}}" in cov["fix"]


def test_utm_audit_edge_cases():
    assert obj.audit_utm_coverage([])["coverage_pct"] is None
    full = [RawAdSnapshotRow(snapshot_date=date(2026, 3, 1), level="ad", id="a", effective_status="ACTIVE", url_tags="UTM_CONTENT=x")]
    assert obj.audit_utm_coverage(full)["coverage_pct"] == 100.0       # case-insensitive
