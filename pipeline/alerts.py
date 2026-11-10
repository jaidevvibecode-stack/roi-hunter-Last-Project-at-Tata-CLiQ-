"""
pipeline/alerts.py — Slack webhook alerts. No-op unless ALERT_SLACK_WEBHOOK is set.
Messages are redacted (tokens / emails / phones) and never include customer rows; delivery failures never crash a run.
"""
from __future__ import annotations

import logging
import os

import httpx

from ingestion.common.logging_utils import redact

log = logging.getLogger(__name__)


def send_alert(text: str, *, webhook: str | None = None, transport: httpx.BaseTransport | None = None) -> bool:
    url = webhook if webhook is not None else os.environ.get("ALERT_SLACK_WEBHOOK", "")
    if not url:
        log.info("alert skipped (no webhook configured)")
        return False
    try:
        with httpx.Client(transport=transport, timeout=10) as c:
            r = c.post(url, json={"text": redact(text)[:3500]})
            r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — alerting must never break the pipeline
        log.warning("alert delivery failed: %s", exc.__class__.__name__)
        return False
