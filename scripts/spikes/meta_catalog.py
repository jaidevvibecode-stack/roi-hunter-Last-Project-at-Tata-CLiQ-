"""
scripts/spikes/meta_catalog.py  — P0.4
----------------------------------------
Spike: pull Meta catalog products and join to product_id values from Pull B.
Verifies: product_id_raw → meta_item_id → retailer_id parse rule.

Run: python scripts/spikes/meta_catalog.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.meta.catalog import snapshot_catalog

setup_logging("INFO")

SAMPLES_DIR = Path(__file__).parent.parent.parent / "docs" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    cfg = get_settings()
    if not cfg.meta.catalog_ids:
        print("❌ META_CATALOG_IDS not set in .env")
        sys.exit(1)

    catalog_id = cfg.meta.catalog_ids[0]
    print(f"\n⏳ Fetching first page of catalog {catalog_id} ...")

    rows = snapshot_catalog(catalog_id, snapshot_date=date.today())
    print(f"✅ Total products: {len(rows)}")

    if not rows:
        print("🔴 No products returned — check catalog ID and permissions")
        sys.exit(1)

    # Inspect ID formats
    sample_ids = [(r.id, r.retailer_id) for r in rows[:10]]
    print("\nF9 check — Sample (meta_item_id → retailer_id):")
    for mid, rid in sample_ids:
        print(f"  {mid!r} → {rid!r}")

    # Derive parse rule
    print("\n📝 Observe the meta_item_id format and write the parse rule in 03_CONTEXT.md.")
    print("   Common formats:")
    print("   - Numeric ID only (same as catalog item 'id' field)")
    print("   - 'g_{id}_{locale}' or '{id}|{name}' — inspect actual values above")

    # Save redacted sample (strip URLs/names)
    sample_out = []
    for r in rows[:10]:
        sample_out.append({
            "id": r.id,
            "retailer_id": "***" if r.retailer_id else "",
            "availability": r.availability,
            "currency": r.currency,
        })

    out = SAMPLES_DIR / "meta_catalog_redacted.json"
    out.write_text(json.dumps({
        "catalog_id": "REDACTED",
        "total_products": len(rows),
        "sample": sample_out,
    }, indent=2))
    print(f"\n✅ Sample saved to {out}")


if __name__ == "__main__":
    main()
