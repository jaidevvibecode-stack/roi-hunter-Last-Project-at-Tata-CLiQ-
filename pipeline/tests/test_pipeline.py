"""Pipeline orchestration, scheduler maths, alerts, doctor — all with injected fakes (no network)."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from pipeline import doctor
from pipeline.alerts import send_alert
from pipeline.run_daily import STEP_ORDER, plan_window, run_pipeline
from pipeline.scheduler import next_run, parse_run_at


# ── window planning ───────────────────────────────────────────────────────────
def test_normal_day_pulls_trailing_7_days_ending_yesterday():
    w = plan_window(date(2026, 3, 4))            # Wednesday
    assert len(w) == 7 and w[-1] == date(2026, 3, 3) and w[0] == date(2026, 2, 25)


def test_monday_does_28_day_restatement():
    w = plan_window(date(2026, 3, 2))            # Monday
    assert len(w) == 28 and w[-1] == date(2026, 3, 1)


# ── orchestration ─────────────────────────────────────────────────────────────
def handlers(fail: set[str] = frozenset(), raise_in: set[str] = frozenset(), dq_errors=()):
    calls: list[str] = []

    def make(name):
        def h(a, w):
            calls.append(name)
            if name in raise_in:
                raise RuntimeError("boom")
            return name not in fail, name
        return h

    h = {n: make(n) for n in STEP_ORDER}
    h["_dq_summary"] = lambda a, w: {"errors": list(dq_errors), "warnings": [], "has_errors": bool(dq_errors)}
    return h, calls


def test_happy_path_runs_all_steps_in_order_and_does_not_alert():
    h, calls = handlers()
    alerts: list[str] = []
    rep = run_pipeline(STEP_ORDER, date(2026, 3, 4), h, alert=alerts.append)
    assert rep.ok and calls == STEP_ORDER and not alerts


def test_failure_skips_dbt_but_dq_still_runs_and_alert_is_sent():
    h, calls = handlers(fail={"meta_ad"})
    alerts: list[str] = []
    rep = run_pipeline(STEP_ORDER, date(2026, 3, 4), h, alert=alerts.append)
    assert not rep.ok and "dbt" not in calls and "dq" in calls
    assert [s.skipped for s in rep.steps if s.name in ("meta_product", "mixpanel", "dbt")] == [True, True, True]
    assert alerts and "FAILED" in alerts[0] and "meta_ad" in alerts[0]


def test_exception_in_a_step_is_contained():
    h, calls = handlers(raise_in={"mixpanel"})
    alerts: list[str] = []
    rep = run_pipeline(STEP_ORDER, date(2026, 3, 4), h, alert=alerts.append)
    assert not rep.ok and calls[-1] == "dq" and "RuntimeError" in rep.steps[STEP_ORDER.index("mixpanel")].detail


def test_dq_errors_fail_the_run_even_if_all_steps_succeed():
    h, _ = handlers(dq_errors=["spend_id_match_rate"])
    alerts: list[str] = []
    rep = run_pipeline(STEP_ORDER, date(2026, 3, 4), h, alert=alerts.append)
    assert not rep.ok and alerts and "spend_id_match_rate" in alerts[0]


def test_dry_run_executes_nothing_and_never_alerts():
    h, calls = handlers(fail={"dbt"})
    alerts: list[str] = []
    rep = run_pipeline(STEP_ORDER, date(2026, 3, 4), h, dry_run=True, alert=alerts.append)
    assert rep.ok and not calls and not alerts


def test_unknown_step_rejected_and_subset_respected():
    h, calls = handlers()
    with pytest.raises(ValueError):
        run_pipeline(["nope"], date(2026, 3, 4), h)
    run_pipeline(["dbt", "dq"], date(2026, 3, 4), h, alert=lambda t: None)
    assert calls == ["dbt", "dq"]


# ── scheduler ─────────────────────────────────────────────────────────────────
IST = "Asia/Kolkata"


def test_next_run_later_today_when_before_run_time():
    now = datetime(2026, 3, 4, 5, 0, tzinfo=ZoneInfo(IST))
    assert next_run(now, IST, time(6, 30)) == datetime(2026, 3, 4, 6, 30, tzinfo=ZoneInfo(IST))


def test_next_run_tomorrow_when_at_or_after_run_time():
    at = time(6, 30)
    assert next_run(datetime(2026, 3, 4, 6, 30, tzinfo=ZoneInfo(IST)), IST, at).date() == date(2026, 3, 5)   # exactly at => next day
    assert next_run(datetime(2026, 3, 4, 23, 59, tzinfo=ZoneInfo(IST)), IST, at).date() == date(2026, 3, 5)


def test_next_run_converts_from_utc():
    now = datetime(2026, 3, 4, 0, 30, tzinfo=ZoneInfo("UTC"))          # 06:00 IST
    assert next_run(now, IST, time(6, 30)) == datetime(2026, 3, 4, 6, 30, tzinfo=ZoneInfo(IST))


def test_parse_run_at():
    assert parse_run_at("06:30") == time(6, 30)


# ── alerts ────────────────────────────────────────────────────────────────────
def test_alert_noop_without_webhook(monkeypatch):
    monkeypatch.delenv("ALERT_SLACK_WEBHOOK", raising=False)
    assert send_alert("x") is False


def test_alert_posts_redacted_text():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200)

    ok = send_alert("failed for ops@tata.com access_token=EAAB123456789012345678901234", webhook="https://hooks.example/x",
                    transport=httpx.MockTransport(handler))
    assert ok and "ops@tata.com" not in seen["body"]["text"] and "EAAB" not in seen["body"]["text"]


def test_alert_failure_never_raises():
    assert send_alert("x", webhook="https://hooks.example/x", transport=httpx.MockTransport(lambda r: httpx.Response(500))) is False


# ── doctor ────────────────────────────────────────────────────────────────────
def test_env_check_never_leaks_values():
    f = doctor.check_env({"META_ACCESS_TOKEN": "SECRET-VALUE"})
    assert any(x.check == "env META_ACCESS_TOKEN" and x.ok for x in f)
    assert "SECRET-VALUE" not in doctor.render(f) and any(not x.ok for x in f)


def meta_transport(scopes, valid=True):
    def handler(req: httpx.Request):
        if req.url.path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"is_valid": valid, "type": "SYSTEM_USER", "scopes": scopes}})
        return httpx.Response(200, json={"data": []})
    return httpx.MockTransport(handler)


ENV = {"META_ACCESS_TOKEN": "t", "META_APP_ID": "1", "META_APP_SECRET": "s"}


def test_meta_least_privilege_passes_for_read_only_token():
    f = {x.check: x for x in doctor.check_meta(ENV, meta_transport(["ads_read"]))}
    assert f["token valid"].ok and f["has ads_read"].ok and f["least privilege (no write scopes)"].ok


def test_meta_flags_over_broad_scopes_and_missing_read():
    f = {x.check: x for x in doctor.check_meta(ENV, meta_transport(["ads_management", "business_management"]))}
    assert not f["has ads_read"].ok and not f["least privilege (no write scopes)"].ok and "ads_management" in f["least privilege (no write scopes)"].detail


def test_meta_invalid_token_fails():
    assert not {x.check: x for x in doctor.check_meta(ENV, meta_transport([], valid=False))}["token valid"].ok


def test_mixpanel_probe():
    env = {"MIXPANEL_REGION": "EU", "MIXPANEL_PROJECT_ID": "9", "MIXPANEL_SERVICE_ACCOUNT_USER": "u", "MIXPANEL_SERVICE_ACCOUNT_SECRET": "s"}
    seen = {}

    def handler(r):
        seen["host"] = r.url.host
        return httpx.Response(200, text="")

    assert doctor.check_mixpanel(env, httpx.MockTransport(handler))[0].ok and seen["host"] == "data-eu.mixpanel.com"
    assert not doctor.check_mixpanel(env, httpx.MockTransport(lambda r: httpx.Response(401)))[0].ok


def test_redshift_privilege_findings():
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.side_effect = [(True,), (True,), (False,)]
    f = doctor.check_redshift(lambda: conn)
    assert [x.ok for x in f] == [True, True, True, False] and conn.close.called
    assert not doctor.check_redshift(lambda: (_ for _ in ()).throw(ConnectionError()))[0].ok


def test_s3_check():
    ok, bad = MagicMock(), MagicMock()
    bad.head_bucket.side_effect = PermissionError()
    assert doctor.check_s3(ok, "b")[0].ok and not doctor.check_s3(bad, "b")[0].ok
