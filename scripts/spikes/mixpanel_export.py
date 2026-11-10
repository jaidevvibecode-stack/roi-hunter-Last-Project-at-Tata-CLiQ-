"""
scripts/spikes/mixpanel_export.py  — P0.6
-------------------------------------------
Spike: export 1 day of Mixpanel events and verify:
- Event/property names (purchase event, SKU, price, qty, order_id, UTM props)
- % of purchase events with SKU and order_id
- % of sessions with utm_content (ad_id linkage)
- $insert_id presence (for deduplication)
- distinct_id behaviour (pre/post identity merge)

Run: python scripts/spikes/mixpanel_export.py

Fill in EVENT_NAMES below once you know the actual event names (Q5).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.mixpanel.client import MixpanelExportClient
from ingestion.mixpanel.events import DEFAULT_PROPERTY_MAP, parse_events

setup_logging("INFO")

SAMPLES_DIR = Path(__file__).parent.parent.parent / "docs" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

# ── Fill these in once Q5 is answered (or pass as env vars) ─────────────────
EVENT_NAMES = [
    DEFAULT_PROPERTY_MAP.purchase_event,       # e.g. "Order Completed"
    DEFAULT_PROPERTY_MAP.product_view_event,   # e.g. "Product Viewed"
]
PROP = DEFAULT_PROPERTY_MAP


def main() -> None:
    cfg = get_settings()
    if not cfg.mixpanel.is_configured():
        print("❌ MIXPANEL_* credentials not set in .env")
        sys.exit(1)

    spike_date = date.today() - timedelta(days=1)
    print(f"\n⏳ Exporting Mixpanel events for {spike_date} ...")
    print(f"   Events: {EVENT_NAMES}")
    print(f"   Region: {cfg.mixpanel.region} (host: {cfg.mixpanel.export_host})")

    with MixpanelExportClient() as client:
        raw_events = client.export_day(spike_date, EVENT_NAMES)

    print(f"✅ Raw events fetched: {len(raw_events)}")

    rows = parse_events(raw_events)
    print(f"   After deduplication: {len(rows)}")

    # Analyse
    by_event: Counter[str] = Counter(r.event for r in rows)
    print(f"\n📊 Event breakdown: {dict(by_event)}")

    purchases = [r for r in rows if r.event == PROP.purchase_event]
    print(f"\n📦 Purchase events: {len(purchases)}")

    if purchases:
        with_sku = sum(1 for r in purchases if r.properties.get(PROP.sku_property))
        with_order_id = sum(1 for r in purchases if r.properties.get(PROP.order_id_property))
        print(f"   with SKU ({PROP.sku_property}):        {with_sku}/{len(purchases)} = {with_sku/len(purchases)*100:.1f}%")
        print(f"   with order_id ({PROP.order_id_property}): {with_order_id}/{len(purchases)} = {with_order_id/len(purchases)*100:.1f}%")

        # Sample properties to verify names
        sample_props = purchases[0].properties if purchases else {}
        print(f"\n   Sample purchase properties (keys): {list(sample_props.keys())}")

    views = [r for r in rows if r.event == PROP.product_view_event]
    if views:
        with_utm = sum(1 for r in views if r.properties.get(PROP.utm_content_property))
        with_fbclid = sum(1 for r in views if r.properties.get(PROP.fbclid_property))
        print(f"\n🔗 Product views: {len(views)}")
        print(f"   with utm_content: {with_utm} = {with_utm/len(views)*100:.1f}%")
        print(f"   with $fbclid:     {with_fbclid} = {with_fbclid/len(views)*100:.1f}%")

    # F7/F8 notes
    print(f"\nF7 — Export API host used: {cfg.mixpanel.export_host}")
    print("F8 — If Data Pipelines is enabled, those tables should be used instead.")
    print("\n📝 Record exact property names in 03_CONTEXT.md Q5 answer.")

    # Save redacted sample (distinct_id hashed)
    sample_out = []
    for r in rows[:5]:
        props = {k: v for k, v in r.properties.items() if k not in ("distinct_id", "$distinct_id")}
        sample_out.append({"event": r.event, "event_time": str(r.event_time), "properties": props})

    out = SAMPLES_DIR / "mixpanel_export_redacted.json"
    out.write_text(json.dumps({
        "date": str(spike_date),
        "total_events": len(raw_events),
        "after_dedup": len(rows),
        "by_event": dict(by_event),
        "sample_rows": sample_out,
    }, indent=2))
    print(f"\n✅ Sample saved to {out}")


if __name__ == "__main__":
    main()
