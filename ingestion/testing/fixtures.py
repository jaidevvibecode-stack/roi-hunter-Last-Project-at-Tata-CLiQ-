"""
ingestion/testing/fixtures.py
------------------------------
Load tests/fixtures/dataset.json into a *Postgres stand-in* warehouse (CI / docker smoke stack ONLY).
Never point this at a client warehouse: it TRUNCATES the owned raw_* / ops tables.

  python -m ingestion.testing.fixtures      # uses TEST_PG_DSN (default: local roi_hunter_ci)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from ingestion.common.ddl import TABLES, generate_ddl

DATASET = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "dataset.json"
DEFAULT_DSN = "host=localhost port=5432 dbname=roi_hunter_ci user=roi_ci password=roi_ci_test_only"


def dsn() -> str:
    return os.environ.get("TEST_PG_DSN", DEFAULT_DSN)


def load(conn: Any, dataset: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, int]:
    """Create owned schemas (postgres dialect), truncate, insert. Returns rows loaded per table."""
    data = dataset or json.loads(DATASET.read_text())
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute(generate_ddl("postgres"))
        for table, rows in data.items():
            if table not in TABLES:
                raise KeyError(f"unknown fixture table {table}")
            cur.execute(f"TRUNCATE {table}")  # noqa: S608  # nosec B608 — table validated against TABLES
            if not rows:
                continue
            cols = list(rows[0])
            values = [
                tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in (r[c] for c in cols))
                for r in rows
            ]
            execute_values(
                cur,
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s",  # noqa: S608  # nosec B608
                values,
            )
            counts[table] = len(rows)
    conn.commit()
    return counts


if __name__ == "__main__":
    c = psycopg2.connect(dsn())
    try:
        print(load(c))
    finally:
        c.close()
