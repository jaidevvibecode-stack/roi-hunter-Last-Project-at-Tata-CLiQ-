"""
ingestion/mixpanel/events.py
-----------------------------
Parse raw Mixpanel event dicts into RawMixpanelEventRow records.
Property names (SKU, price, quantity, order_id, UTM fields) are NOT
hardcoded — they come from config/context once verified in spike P0.6.

DESIGN §7.4, §5 prerequisites P2/P3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ingestion.common.models import RawMixpanelEventRow

log = logging.getLogger(__name__)


_MAPPING_FILE = Path(__file__).resolve().parents[2] / "config" / "mixpanel_mapping.yml"


@dataclass(frozen=True)
class EventPropertyMap:
    """
    Event / property names, loaded from config/mixpanel_mapping.yml (single source of truth, mirrored in the dbt
    vars — a test fails if they drift). PLACEHOLDERS until spike P0.6 / Q5 verifies them.
    """

    purchase_event: str
    product_view_event: str
    touch_events: tuple[str, ...]
    properties: dict[str, str]
    meta_utm_sources: tuple[str, ...]
    paid_utm_mediums: tuple[str, ...]

    @property
    def export_events(self) -> list[str]:
        """Event names to request from the Mixpanel export API (only what the models need)."""
        return list(dict.fromkeys([self.purchase_event, self.product_view_event, *self.touch_events]))


def load_mapping(path: Path = _MAPPING_FILE) -> EventPropertyMap:
    cfg = yaml.safe_load(path.read_text())
    return EventPropertyMap(
        purchase_event=cfg["purchase_event"],
        product_view_event=cfg["product_view_event"],
        touch_events=tuple(cfg.get("touch_events", [])),
        properties=dict(cfg["properties"]),
        meta_utm_sources=tuple(cfg["meta_utm_sources"]),
        paid_utm_mediums=tuple(cfg["paid_utm_mediums"]),
    )


DEFAULT_PROPERTY_MAP = load_mapping()


def parse_event(raw: dict[str, Any]) -> RawMixpanelEventRow | None:
    """
    Parse one raw Mixpanel export event into a RawMixpanelEventRow.
    Returns None if the event cannot be parsed (logged as warning).
    """
    try:
        props: dict[str, Any] = raw.get("properties", {})

        # Mixpanel stores event time as Unix epoch in $time property
        epoch = props.get("time") or props.get("$time")
        if epoch is None:
            log.warning("Event missing time property — skipping")
            return None
        event_time = datetime.fromtimestamp(int(epoch), tz=timezone.utc).replace(tzinfo=None)

        distinct_id: str = str(props.get("distinct_id", props.get("$distinct_id", "")))
        insert_id: str = str(props.get("$insert_id", ""))

        if not distinct_id or not insert_id:
            log.warning(
                "Event missing distinct_id or $insert_id",
                extra={"event": raw.get("event")},
            )
            return None

        # Strip PII-adjacent fields we must not store (DESIGN §13)
        cleaned_props = {
            k: v for k, v in props.items()
            if k not in ("$email", "email", "$phone", "phone", "$name")
        }

        return RawMixpanelEventRow(
            event=str(raw.get("event", "")),
            event_time=event_time,
            distinct_id=distinct_id,
            insert_id=insert_id,
            properties=cleaned_props,
        )
    except Exception as exc:
        log.warning("Failed to parse Mixpanel event", extra={"error": str(exc)})
        return None


def parse_events(
    raw_events: list[dict[str, Any]],
    seen_insert_ids: set[str] | None = None,
) -> list[RawMixpanelEventRow]:
    """
    Parse and deduplicate a batch of raw export events.
    `seen_insert_ids` allows cross-batch deduplication when processing multiple days.
    """
    seen: set[str] = seen_insert_ids or set()
    rows: list[RawMixpanelEventRow] = []
    for raw in raw_events:
        row = parse_event(raw)
        if row is None:
            continue
        if row.insert_id in seen:
            continue  # idempotent — skip duplicates
        seen.add(row.insert_id)
        rows.append(row)
    return rows
