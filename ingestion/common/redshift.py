"""
ingestion/common/redshift.py
-----------------------------
Redshift loader: S3 COPY (primary) with batched INSERT fallback.
Also writes to ops.ingestion_runs and ops.ingestion_checkpoints.

We ONLY write to schemas we own: raw_meta, raw_mixpanel, ops.
We NEVER touch existing customer schemas.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

import redshift_connector

from ingestion.common.models import (
    DQResult,
    IngestionCheckpoint,
    IngestionRun,
)

log = logging.getLogger(__name__)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
# Schemas this project owns and may write to. Existing Tata schemas are NEVER written.
WRITABLE_SCHEMAS = frozenset({"raw_meta", "raw_mixpanel", "ops"})


_S3_URI = re.compile(r"^s3://[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]/[A-Za-z0-9!_.*'()/=\-]+$")
_IAM_ARN = re.compile(r"^arn:aws(-[a-z]+)*:iam::\d{12}:role/[\w+=,.@/\-]+$")


def _check_copy_inputs(s3_uri: str, iam_role_arn: str) -> None:
    """COPY cannot bind parameters, so the S3 URI / IAM role are strictly validated before interpolation."""
    if not _S3_URI.match(s3_uri):
        raise ValueError(f"invalid s3 uri: {s3_uri!r}")
    if not _IAM_ARN.match(iam_role_arn):
        raise ValueError("invalid IAM role ARN")


def _check_write_target(table: str, columns: list[str]) -> None:
    """Reject anything but owned-schema, plain-identifier tables/columns (blocks SQL injection & stray writes)."""
    parts = table.split(".")
    if len(parts) != 2 or not all(_IDENT.match(p) for p in parts):
        raise ValueError(f"table must be schema-qualified plain identifiers: {table!r}")
    if parts[0] not in WRITABLE_SCHEMAS:
        raise PermissionError(f"writes only allowed to {sorted(WRITABLE_SCHEMAS)}, not {parts[0]!r}")
    bad = [c for c in columns if not _IDENT.match(c)]
    if bad:
        raise ValueError(f"invalid column identifiers: {bad}")



def get_connection(
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> redshift_connector.Connection:
    """Open a Redshift connection. Caller is responsible for closing it."""
    return redshift_connector.connect(
        host=host,
        port=port,
        database=db,
        user=user,
        password=password,
        ssl=True,
        timeout=30,
    )


class RedshiftLoader:
    """
    Load records into Redshift via S3 COPY (preferred) or batched INSERT fallback.
    """

    def __init__(
        self,
        conn: redshift_connector.Connection,
        iam_role_arn: str = "",
    ) -> None:
        self._conn = conn
        self._iam_role_arn = iam_role_arn

    # ── COPY from S3 ─────────────────────────────────────────────────────────

    def copy_from_s3(
        self,
        table: str,
        s3_uri: str,
        columns: list[str] | None = None,
    ) -> int:
        """
        COPY a Parquet file from S3 into `table`.
        `table` must be schema-qualified, e.g. 'raw_meta.ad_insights_daily'.
        Returns approximate row count from stl_load_commits.
        """
        if not self._iam_role_arn:
            raise ValueError(
                "iam_role_arn is required for COPY. "
                "Set REDSHIFT_IAM_ROLE_ARN in .env or fall back to batched INSERT."
            )

        _check_write_target(table, columns or [])
        _check_copy_inputs(s3_uri, self._iam_role_arn)
        col_clause = f"({', '.join(columns)})" if columns else ""
        sql = f"""
            COPY {table} {col_clause}
            FROM '{s3_uri}'
            IAM_ROLE '{self._iam_role_arn}'
            FORMAT AS PARQUET
            COMPUPDATE OFF
            STATUPDATE OFF
        """  # noqa: S608  # nosec B608 — table/columns/uri/arn validated above
        with self._conn.cursor() as cur:
            log.info("COPY from S3", extra={"table": table, "s3_uri": s3_uri})
            cur.execute(sql)
            self._conn.commit()

        # Best-effort row count
        return self._last_copy_rows(table)

    def _last_copy_rows(self, table: str) -> int:
        schema, tbl = (table.split(".", 1) + [""])[:2]
        sql = """
            SELECT NVL(SUM(lines_scanned), 0)
            FROM stl_load_commits
            WHERE schema_name = %s AND table_name = %s
              AND query = pg_last_query_id()
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (schema, tbl))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ── Batched INSERT fallback ───────────────────────────────────────────────

    def insert_batch(
        self,
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        batch_size: int = 1000,
    ) -> int:
        """
        Insert rows in batches using parameterised SQL.
        `table` must be schema-qualified.
        Returns total rows inserted.
        """
        if not rows:
            return 0

        _check_write_target(table, columns)
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)
        # Identifiers validated by _check_write_target; values are bound parameters.
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"  # noqa: S608  # nosec B608

        total = 0
        with self._conn.cursor() as cur:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                cur.executemany(sql, batch)
                total += len(batch)
            self._conn.commit()

        log.info("Batch INSERT complete", extra={"table": table, "rows": total})
        return total

    # ── Ops writers ───────────────────────────────────────────────────────────

    def _replace_row(self, table: str, key_sql: str, key_params: tuple[Any, ...], columns: list[str],
                     values: tuple[Any, ...]) -> None:
        """Portable upsert: DELETE then INSERT in ONE transaction (Redshift does not support ON CONFLICT)."""
        _check_write_target(table, columns)
        placeholders = ", ".join(["%s"] * len(columns))
        with self._conn.cursor() as cur:
            try:
                delete_sql = f"DELETE FROM {table} WHERE {key_sql}"  # noqa: S608  # nosec B608
                insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608  # nosec B608
                cur.execute(delete_sql, key_params)
                cur.execute(insert_sql, values)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def upsert_run(self, run: IngestionRun) -> None:
        """Insert or replace a row in ops.ingestion_runs (keyed by run_id)."""
        self._replace_row(
            "ops.ingestion_runs", "run_id = %s", (run.run_id,),
            ["run_id", "source", "started_at", "finished_at", "status", "date_from", "date_to",
             "rows_loaded", "error"],
            (run.run_id, run.source, run.started_at, run.finished_at, run.status.value,
             run.date_from, run.date_to, run.rows_loaded, run.error),
        )

    def upsert_checkpoint(self, cp: IngestionCheckpoint) -> None:
        self._replace_row(
            "ops.ingestion_checkpoints", "source = %s AND account_id = %s AND chunk_key = %s",
            (cp.source, cp.account_id, cp.chunk_key),
            ["source", "account_id", "chunk_key", "date", "status", "updated_at"],
            (cp.source, cp.account_id, cp.chunk_key, cp.date, cp.status.value, cp.updated_at),
        )

    def checkpoint_done(self, source: str, account_id: str, chunk_key: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM ops.ingestion_checkpoints WHERE source = %s AND account_id = %s AND chunk_key = %s",
                (source, account_id, chunk_key),
            )
            row = cur.fetchone()
        return bool(row and row[0] == "done")

    def write_dq_result(self, result: DQResult) -> None:
        sql = """
            INSERT INTO ops.dq_results
                (check_name, run_at, status, observed, threshold, details)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    result.check_name, result.run_at, result.status.value,
                    float(result.observed) if result.observed is not None else None,
                    float(result.threshold) if result.threshold is not None else None,
                    json.dumps(result.details, default=str),
                ),
            )
            self._conn.commit()

    # ── Idempotent partition load ─────────────────────────────────────────────

    def replace_partition(
        self,
        table: str,
        date_column: str,
        start: date | datetime,
        end: date | datetime,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        extra_filter: tuple[str, str] | None = None,
    ) -> int:
        """
        Idempotent load: delete [start, end] (optionally only `extra_filter=(column, value)`, e.g. one ad
        account) then insert `rows`, atomically. Re-running with the same input yields the same table state.
        """
        _check_write_target(table, [date_column, *columns, *([extra_filter[0]] if extra_filter else [])])
        where = f"{date_column} >= %s AND {date_column} <= %s"
        params: list[Any] = [start, end]
        if extra_filter:
            where += f" AND {extra_filter[0]} = %s"
            params.append(extra_filter[1])
        placeholders = ", ".join(["%s"] * len(columns))
        with self._conn.cursor() as cur:
            try:
                delete_sql = f"DELETE FROM {table} WHERE {where}"  # noqa: S608  # nosec B608
                insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608  # nosec B608
                cur.execute(delete_sql, params)
                if rows:
                    cur.executemany(insert_sql, rows)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return len(rows)

    def replace_partition_via_s3(
        self,
        table: str,
        date_column: str,
        start: date | datetime,
        end: date | datetime,
        s3_uri: str,
        columns: list[str],
        extra_filter: tuple[str, str] | None = None,
    ) -> None:
        """Bulk path for Redshift: DELETE the partition then COPY the Parquet file, in ONE transaction."""
        _check_write_target(table, [date_column, *columns, *([extra_filter[0]] if extra_filter else [])])
        _check_copy_inputs(s3_uri, self._iam_role_arn)
        where = f"{date_column} >= %s AND {date_column} <= %s"
        params: list[Any] = [start, end]
        if extra_filter:
            where += f" AND {extra_filter[0]} = %s"
            params.append(extra_filter[1])
        delete_sql = f"DELETE FROM {table} WHERE {where}"  # noqa: S608  # nosec B608 — identifiers validated
        copy_sql = (  # noqa: S608  # nosec B608 — identifiers/uri/arn validated above
            f"COPY {table} ({', '.join(columns)}) FROM '{s3_uri}' IAM_ROLE '{self._iam_role_arn}' "
            "FORMAT AS PARQUET COMPUPDATE OFF STATUPDATE OFF"
        )
        with self._conn.cursor() as cur:
            try:
                cur.execute(delete_sql, params)
                cur.execute(copy_sql)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def distinct_values(self, table: str, column: str, day: date, account_id: str,
                        where_eq: tuple[str, str] | None = None) -> list[str]:
        """Distinct ids already loaded for (day, account) — used to split oversized Meta reports."""
        _check_write_target(table, [column, *([where_eq[0]] if where_eq else [])])
        sql = f"SELECT DISTINCT {column} FROM {table} WHERE date_start = %s AND account_id = %s"  # noqa: S608  # nosec B608
        params: list[Any] = [day, account_id]
        if where_eq:
            sql += f" AND {where_eq[0]} = %s"
            params.append(where_eq[1])
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return sorted(str(r[0]) for r in cur.fetchall() if r[0])

    # ── Bootstrap of OWNED schemas (explicit approval only) ───────────────────

    def bootstrap_owned_schemas(self, dialect: str = "redshift", *, approved: bool = False) -> None:
        """Create raw_meta / raw_mixpanel / ops tables. Refuses to run without explicit approval."""
        if not approved:
            raise PermissionError(
                "Creating schemas in the client warehouse needs explicit approval (plan P0.7). "
                "Pass approved=True / --i-have-approval after the owner signs off."
            )
        from ingestion.common.ddl import generate_ddl

        with self._conn.cursor() as cur:
            for stmt in [s for s in generate_ddl(dialect).split(";") if s.strip()]:
                cur.execute(stmt)
        self._conn.commit()
