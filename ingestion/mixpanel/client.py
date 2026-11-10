"""
ingestion/mixpanel/client.py
-----------------------------
Mixpanel Raw Event Export API client.
Endpoint: https://{host}/api/2.0/export
Auth: HTTP Basic (service account user : secret)
Format: newline-delimited JSON (JSONL)
Rate limits: approx 60 queries/hour, 3/second — verify in spike P0.6.

EU projects: host = data-eu.mixpanel.com
IN projects: host = data-in.mixpanel.com

If Mixpanel Data Pipelines already sync to Redshift, skip this module
entirely and point dbt sources at those tables (DESIGN §7.4 decision tree).
"""
from __future__ import annotations

import json
import logging
from datetime import date

import httpx

from ingestion.common.config import MixpanelSettings, get_settings
from ingestion.common.retry import retry_meta  # same retry logic applies

log = logging.getLogger(__name__)

EXPORT_PATH = "/api/2.0/export"
REQUEST_TIMEOUT_S = 300  # export calls can be slow for a full day
PER_SECOND_CAP = 3       # verify in spike


class MixpanelExportClient:
    """
    Client for the Mixpanel Raw Event Export API.
    Use as a context manager to ensure the underlying httpx client is closed.
    """

    def __init__(self, cfg: MixpanelSettings | None = None) -> None:
        cfg = cfg or get_settings().mixpanel
        if not cfg.is_configured():
            raise RuntimeError(
                "Mixpanel credentials not configured. "
                "Set MIXPANEL_PROJECT_ID, MIXPANEL_SERVICE_ACCOUNT_USER, "
                "MIXPANEL_SERVICE_ACCOUNT_SECRET in .env"
            )
        self._cfg = cfg
        self._base_url = f"https://{cfg.export_host}"
        self._auth = (cfg.service_account_user, cfg.service_account_secret)
        self._client: httpx.Client | None = None

    def __enter__(self) -> "MixpanelExportClient":
        self._client = httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            timeout=REQUEST_TIMEOUT_S,
        )
        return self

    def __exit__(self, *_: object) -> None:
        if self._client:
            self._client.close()

    @retry_meta(max_attempts=5)
    def export_day(
        self,
        export_date: date,
        event_names: list[str],
    ) -> list[dict[str, object]]:
        """
        Export all events of given types for one UTC day.
        Returns a list of raw event dicts.
        Deduplication on $insert_id is done by the caller.

        NOTE: property names (SKU prop, price prop, etc.) are NOT hardcoded here.
        They are set by the caller once verified in spike P0.6.
        """
        if self._client is None:
            raise RuntimeError("Use MixpanelExportClient as a context manager.")

        params = {
            "project_id": self._cfg.project_id,
            "from_date": str(export_date),
            "to_date": str(export_date),
            "event": json.dumps(event_names),
        }

        log.info(
            "Mixpanel export: fetching events",
            extra={
                "date": str(export_date),
                "events": event_names,
                "project_id": self._cfg.project_id,
            },
        )

        # Stream line by line: the body is never held as one giant string next to the parsed list. The whole day
        # is still returned as a list so that a retry restarts cleanly (a half-consumed generator cannot be retried).
        events: list[dict[str, object]] = []
        with self._client.stream("GET", EXPORT_PATH, params=params) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Skipping unparseable Mixpanel JSONL line")

        log.info(
            "Mixpanel export: done",
            extra={"date": str(export_date), "event_count": len(events)},
        )
        return events
