"""Meta async insights flow with a faked SDK: create report -> poll -> paginate -> parse. No network."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import ingestion.meta.insights as ins


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def load_next_page(self):
        return False


def make_fake_run(statuses, rows):
    class FakeRun:
        _calls = 0

        def __init__(self, run_id):
            self.id = run_id
            self._data = {}

        def api_get(self, fields=None):
            status = statuses[min(FakeRun._calls, len(statuses) - 1)]
            FakeRun._calls += 1
            self._data = {"async_status": status, "async_percent_completion": 100 if status == "Job Complete" else 10}

        def get(self, key, default=None):
            return self._data.get(key, default)

        def get_insights(self):
            return FakeCursor(rows)

    return FakeRun


class FakeAccount:
    def __init__(self):
        self.params = None

    def create_ad_report_run(self, params):
        self.params = params
        return {"id": "run_1"}


@pytest.fixture
def patched(monkeypatch):
    acct = FakeAccount()
    monkeypatch.setattr(ins, "get_ad_account", lambda account_id: acct)
    monkeypatch.setattr(ins.time, "sleep", lambda s: None)
    return acct


PULL_A_ROW = {
    "account_id": "act_1", "date_start": "2026-03-01", "campaign_id": "c1", "adset_id": "s1", "ad_id": "ad1",
    "spend": "155.50", "impressions": "15000", "clicks": "300", "inline_link_clicks": "250",
    "actions": [{"action_type": "purchase", "value": "4"}], "action_values": [{"action_type": "purchase", "value": "400"}],
}
PULL_B_ROW = {"account_id": "act_1", "date_start": "2026-03-01", "campaign_id": "c1", "adset_id": "s1", "ad_id": "ad1",
              "product_id": "12345", "spend": "100", "impressions": "10000", "inline_link_clicks": "200", "clicks": "220"}


def test_pull_a_parses_rows_and_requests_unified_attribution(monkeypatch, patched):
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Running", "Job Complete"], [PULL_A_ROW]))
    rows = ins.fetch_ad_level("act_1", date(2026, 3, 1), run_id="r1")
    assert len(rows) == 1 and rows[0].spend == Decimal("155.50") and rows[0].inline_link_clicks == 250
    assert rows[0].actions[0]["value"] == "4" and rows[0].run_id == "r1"
    p = patched.params
    assert p["level"] == "ad" and p["time_increment"] == "1" and p["use_unified_attribution_setting"] is True
    assert p["time_range"] == {"since": "2026-03-01", "until": "2026-03-01"} and "breakdowns" not in p


def test_pull_b_requests_product_breakdown_and_keeps_raw_id(monkeypatch, patched):
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Complete"], [PULL_B_ROW]))
    rows = ins.fetch_product_level("act_1", date(2026, 3, 1), campaign_id="c1")
    assert rows[0].product_id_raw == "12345"                      # exactly as returned, never normalised here
    assert patched.params["breakdowns"] == ["product_id"]
    assert patched.params["filtering"] == [{"field": "campaign.id", "operator": "EQUAL", "value": "c1"}]


def test_failed_job_raises(monkeypatch, patched):
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Failed"], []))
    with pytest.raises(RuntimeError, match="Job Failed"):
        ins.fetch_ad_level("act_1", date(2026, 3, 1))


def test_never_completing_job_times_out(monkeypatch, patched):
    monkeypatch.setattr(ins, "POLL_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Running"], []))
    with pytest.raises(TimeoutError):
        ins.fetch_ad_level("act_1", date(2026, 3, 1))


def test_empty_day_returns_empty_list(monkeypatch, patched):
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Complete"], []))
    assert ins.fetch_ad_level("act_1", date(2026, 3, 1)) == []


def test_date_helpers():
    assert ins.date_range(date(2026, 3, 1), date(2026, 3, 3)) == [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)]
    assert len(ins.trailing_dates(7)) == 7


# ── attribution pinning (reviewer finding) ────────────────────────────────────
from ingestion.common.config import MetaSettings  # noqa: E402


def test_default_uses_unified_account_setting_and_records_it(monkeypatch, patched):
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Complete"], [PULL_A_ROW]))
    rows = ins.fetch_ad_level("act_1", date(2026, 3, 1))
    assert patched.params["use_unified_attribution_setting"] is True and "action_attribution_windows" not in patched.params
    assert rows[0].attribution_setting == "unified (ad account setting)"          # real setting, not a constant


def test_explicit_windows_are_sent_and_recorded(monkeypatch, patched):
    pinned = MetaSettings(use_unified_attribution=False, attribution_windows="7d_click, 1d_view")
    monkeypatch.setattr(ins, "get_settings", lambda: type("S", (), {"meta": pinned})())
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Complete"], [PULL_A_ROW]))
    rows = ins.fetch_ad_level("act_1", date(2026, 3, 1))
    assert patched.params["use_unified_attribution_setting"] is False
    assert patched.params["action_attribution_windows"] == ["7d_click", "1d_view"]
    assert rows[0].attribution_setting == "windows:7d_click,1d_view"


def test_label_when_nothing_pinned():
    assert ins.attribution_label(MetaSettings(use_unified_attribution=False)) == "api-default"


def test_first_poll_does_not_wait_a_full_interval(monkeypatch, patched):
    sleeps: list[float] = []
    monkeypatch.setattr(ins.time, "sleep", sleeps.append)
    monkeypatch.setattr(ins, "AdReportRun", make_fake_run(["Job Complete"], []))
    ins.fetch_ad_level("act_1", date(2026, 3, 1))
    assert sleeps == [ins.POLL_INITIAL_DELAY_S] and ins.POLL_INITIAL_DELAY_S < ins.POLL_INTERVAL_S
