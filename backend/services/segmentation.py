"""Product segmentation: Stars / Hidden Gems / Bleeders / Zombies (ROI-Hunter-style quadrants)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CFG = Path(__file__).resolve().parents[2] / "config" / "segments.yml"
SEGMENTS = ("Stars", "Hidden Gems", "Bleeders", "Zombies", "Insufficient data")


def load_config(path: Path = _CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def percentile_cont(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile — identical semantics to SQL percentile_cont (keeps API == dbt mart)."""
    if not sorted_values:
        return float("inf")
    pos = p * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def segment_products(products: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return products with a 'segment' key. Input rows need spend & roas."""
    cfg = cfg or load_config()
    min_spend = float(cfg["min_spend_for_classification"])
    target = float(cfg["target_roas"])
    spends = sorted(p["spend"] for p in products if p["spend"] >= min_spend)
    spend_cut = percentile_cont(spends, float(cfg["high_spend_percentile"]))

    out = []
    for p in products:
        if p["spend"] < min_spend:
            seg = "Insufficient data"
        else:
            high_spend = p["spend"] >= spend_cut
            high_roas = (p.get("roas") or 0) >= target
            seg = (
                "Stars" if high_spend and high_roas
                else "Bleeders" if high_spend
                else "Hidden Gems" if high_roas
                else "Zombies"
            )
        out.append({**p, "segment": seg})
    return out


def summarize(segmented: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_spend = sum(p["spend"] for p in segmented) or 1.0
    rows = []
    for s in SEGMENTS:
        members = [p for p in segmented if p["segment"] == s]
        spend = sum(p["spend"] for p in members)
        revenue = sum(p["revenue"] for p in members)
        rows.append({
            "segment": s,
            "products": len(members),
            "spend": spend,
            "revenue": revenue,
            "roas": revenue / spend if spend else None,
            "spend_share": spend / total_spend,
        })
    return rows
