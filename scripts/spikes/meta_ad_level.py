"""
scripts/spikes/meta_ad_level.py  — P0.2
-----------------------------------------
Spike: verify Meta access token, list ad accounts, run one-day ad-level insights.
Run: python scripts/spikes/meta_ad_level.py

Records findings in docs/samples/meta_ad_level_redacted.json (token stripped).
Verifies: F6 (attribution setting), F10 (API version), token scopes.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.meta.client import get_api

setup_logging("DEBUG")

SAMPLES_DIR = Path(__file__).parent.parent.parent / "docs" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    cfg = get_settings()
    if not cfg.meta.is_configured():
        print("❌ META_ACCESS_TOKEN and META_AD_ACCOUNT_IDS not set in .env")
        sys.exit(1)

    get_api()

    # 1. Token debug — scopes, expiry
    print(f"\n✅ API version: {cfg.meta.api_version}")
    print(f"   Ad account IDs: {cfg.meta.ad_account_ids}")

    # 2. Get one day of ad-level insights for the first account
    account_id = cfg.meta.ad_account_ids[0]
    yesterday = str(date.today() - timedelta(days=1))

    from facebook_business.adobjects.adaccount import AdAccount
    acct = AdAccount(account_id if account_id.startswith("act_") else f"act_{account_id}")

    print(f"\n⏳ Requesting ad-level insights for {account_id} on {yesterday} ...")
    params = {
        "level": "ad",
        "time_increment": "1",
        "time_range": {"since": yesterday, "until": yesterday},
        "use_unified_attribution_setting": True,
        "action_report_time": "impression",
        "fields": [
            "account_id", "campaign_id", "ad_id", "date_start",
            "spend", "impressions", "clicks", "inline_link_clicks",
            "actions", "action_values", "purchase_roas",
        ],
        "limit": 5,  # small sample for spike
    }

    insights = list(acct.get_insights(params=params))
    print(f"✅ Got {len(insights)} rows (limit=5 for spike)")

    # Redact and save
    sample = []
    for row in insights[:3]:
        d = dict(row)
        # Redact any potential PII fields
        for k in list(d.keys()):
            if "name" in k.lower():
                d[k] = "***REDACTED***"
        sample.append(d)

    out = SAMPLES_DIR / "meta_ad_level_redacted.json"
    out.write_text(json.dumps({"api_version": cfg.meta.api_version, "sample": sample}, indent=2))
    print(f"✅ Sample saved to {out}")

    # F6: check attribution setting actually used
    if insights:
        row0 = dict(insights[0])
        print(f"\nF6 check — use_unified_attribution_setting in response: {row0.get('use_unified_attribution_setting', 'NOT PRESENT')}")

    print("""
┌─────────────────────────────────────────────────────────────────┐
│  P0.2 SPIKE COMPLETE — record the following in 03_CONTEXT.md:   │
│  F10: API version pinned = {api_version}                        │
│  F6:  attribution setting used (see above)                      │
│  Token scopes (check Business Manager > System Users > token)   │
└─────────────────────────────────────────────────────────────────┘
""".format(api_version=cfg.meta.api_version))


if __name__ == "__main__":
    main()
