from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.v1.export import safe_cell, stream_csv
from backend.core.auth import hash_password
from backend.core.db import UnsafeQueryError, validate_select
from backend.core.settings import Settings, get_settings
from backend.main import create_app
from backend.queries.common import CommonFilters, validate_sort_column


# ── fail-closed settings ──────────────────────────────────────────────────────
def test_prod_rejects_no_auth():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="prod", app_auth_method="none", data_source="redshift")


def test_prod_rejects_demo_and_wildcards():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="prod", app_auth_method="basic", app_auth_basic_user="u",
                 app_auth_basic_password_hash=hash_password("x"), app_secret_key="k" * 40,
                 data_source="demo")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="staging", cors_origins="*")


def test_basic_requires_bcrypt_hash_not_plaintext():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_auth_method="basic", app_auth_basic_user="u",
                 app_auth_basic_password_hash="plaintext-password")


# ── auth ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def secured(monkeypatch, window):
    monkeypatch.setenv("APP_AUTH_METHOD", "basic")
    monkeypatch.setenv("APP_AUTH_BASIC_USER", "tata")
    monkeypatch.setenv("APP_AUTH_BASIC_PASSWORD_HASH", hash_password("s3cret!"))
    get_settings.cache_clear()
    yield TestClient(create_app()), window
    get_settings.cache_clear()


def test_auth_enforced(secured):
    c, w = secured
    assert c.get("/health").status_code == 200
    assert c.get(f"/api/v1/overview?{w}").status_code == 401
    assert c.get(f"/api/v1/overview?{w}", auth=("tata", "wrong")).status_code == 401
    assert c.get(f"/api/v1/overview?{w}", auth=("evil", "s3cret!")).status_code == 401
    assert c.get(f"/api/v1/overview?{w}", auth=("tata", "s3cret!")).status_code == 200


# ── headers / limits ──────────────────────────────────────────────────────────
def test_security_headers(client):
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]


def test_long_param_rejected(client, window):
    assert client.get(f"/api/v1/products?{window}&search={'a' * 500}").status_code in (414, 422)


def test_untrusted_host_rejected(client):
    assert client.get("/health", headers={"host": "evil.example.com"}).status_code == 400


def test_rate_limit(monkeypatch, window):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "5")
    get_settings.cache_clear()
    c = TestClient(create_app())
    codes = [c.get(f"/api/v1/trends?{window}").status_code for _ in range(8)]
    get_settings.cache_clear()
    assert 429 in codes


def test_errors_do_not_leak_internals(client, window, monkeypatch):
    from backend.data.demo_source import DemoDataSource

    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(DemoDataSource, "overview", boom)
    c = TestClient(create_app(), raise_server_exceptions=False)
    r = c.get(f"/api/v1/overview?{window}")
    assert r.status_code == 500 and "secret-internal-detail" not in r.text


# ── SQL injection / read-only guard ───────────────────────────────────────────
@pytest.mark.parametrize("bad", ["spend; DROP TABLE x", "spend desc, (select 1)", "1=1", "revenue--", "' OR '1'='1"])
def test_sort_whitelist(client, window, bad):
    from urllib.parse import quote

    assert client.get(f"/api/v1/products?{window}&sort={quote(bad)}").status_code == 400
    with pytest.raises(ValueError):
        validate_sort_column(bad)


def test_search_is_parameterised_not_interpolated():
    f = CommonFilters(start_date="2026-01-01", end_date="2026-01-31", search="x'; DROP TABLE a;--")  # type: ignore[arg-type]
    sql, params = f.build_where_clause()
    assert "drop" not in sql.lower() and any("drop table" in str(p) for p in params)


def test_search_like_wildcards_escaped():
    f = CommonFilters(start_date="2026-01-01", end_date="2026-01-31", search="50%_off")  # type: ignore[arg-type]
    _, params = f.build_where_clause()
    assert "50\\%\\_off" in params[-1]


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE mart.x", "DELETE FROM mart.x", "INSERT INTO mart.x VALUES (1)",
    "UPDATE mart.x SET a=1", "SELECT * FROM raw_meta.ad_insights", "SELECT * FROM pg_catalog.pg_user",
    "COPY mart.x FROM 's3://b'", "SELECT * INTO mart.y FROM mart.x", "CREATE TABLE mart.z (a int)",
    "SET search_path TO raw_meta", "/* hi */ DROP TABLE mart.x", "WITH a AS (SELECT 1) DELETE FROM mart.x",
])
def test_db_guard_blocks(sql):
    with pytest.raises(UnsafeQueryError):
        validate_select(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM mart.dim_product WHERE x = %s",
    "WITH a AS (SELECT 1) SELECT * FROM a JOIN ops.dq_results d ON 1=1",
    "SELECT 'DROP TABLE' AS note FROM mart.dim_product;",
])
def test_db_guard_allows_readonly(sql):
    assert validate_select(sql)


def test_all_redshift_source_sql_passes_guard(monkeypatch):
    """Every query the Redshift source issues must pass the read-only guard."""
    from datetime import date

    import backend.data.redshift_source as rs

    seen: list[str] = []

    def fake(sql, params=()):
        validate_select(sql)
        seen.append(sql)
        return []

    monkeypatch.setattr(rs, "run_select", fake)
    src = rs.RedshiftDataSource()
    f = CommonFilters(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), brands=["a"], categories=["b"],
                      campaign_ids=["c"], search="s")
    src.product_aggregates(f); src.daily_series(f, "k"); src.breakdown(f, "k", "ad")
    src.filter_options(f); src.attribution_matrix(f); src.unallocated_spend(f)
    src.data_quality(); src.freshness()
    assert len(seen) >= 10


# ── CSV injection ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", ["=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd"])
def test_csv_formula_neutralised(v):
    assert safe_cell(v).startswith("'")


def test_csv_stream_neutralises_rows():
    out = "".join(stream_csv(iter([{"product_name": "=cmd|' /C calc'!A0", "spend": 5}])))
    assert "'=cmd" in out


def test_prod_rejects_postgres_stand_in():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="prod", app_auth_method="basic", app_auth_basic_user="u",
                 app_auth_basic_password_hash=hash_password("x"), app_secret_key="k" * 40,
                 data_source="redshift", redshift_host="h", redshift_db="d", redshift_user="u",
                 warehouse_driver="postgres")


# ── SQL guard hardening (reviewer findings) ───────────────────────────────────
@pytest.mark.parametrize("sql", [
    "SELECT * FROM mart.dim_product a, raw_meta.ad_insights_daily b",                       # comma join
    "SELECT * FROM mart.dim_product WHERE x IN (SELECT ad_id FROM public.orders)",           # subquery
    'SELECT * FROM "raw_meta"."ad_insights_daily"',                                          # quoted identifiers
    "SELECT * FROM mart.dim_product, pg_catalog.pg_user",
])
def test_guard_blocks_comma_joins_subqueries_quoted_identifiers(sql):
    with pytest.raises(UnsafeQueryError):
        validate_select(sql)


def test_guard_still_allows_aliased_columns():
    validate_select("SELECT m.spend, d.brand FROM mart.product_performance_daily m JOIN mart.dim_product d ON d.product_key = m.product_key")


# ── lookback honesty ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("lb", [1, 28, 0, 99])
def test_unsupported_lookback_is_refused_not_faked(client, window, lb):
    r = client.get(f"/api/v1/overview?{window}&lookback_days={lb}")
    assert r.status_code == 422 and "lookback_days must be one of" in r.json()["detail"]


def test_supported_lookbacks_match_the_dbt_mart():
    import yaml

    from backend.queries.common import SUPPORTED_LOOKBACK_DAYS

    v = yaml.safe_load((__import__("pathlib").Path(__file__).resolve().parents[2] / "transform" / "dbt_project.yml").read_text())["vars"]
    assert SUPPORTED_LOOKBACK_DAYS == (v["default_lookback_days"],)


# ── rate limiter behind a proxy ───────────────────────────────────────────────
def _limited_client(monkeypatch, trust: bool):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true" if trust else "false")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_forwarded_for_ignored_by_default_so_it_cannot_be_spoofed(monkeypatch, window):
    c = _limited_client(monkeypatch, trust=False)
    codes = [c.get(f"/api/v1/trends?{window}", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(6)]
    get_settings.cache_clear()
    assert 429 in codes                      # rotating the header did not dodge the limit


def test_each_real_client_gets_its_own_bucket_when_proxy_is_trusted(monkeypatch, window):
    c = _limited_client(monkeypatch, trust=True)
    a = [c.get(f"/api/v1/trends?{window}", headers={"X-Forwarded-For": "10.0.0.1"}).status_code for _ in range(5)]
    b = c.get(f"/api/v1/trends?{window}", headers={"X-Forwarded-For": "10.0.0.2"}).status_code
    bad = c.get(f"/api/v1/trends?{window}", headers={"X-Forwarded-For": "not-an-ip"}).status_code   # falls back, no crash
    get_settings.cache_clear()
    assert 429 in a and b == 200 and bad in (200, 429)


def test_rate_limit_memory_is_bounded():
    from backend.core.security import SecurityMiddleware

    mw = SecurityMiddleware(app=lambda *a: None, rate_limit_per_minute=5, max_param_len=100)  # type: ignore[arg-type]
    mw.MAX_TRACKED_CLIENTS = 50
    for i in range(300):
        mw._rate_limited(f"1.1.{i // 250}.{i % 250}")
        mw._hits[f"1.1.{i // 250}.{i % 250}"].clear()      # idle clients
    assert len(mw._hits) <= 60
