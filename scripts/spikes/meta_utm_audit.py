"""
scripts/spikes/meta_utm_audit.py  — P0.5
------------------------------------------
Spike: check what % of active catalog ads have utm_content={{ad.id}} in url_tags.
Attribution prerequisite P1 (DESIGN §5).

Run: python scripts/spikes/meta_utm_audit.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.meta.objects import audit_utm_coverage, snapshot_objects

setup_logging("INFO")

SAMPLES_DIR = Path(__file__).parent.parent.parent / "docs" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    cfg = get_settings()
    if not cfg.meta.is_configured():
        print("❌ Meta credentials not configured.")
        sys.exit(1)

    account_id = cfg.meta.ad_account_ids[0]
    print(f"\n⏳ Fetching ad objects for {account_id} ...")

    rows = snapshot_objects(account_id, snapshot_date=date.today())
    audit = audit_utm_coverage(rows)

    print("\n📊 UTM Coverage Audit:")
    print(f"   Total active ads:      {audit['total_active_ads']}")
    print(f"   With ad.id utm_content: {audit['with_ad_id_utm']}")
    print(f"   Coverage:              {audit['coverage_pct']}%")

    if audit.get("coverage_pct") is not None and audit["coverage_pct"] < 100:
        missing = audit["total_active_ads"] - audit["with_ad_id_utm"]
        print(f"\n⚠️  RISK: {missing} active ads missing ad ID in URL parameters.")
        print("   M1 and M2 attribution will be INCOMPLETE for these ads.")
        print("   No backfill possible for historical clicks without this parameter.")
        print("\n   FIX: In Ads Manager → Campaign → Ad Set → Ad → URL Parameters, add:")
        print("   utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}&utm_content={{ad.id}}")
        print("   (This fixes future clicks only — history cannot be recovered)")

    # Save
    out = SAMPLES_DIR / "meta_utm_audit.json"
    out.write_text(json.dumps(audit, indent=2))
    print(f"\n✅ Audit saved to {out}")
    print("📝 Record coverage_pct in 03_CONTEXT.md Verified Facts")


if __name__ == "__main__":
    main()
