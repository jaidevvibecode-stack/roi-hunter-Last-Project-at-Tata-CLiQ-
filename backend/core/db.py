"""
backend/core/db.py
-------------------
Read-only Redshift access, enforced in code (defence in depth on top of the
read-only DB user the client must provision):
  * single SELECT/WITH statement only (run_select guard)
  * only mart / ops schemas may be referenced
  * session is READ ONLY with a statement timeout
  * parameterised queries only
"""
from __future__ import annotations

from typing import Any, Sequence

from backend.core.settings import get_settings
from ingestion.common.sqlguard import ALLOWED_SCHEMAS, UnsafeQueryError, validate_select  # noqa: F401  (re-exported)


def _connect() -> Any:
    """Open a READ-ONLY connection to the configured warehouse (Redshift in prod, Postgres in CI/compose)."""
    s = get_settings()
    password = s.redshift_password.get_secret_value()
    if s.warehouse_driver == "postgres":
        import psycopg2  # lazy: dev/CI dependency

        conn = psycopg2.connect(
            host=s.redshift_host, port=s.redshift_port, dbname=s.redshift_db, user=s.redshift_user,
            password=password, sslmode="require" if s.warehouse_ssl else "disable",
            connect_timeout=10,
            # search_path = our two readable schemas only: an unqualified table can never resolve to public/etc.
            options=f"-c statement_timeout={int(s.statement_timeout_ms)} -c search_path=mart,ops",
        )
        conn.set_session(readonly=True, autocommit=True)
        return conn

    import redshift_connector  # lazy: only needed when DATA_SOURCE=redshift

    conn = redshift_connector.connect(
        host=s.redshift_host, port=s.redshift_port, database=s.redshift_db, user=s.redshift_user,
        password=password, ssl=s.warehouse_ssl,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    cur.execute(f"SET statement_timeout TO {int(s.statement_timeout_ms)}")
    cur.execute("SET search_path TO mart, ops")
    return conn


def run_select(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Execute a validated read-only query; returns rows as dicts."""
    safe_sql = validate_select(sql)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(safe_sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()
