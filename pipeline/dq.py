"""
pipeline/dq.py — daily data-quality runner. Writes every result to ops.dq_results (shown on the Data Health page).

Checks live in config/dq_checks.yml. Each is ONE read-only SELECT returning a single number; queries pass through
the shared SQL guard, so a bad/edited check can never write. Failing `error` checks make the pipeline exit non-zero.
"""
from __future__ import annotations

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from ingestion.common.models import DQResult, DQStatus
from ingestion.common.redshift import RedshiftLoader
from ingestion.common.sqlguard import validate_select
from ingestion.mixpanel.events import DEFAULT_PROPERTY_MAP

CHECKS_FILE = Path(__file__).resolve().parents[1] / "config" / "dq_checks.yml"
# DQ may inspect staging and raw layers too (the API may not): still SELECT-only.
DQ_SCHEMAS = frozenset({"mart", "ops", "stg", "int", "raw_meta", "raw_mixpanel"})
_OPS: dict[str, Callable[[Any, Any], bool]] = {"le": operator.le, "ge": operator.ge, "eq": operator.eq,
                                                "lt": operator.lt, "gt": operator.gt}
_PARAM = re.compile(r":(as_of|purchase_event)\b")


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str
    op: str
    threshold: float
    severity: str     # status on failure: "error" | "warn"
    on_null: str      # status when no data: "ok" | "warn" | "error"


def load_checks(path: Path = CHECKS_FILE) -> list[Check]:
    checks = []
    for c in yaml.safe_load(path.read_text())["checks"]:
        if c["op"] not in _OPS or c["severity"] not in ("error", "warn") or c.get("on_null", "warn") not in ("ok", "warn", "error"):
            raise ValueError(f"invalid DQ check definition: {c['name']}")
        validate_select(c["sql"].replace(":as_of", "%s").replace(":purchase_event", "%s"), DQ_SCHEMAS)  # fail fast on load
        checks.append(Check(c["name"], c.get("description", ""), c["sql"], c["op"], float(c["threshold"]),
                            c["severity"], c.get("on_null", "warn")))
    return checks


def _bind(sql: str, as_of: date) -> tuple[str, list[Any]]:
    """
    Replace :as_of / :purchase_event with %s (bound parameters, never interpolated).
    Literal % characters (e.g. LIKE '%ad.id%') are escaped as %% — the drivers treat bare % as a placeholder.
    """
    values = {"as_of": as_of, "purchase_event": DEFAULT_PROPERTY_MAP.purchase_event}
    params: list[Any] = []

    def sub(m: re.Match[str]) -> str:
        params.append(values[m.group(1)])
        return "%s"

    out = _PARAM.sub(sub, sql.replace("%", "%%"))
    return (out, params) if params else (sql, [])


def evaluate(check: Check, observed: Any) -> DQResult:
    if observed is None:
        return DQResult(check_name=check.name, status=DQStatus(check.on_null), observed=None,
                        threshold=Decimal(str(check.threshold)),
                        details={"description": check.description, "note": "no data to measure"})
    ok = _OPS[check.op](float(observed), check.threshold)
    return DQResult(check_name=check.name, status=DQStatus.OK if ok else DQStatus(check.severity),
                    observed=Decimal(str(round(float(observed), 6))), threshold=Decimal(str(check.threshold)),
                    details={"description": check.description, "op": check.op})


def run_checks(conn: Any, checks: list[Check], as_of: date) -> list[DQResult]:
    results: list[DQResult] = []
    for chk in checks:
        sql, params = _bind(chk.sql, as_of)
        safe = validate_select(sql, DQ_SCHEMAS)
        try:
            with conn.cursor() as cur:
                cur.execute(safe, params or None)
                row = cur.fetchone()
            results.append(evaluate(chk, row[0] if row else None))
        except Exception as exc:  # noqa: BLE001 — a broken check is itself a finding, not a crash
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001, S110
                pass
            results.append(DQResult(check_name=chk.name, status=DQStatus.ERROR, observed=None,
                                    threshold=Decimal(str(chk.threshold)),
                                    details={"description": chk.description, "check_failed_to_run": exc.__class__.__name__}))
    return results


def persist(loader: RedshiftLoader, results: list[DQResult]) -> None:
    for r in results:
        loader.write_dq_result(r)


def summarize(results: list[DQResult]) -> dict[str, Any]:
    by: dict[str, list[str]] = {"error": [], "warn": [], "ok": []}
    for r in results:
        by[r.status.value].append(r.check_name)
    return {"errors": by["error"], "warnings": by["warn"], "ok": by["ok"], "has_errors": bool(by["error"])}
