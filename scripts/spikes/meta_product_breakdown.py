"""
scripts/spikes/meta_product_breakdown.py  — P0.3
--------------------------------------------------
Spike: verify Meta product_id breakdown works for catalog ads.
Verifies: F1, F2, F3, F9 (product_id value format).
Compares Σ product spend vs ad-level spend for same date.

Run: python scripts/spikes/meta_product_breakdown.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging

setup_logging("INFO")

SAMPLES_DIR = Path(__file__).parent.parent.parent / "docs" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    cfg = get_settings()
    if not cfg.meta.is_configured():
        print("❌ Meta credentials not configured.")
        sys.exit(1)

    from facebook_business.adobjects.adaccount import AdAccount

    from ingestion.meta.client import get_api
    get_api()

    account_id = cfg.meta.ad_account_ids[0]
    acct = AdAccount(account_id if account_id.startswith("act_") else f"act_{account_id}")
    yesterday = str(date.today() - timedelta(days=1))

    print(f"\n⏳ Pull A: ad-level spend for {account_id} on {yesterday} ...")
    ad_level = list(acct.get_insights(params={
        "level": "ad",
        "time_increment": "1",
        "time_range": {"since": yesterday, "until": yesterday},
        "use_unified_attribution_setting": True,
        "fields": ["ad_id", "spend", "impressions", "inline_link_clicks"],
        "limit": 500,
    }))
    ad_level_total = sum(Decimal(r.get("spend", "0") or "0") for r in ad_level)
    print(f"   Ad-level rows: {len(ad_level)}, total spend: {ad_level_total}")

    print(f"\n⏳ Pull B: product breakdown for {account_id} on {yesterday} ...")
    try:
        product_level = list(acct.get_insights(params={
            "level": "ad",
            "time_increment": "1",
            "time_range": {"since": yesterday, "until": yesterday},
            "use_unified_attribution_setting": True,
            "breakdowns": ["product_id"],
            "fields": ["ad_id", "spend", "impressions", "inline_link_clicks",
                       "actions", "action_values"],
            "limit": 500,
        }))
    except Exception as exc:
        print(f"\n🔴 Pull B FAILED: {exc}")
        print("   → Are there catalog/DPA ads in this account?")
        print("   → Does the system user have catalog read permission?")
        sys.exit(1)

    product_level_total = sum(Decimal(r.get("spend", "0") or "0") for r in product_level)
    print(f"   Product-level rows: {len(product_level)}, total spend: {product_level_total}")

    # F3: gap
    gap = ad_level_total - product_level_total
    gap_pct = float(gap / ad_level_total * 100) if ad_level_total else 0
    print(f"\nF3 — Unallocated spend: {gap:.6f} ({gap_pct:.2f}%)")

    # F2: check if actions/action_values have values at product level
    has_actions = any(r.get("actions") for r in product_level[:10])
    has_action_values = any(r.get("action_values") for r in product_level[:10])
    print(f"F2 — product-level actions present: {has_actions} (should be False/empty)")
    print(f"F2 — product-level action_values present: {has_action_values} (should be False/empty)")

    # F9: product_id value format
    if product_level:
        sample_ids = [r.get("product_id", "") for r in product_level[:5]]
        print(f"\nF9 — Sample product_id values: {sample_ids}")
        print("     → Record the format in 03_CONTEXT.md F9")

    # Save redacted sample
    sample_rows = []
    for r in product_level[:5]:
        d = dict(r)
        sample_rows.append(d)

    out = SAMPLES_DIR / "meta_product_breakdown_redacted.json"
    out.write_text(json.dumps({
        "account_id": "act_REDACTED",
        "date": yesterday,
        "ad_level_total_spend": str(ad_level_total),
        "product_level_total_spend": str(product_level_total),
        "unallocated_spend": str(gap),
        "unallocated_pct": gap_pct,
        "f2_actions_at_product_level": has_actions,
        "f9_sample_product_ids": sample_ids,
        "sample_rows": sample_rows,
    }, indent=2))
    print(f"\n✅ Sample saved to {out}")
    print("\n📝 Update 03_CONTEXT.md: F1, F2, F3, F9 — mark ✅ for each verified fact.")


if __name__ == "__main__":
    main()
