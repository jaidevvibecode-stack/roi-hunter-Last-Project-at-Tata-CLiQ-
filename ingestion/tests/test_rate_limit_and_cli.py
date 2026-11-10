"""Meta rate-limit back-off maths and the ingestion CLI (argument handling, safety flags)."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import ingestion.cli as cli_mod
import ingestion.common.rate_limit as rl
from ingestion.jobs import JobResult


# ── rate limit ────────────────────────────────────────────────────────────────
def state_for(headers):
    s = rl.RateLimitState("act_1")
    s.update(headers)
    return s


def test_no_headers_means_no_backoff():
    s = state_for({})
    assert not s.should_backoff() and s.backoff_seconds() == 0


def test_business_use_case_usage_drives_backoff_levels():
    hdr = lambda pct, regain=0: {"x-business-use-case-usage": json.dumps({"123": [{"call_count": pct, "total_cputime": 1, "total_time": 1, "estimated_time_to_regain_access": regain}]})}  # noqa: E731
    assert not state_for(hdr(50)).should_backoff()
    mid = state_for(hdr(80))
    assert mid.should_backoff() and mid.backoff_seconds() == 30                      # default for 75-90%
    crit = state_for(hdr(95))
    assert crit.backoff_seconds() == 120                                              # default for >= 90%
    assert state_for(hdr(95, regain=300)).backoff_seconds() == 300                    # server estimate wins


def test_insights_throttle_header_and_garbage_are_handled():
    assert state_for({"x-fb-ads-insights-throttle": json.dumps({"app_id_util_pct": 10, "acc_id_util_pct": 92})}).should_backoff()
    s = state_for({"x-business-use-case-usage": "not json", "x-fb-ads-insights-throttle": "{{"})
    assert not s.should_backoff()                                                     # unparseable => no crash, no back-off


def test_wait_sleeps_only_when_needed(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(rl.time, "sleep", slept.append)
    rl.update_and_wait("act_slow", {"x-fb-ads-insights-throttle": json.dumps({"acc_id_util_pct": 99})})
    rl.update_and_wait("act_ok", {"x-fb-ads-insights-throttle": json.dumps({"acc_id_util_pct": 5})})
    assert slept == [120.0] and rl.get_state("act_slow") is rl.get_state("act_slow")


# ── CLI ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_cli(monkeypatch):
    calls: dict[str, object] = {}
    monkeypatch.setattr(cli_mod, "_loader", lambda: MagicMock(name="loader"))
    monkeypatch.setattr(cli_mod, "setup_logging", lambda: None)
    monkeypatch.setattr(cli_mod, "get_settings", lambda: SimpleNamespace(meta=SimpleNamespace(ad_account_ids=["act_env"], catalog_ids=["cat_env"])))

    def meta_insights(loader, level, accounts, days, force=False):
        calls["meta"] = (level, accounts, days, force)
        return JobResult("meta", "r", rows_loaded=5, chunks_done=len(days))

    def mixpanel(loader, days, force=False):
        calls["mixpanel"] = (days, force)
        return JobResult("mixpanel", "r", rows_loaded=1, chunks_done=len(days))

    monkeypatch.setattr(cli_mod, "run_meta_insights", meta_insights)
    monkeypatch.setattr(cli_mod, "run_mixpanel", mixpanel)
    monkeypatch.setattr(cli_mod, "run_meta_catalog", lambda ld, ids, d: calls.setdefault("catalog", ids) and JobResult("c", "r"))
    monkeypatch.setattr(cli_mod, "run_meta_objects", lambda ld, a, d: calls.setdefault("objects", a) and JobResult("o", "r"))
    return calls


def test_backfill_expands_dates_and_uses_account_override(fake_cli):
    r = CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "meta_product", "--from", "2026-03-01", "--to", "2026-03-03", "--accounts", "act_1, act_2"])
    assert r.exit_code == 0, r.output
    level, accounts, days, force = fake_cli["meta"]
    assert level == "product" and accounts == ["act_1", "act_2"] and len(days) == 3 and days[0] == date(2026, 3, 1) and not force


def test_backfill_defaults_to_env_accounts_and_force_flag(fake_cli):
    assert CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "meta_ad", "--from", "2026-03-01", "--to", "2026-03-01", "--force"]).exit_code == 0
    assert fake_cli["meta"][1] == ["act_env"] and fake_cli["meta"][3] is True


def test_mixpanel_backfill_and_bad_inputs(fake_cli):
    assert CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "mixpanel", "--from", "2026-03-01", "--to", "2026-03-02"]).exit_code == 0
    assert len(fake_cli["mixpanel"][0]) == 2
    assert CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "bogus", "--from", "2026-03-01", "--to", "2026-03-02"]).exit_code != 0
    assert CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "meta_ad", "--from", "03/01/2026", "--to", "2026-03-02"]).exit_code != 0


def test_trailing_pulls_both_levels_and_rejects_out_of_range(fake_cli):
    assert CliRunner().invoke(cli_mod.cli, ["trailing", "--days", "3"]).exit_code == 0
    assert CliRunner().invoke(cli_mod.cli, ["trailing", "--days", "99"]).exit_code != 0


def test_failures_make_the_cli_exit_non_zero(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_mod, "run_mixpanel", lambda ld, d, force=False: JobResult("mixpanel", "r", failures=["2026-03-01: boom"]))
    r = CliRunner().invoke(cli_mod.cli, ["backfill", "--source", "mixpanel", "--from", "2026-03-01", "--to", "2026-03-01"])
    assert r.exit_code == 1 and "FAILED" in r.output


def test_catalog_and_objects_commands(fake_cli):
    assert CliRunner().invoke(cli_mod.cli, ["catalog"]).exit_code == 0 and fake_cli["catalog"] == ["cat_env"]
    assert CliRunner().invoke(cli_mod.cli, ["objects"]).exit_code == 0 and fake_cli["objects"] == ["act_env"]


def test_init_schemas_requires_explicit_approval(monkeypatch):
    loader = MagicMock()
    monkeypatch.setattr(cli_mod, "_loader", lambda: loader)
    loader.bootstrap_owned_schemas.side_effect = lambda d, approved: (_ for _ in ()).throw(PermissionError("needs approval")) if not approved else None
    assert CliRunner().invoke(cli_mod.cli, ["init-schemas"]).exit_code != 0
    assert CliRunner().invoke(cli_mod.cli, ["init-schemas", "--i-have-approval"]).exit_code == 0
