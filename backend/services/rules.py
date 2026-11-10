"""Recommendation rules engine. Read-only: produces suggestions, never writes to ad platforms."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CFG = Path(__file__).resolve().parents[2] / "config" / "rules.yml"
_SEVERITY_ORDER = {"critical": 0, "opportunity": 1, "info": 2}


def load_rules(path: Path = _CFG) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["rules"]


def build_recommendations(segmented: list[dict[str, Any]], rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rules = rules or load_rules()
    recs: list[dict[str, Any]] = []
    for r in rules:
        if "segment" in r:
            members = [p for p in segmented if p["segment"] == r["segment"]]
        elif r.get("condition") == "out_of_stock_with_spend":
            members = [p for p in segmented if p.get("availability") == "out of stock" and p["spend"] > 0]
        else:
            continue
        if not members:
            continue
        members.sort(key=lambda p: p["spend"], reverse=True)
        spend = sum(p["spend"] for p in members)
        recs.append({
            "rule_id": r["id"],
            "severity": r["severity"],
            "action": r["action"],
            "reason": r["reason"],
            "product_count": len(members),
            "spend_affected": spend,
            "revenue_affected": sum(p["revenue"] for p in members),
            "top_products": [
                {"product_key": p["product_key"], "retailer_id": p["retailer_id"],
                 "product_name": p["product_name"], "spend": p["spend"], "roas": p.get("roas")}
                for p in members[:5]
            ],
            "retailer_ids": [p["retailer_id"] for p in members],
        })
    recs.sort(key=lambda x: (_SEVERITY_ORDER.get(x["severity"], 9), -x["spend_affected"]))
    return recs


def pareto(products: list[dict[str, Any]], key: str = "spend") -> dict[str, Any]:
    """How concentrated is spend/revenue? Returns the cumulative curve and 'SKUs for 80%'."""
    vals = sorted((p[key] for p in products), reverse=True)
    total = sum(vals)
    if not total:
        return {"curve": [], "skus_for_80pct": 0, "share_of_skus_for_80pct": None}
    cum, curve, n80 = 0.0, [], None
    for i, v in enumerate(vals, 1):
        cum += v
        if n80 is None and cum / total >= 0.8:
            n80 = i
        if i % max(1, len(vals) // 50) == 0 or i == len(vals):
            curve.append({"sku_pct": i / len(vals), "cum_share": cum / total})
    return {"curve": curve, "skus_for_80pct": n80, "share_of_skus_for_80pct": (n80 or 0) / len(vals)}
