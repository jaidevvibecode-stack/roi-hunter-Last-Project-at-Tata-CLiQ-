"""
pipeline/run_daily.py — one daily run: snapshots -> Meta pulls -> Mixpanel -> dbt -> data-quality -> alert.

  python -m pipeline.run_daily                       # everything, as of today
  python -m pipeline.run_daily --steps dbt,dq        # subset
  python -m pipeline.run_daily --date 2026-03-04 --dry-run

Semantics (plan P1.6):
  * trailing 7-day re-pull every day; on MONDAYS a 28-day restatement (Meta restates conversions for ~28 days)
  * a failing step skips the remaining *producer* steps (dbt) but data-quality ALWAYS runs, so staleness is reported
  * any failure / DQ error -> Slack alert and a non-zero exit code
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import click

from pipeline.alerts import send_alert

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
STEP_ORDER = ["objects", "catalog", "meta_ad", "meta_product", "mixpanel", "dbt", "dq"]
ALWAYS_RUN = {"dq"}


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class RunReport:
    as_of: date
    steps: list[StepResult] = field(default_factory=list)
    dq: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return all(s.ok or s.skipped for s in self.steps) and not (self.dq or {}).get("has_errors", False)

    def summary(self) -> str:
        lines = [f"Daily pipeline {'OK' if self.ok else 'FAILED'} (as of {self.as_of})"]
        for s in self.steps:
            lines.append(f"  {'SKIP' if s.skipped else ('ok  ' if s.ok else 'FAIL')} {s.name} {s.detail}".rstrip())
        if self.dq:
            lines.append(f"  DQ errors={self.dq['errors']} warnings={self.dq['warnings']}")
        return "\n".join(lines)


def plan_window(as_of: date) -> list[date]:
    """Days to (re)pull: yesterday back 7 days; Mondays back 28 days to capture Meta's conversion restatements."""
    n = 28 if as_of.weekday() == 0 else 7
    end = as_of - timedelta(days=1)
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]


def run_dbt(select: str | None = None) -> tuple[bool, str]:
    cmd = ["dbt", "build", "--project-dir", str(ROOT / "transform")]
    if select:
        cmd += ["--select", select]
    res = subprocess.run(cmd, capture_output=True, text=True, env=os.environ, check=False)  # noqa: S603
    tail = (res.stdout or "").strip().splitlines()[-1:] or [""]
    return res.returncode == 0, tail[0][:200]


def run_pipeline(steps: list[str], as_of: date, handlers: dict[str, Callable[[date, list[date]], tuple[bool, str]]],
                 dry_run: bool = False, alert: Callable[[str], Any] = send_alert) -> RunReport:
    unknown = set(steps) - set(STEP_ORDER)
    if unknown:
        raise ValueError(f"unknown steps: {sorted(unknown)}")
    report, window, failed = RunReport(as_of=as_of), plan_window(as_of), False
    for name in [s for s in STEP_ORDER if s in steps]:
        if failed and name not in ALWAYS_RUN:
            report.steps.append(StepResult(name, ok=False, skipped=True, detail="skipped after earlier failure"))
            continue
        if dry_run:
            report.steps.append(StepResult(name, ok=True, skipped=True, detail=f"dry-run window={window[0]}..{window[-1]}"))
            continue
        try:
            ok, detail = handlers[name](as_of, window)
        except Exception as exc:  # noqa: BLE001 — never let one step crash the run before alerting
            ok, detail = False, f"{exc.__class__.__name__}: {exc}"[:300]
        report.steps.append(StepResult(name, ok, detail))
        if name == "dq" and handlers.get("_dq_summary"):
            report.dq = handlers["_dq_summary"](as_of, window)  # type: ignore[assignment]
        failed = failed or not ok
    if not report.ok and not dry_run:
        alert(report.summary())
    return report


def default_handlers() -> dict[str, Callable[..., Any]]:
    from ingestion.common.config import get_settings
    from ingestion.common.redshift import RedshiftLoader, get_connection
    from ingestion.jobs import run_meta_catalog, run_meta_insights, run_meta_objects, run_mixpanel
    from pipeline import dq as dqmod

    cfg = get_settings()
    r = cfg.redshift
    state: dict[str, Any] = {}

    def loader() -> RedshiftLoader:
        if "loader" not in state:
            state["loader"] = RedshiftLoader(get_connection(r.host, r.port, r.db, r.user, r.password), r.iam_role_arn)
        return state["loader"]  # type: ignore[no-any-return]

    def fmt(res: Any) -> tuple[bool, str]:
        return res.ok, f"rows={res.rows_loaded} done={res.chunks_done} skipped={res.chunks_skipped} failed={len(res.failures)}"

    def dq_step(as_of: date, _w: list[date]) -> tuple[bool, str]:
        results = dqmod.run_checks(loader()._conn, dqmod.load_checks(), as_of)  # noqa: SLF001
        dqmod.persist(loader(), results)
        state["dq"] = dqmod.summarize(results)
        return not state["dq"]["has_errors"], f"errors={len(state['dq']['errors'])} warnings={len(state['dq']['warnings'])}"

    return {
        "objects": lambda a, w: fmt(run_meta_objects(loader(), cfg.meta.ad_account_ids, a)),
        "catalog": lambda a, w: fmt(run_meta_catalog(loader(), cfg.meta.catalog_ids, a)),
        "meta_ad": lambda a, w: fmt(run_meta_insights(loader(), "ad", cfg.meta.ad_account_ids, w, force=True)),
        "meta_product": lambda a, w: fmt(run_meta_insights(loader(), "product", cfg.meta.ad_account_ids, w, force=True)),
        "mixpanel": lambda a, w: fmt(run_mixpanel(loader(), w[-3:], force=True)),   # events are append-only: last 3 days
        "dbt": lambda a, w: run_dbt(),
        "dq": dq_step,
        "_dq_summary": lambda a, w: state.get("dq", {"errors": [], "warnings": [], "has_errors": False}),
    }


@click.command()
@click.option("--steps", default=",".join(STEP_ORDER), show_default=True)
@click.option("--date", "as_of", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="Run as of this date (default: today)")
@click.option("--dry-run", is_flag=True)
def main(steps: str, as_of: Any, dry_run: bool) -> None:
    from ingestion.common.logging_utils import setup_logging

    setup_logging()
    day = as_of.date() if as_of else date.today()
    report = run_pipeline([s.strip() for s in steps.split(",") if s.strip()], day,
                          {} if dry_run else default_handlers(), dry_run=dry_run)
    click.echo(report.summary())
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
