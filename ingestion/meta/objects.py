"""
ingestion/meta/objects.py
--------------------------
Daily snapshots of Meta ad objects: campaigns, ad sets, ads.
Also performs UTM audit (prerequisite P1 check from DESIGN §5).

DESIGN §7.2 → raw_meta.ads_snapshot.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from ingestion.common.models import RawAdSnapshotRow
from ingestion.common.retry import retry_meta
from ingestion.meta.client import get_ad_account

log = logging.getLogger(__name__)

CAMPAIGN_FIELDS = [
    "id", "name", "status", "effective_status", "objective", "created_time",
]
ADSET_FIELDS = [
    "id", "name", "status", "effective_status", "campaign_id",
    "promoted_object", "product_set_id", "created_time",
]
AD_FIELDS = [
    "id", "name", "status", "effective_status", "adset_id", "campaign_id",
    "creative", "url_tags", "created_time",
]


@retry_meta()
def _fetch_campaigns(account_id: str) -> list[dict[str, Any]]:
    acct = get_ad_account(account_id)
    return [dict(c) for c in acct.get_campaigns(fields=CAMPAIGN_FIELDS)]


@retry_meta()
def _fetch_adsets(account_id: str) -> list[dict[str, Any]]:
    acct = get_ad_account(account_id)
    return [dict(a) for a in acct.get_ad_sets(fields=ADSET_FIELDS)]


@retry_meta()
def _fetch_ads(account_id: str) -> list[dict[str, Any]]:
    acct = get_ad_account(account_id)
    return [dict(a) for a in acct.get_ads(fields=AD_FIELDS)]


def snapshot_objects(
    account_id: str,
    snapshot_date: date | None = None,
    run_id: str | None = None,
) -> list[RawAdSnapshotRow]:
    """
    Snapshot all campaigns, ad sets, and ads for one account.
    Returns list of RawAdSnapshotRow.
    """
    snapshot_date = snapshot_date or date.today()
    run_id = run_id or str(uuid.uuid4())

    rows: list[RawAdSnapshotRow] = []

    for campaign in _fetch_campaigns(account_id):
        rows.append(RawAdSnapshotRow(
            snapshot_date=snapshot_date,
            level="campaign",
            id=campaign.get("id", ""),
            parent_id=account_id,
            name=campaign.get("name", ""),
            status=campaign.get("status", ""),
            effective_status=campaign.get("effective_status", ""),
            objective=campaign.get("objective", ""),
            raw=campaign,
        ))

    for adset in _fetch_adsets(account_id):
        rows.append(RawAdSnapshotRow(
            snapshot_date=snapshot_date,
            level="adset",
            id=adset.get("id", ""),
            parent_id=adset.get("campaign_id", ""),
            name=adset.get("name", ""),
            status=adset.get("status", ""),
            effective_status=adset.get("effective_status", ""),
            product_set_id=adset.get("product_set_id", ""),
            raw=adset,
        ))

    for ad in _fetch_ads(account_id):
        rows.append(RawAdSnapshotRow(
            snapshot_date=snapshot_date,
            level="ad",
            id=ad.get("id", ""),
            parent_id=ad.get("adset_id", ""),
            name=ad.get("name", ""),
            status=ad.get("status", ""),
            effective_status=ad.get("effective_status", ""),
            url_tags=ad.get("url_tags", ""),
            raw=ad,
        ))

    log.info(
        "Objects snapshot complete",
        extra={"account_id": account_id, "rows": len(rows)},
    )
    return rows


def audit_utm_coverage(rows: list[RawAdSnapshotRow]) -> dict[str, Any]:
    """
    Check what % of active catalog ads have {{ad.id}} (or utm_content) in url_tags.
    Returns a dict with coverage stats for ops.dq_results.
    DESIGN §5 prerequisite P1.
    """
    ads = [r for r in rows if r.level == "ad" and r.effective_status == "ACTIVE"]
    total = len(ads)
    if total == 0:
        return {"total_active_ads": 0, "with_ad_id_utm": 0, "coverage_pct": None}

    with_utm = sum(
        1 for r in ads
        if "ad.id" in r.url_tags.lower() or "utm_content" in r.url_tags.lower()
    )
    coverage_pct = round(with_utm / total * 100, 2)

    if coverage_pct < 100:
        log.warning(
            "⚠️ UTM coverage below 100%% — M1/M2 attribution will be incomplete",
            extra={"coverage_pct": coverage_pct, "missing": total - with_utm},
        )
    return {
        "total_active_ads": total,
        "with_ad_id_utm": with_utm,
        "coverage_pct": coverage_pct,
        "fix": (
            "Add URL parameters in Ads Manager: "
            "utm_source=facebook&utm_medium=paid_social"
            "&utm_campaign={{campaign.id}}&utm_content={{ad.id}}"
        ),
    }
