"""
ingestion/common/sqlguard.py
-----------------------------
Read-only SQL guard shared by the API (backend/core/db.py) and the pipeline's DQ runner.
Accepts exactly ONE SELECT/WITH statement over an allowlist of schemas; everything else is rejected.
"""
from __future__ import annotations

import re

ALLOWED_SCHEMAS = frozenset({"mart", "ops"})
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|unload|call|"
    r"merge|vacuum|analyze|set|begin|commit|rollback|lock|execute|into)\b",
    re.IGNORECASE,
)
_SCHEMA_REF = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)", re.IGNORECASE)
# Any mention of a known schema / system catalog followed by a dot, ANYWHERE in the query. This closes the
# comma-join / subquery routes that a FROM/JOIN-only check misses (`FROM mart.a, raw_meta.b`).
_KNOWN_SCHEMAS = re.compile(
    r"\b(pg_\w+|stl_\w+|stv_\w+|svv_\w+|svl_\w+|sys_\w+|information_schema|public|"
    r"raw_meta|raw_mixpanel|stg|int|mart|ops)\s*\.",
    re.IGNORECASE,
)


class UnsafeQueryError(ValueError):
    pass


def validate_select(sql: str, allowed_schemas: frozenset[str] = ALLOWED_SCHEMAS) -> str:
    """Raise UnsafeQueryError unless sql is one read-only SELECT/WITH over allowed schemas (default: mart, ops)."""
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";").strip()
    if ";" in stripped:
        raise UnsafeQueryError("multiple statements are not allowed")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise UnsafeQueryError("only SELECT/WITH statements are allowed")
    if '"' in stripped or "`" in stripped:
        raise UnsafeQueryError("quoted identifiers are not allowed")  # would bypass the schema checks
    # Ignore string literals when scanning for forbidden keywords
    scan = re.sub(r"'[^']*'", "''", stripped)
    m = _FORBIDDEN.search(scan)
    if m:
        raise UnsafeQueryError(f"forbidden keyword: {m.group(1)}")
    for schema, _table in _SCHEMA_REF.findall(scan):
        if schema.lower() not in allowed_schemas:
            raise UnsafeQueryError(f"schema not allowed: {schema}")
    for (schema,) in [(m,) for m in _KNOWN_SCHEMAS.findall(scan)]:
        if schema.lower() not in allowed_schemas:
            raise UnsafeQueryError(f"schema not allowed: {schema}")
    return stripped
