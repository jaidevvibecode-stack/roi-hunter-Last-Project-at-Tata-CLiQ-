"""
pipeline/scheduler.py — long-running daily scheduler (container entrypoint).

Runs the daily pipeline at RUN_AT (default 06:30) in REPORTING_TZ — after Meta's reporting day has closed for
Asia/Kolkata ad accounts. Survives failures (alerts, keeps looping) and writes a heartbeat file for container health.
Alternative without a long-running process: cron / GitHub Actions / ECS Scheduled Task calling `python -m pipeline.run_daily`.
"""
from __future__ import annotations

import logging
import os
import signal
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.alerts import send_alert

log = logging.getLogger(__name__)
HEARTBEAT = Path(os.environ.get("SCHEDULER_HEARTBEAT", "/tmp/scheduler.heartbeat"))  # noqa: S108  # nosec B108 - liveness file only


def next_run(now: datetime, tz: str, at: time) -> datetime:
    """Next occurrence of `at` (wall-clock in `tz`) strictly after `now`. `now` must be timezone-aware."""
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    candidate = datetime.combine(local.date(), at, tzinfo=zone)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=zone)
    return candidate


def parse_run_at(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def main() -> None:
    from ingestion.common.logging_utils import setup_logging
    from pipeline.run_daily import STEP_ORDER, default_handlers, run_pipeline

    setup_logging()
    tz = os.environ.get("REPORTING_TZ", "Asia/Kolkata")
    at = parse_run_at(os.environ.get("RUN_AT", "06:30"))
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))

    while not stop["flag"]:
        target = next_run(datetime.now(ZoneInfo("UTC")), tz, at)
        log.info("next run scheduled", extra={"at": target.isoformat()})
        while not stop["flag"] and datetime.now(ZoneInfo("UTC")) < target:
            HEARTBEAT.write_text(datetime.now(ZoneInfo("UTC")).isoformat())
            _time.sleep(30)
        if stop["flag"]:
            break
        try:
            report = run_pipeline(STEP_ORDER, datetime.now(ZoneInfo(tz)).date(), default_handlers())
            log.info("run finished", extra={"ok": report.ok})
        except Exception as exc:  # noqa: BLE001 — the loop must survive anything
            log.exception("pipeline crashed")
            send_alert(f"Pipeline crashed: {exc.__class__.__name__}")


if __name__ == "__main__":
    main()
