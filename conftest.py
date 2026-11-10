"""
Shared test fixtures (single definition for the whole repo): a Postgres stand-in for Redshift, loaded with tests/fixtures/dataset.json and built with
the REAL dbt project. Skipped automatically when no Postgres is reachable (set TEST_PG_DSN to override).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
EXPECTED = json.loads((ROOT / "tests" / "fixtures" / "expected.json").read_text())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in str(item.fspath) or item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    psycopg2 = pytest.importorskip("psycopg2")
    from ingestion.testing.fixtures import dsn

    try:
        psycopg2.connect(dsn(), connect_timeout=3).close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres stand-in reachable ({exc.__class__.__name__}); set TEST_PG_DSN")
    return dsn()


@pytest.fixture(scope="session")
def warehouse(pg_dsn: str):  # type: ignore[no-untyped-def]
    """Fixtures loaded + `dbt build` completed. Yields a psycopg2 connection."""
    import psycopg2

    from ingestion.testing.fixtures import load

    conn = psycopg2.connect(pg_dsn)
    load(conn)
    conn.autocommit = True   # reads must never leave a transaction open (it would block dbt's DROP/CREATE)

    prof = Path(tempfile.mkdtemp(prefix="dbtprof_"))
    shutil.copy(ROOT / "transform" / "profiles.ci.yml", prof / "profiles.yml")
    dbt = Path(sys.executable).with_name("dbt")
    env = {**os.environ}
    # translate DSN pieces for profiles.ci.yml env_vars
    parts = dict(p.split("=", 1) for p in pg_dsn.split())
    env |= {"TEST_PG_HOST": parts.get("host", "localhost"), "TEST_PG_PORT": parts.get("port", "5432"),
            "TEST_PG_DB": parts.get("dbname", ""), "TEST_PG_USER": parts.get("user", ""),
            "TEST_PG_PASSWORD": parts.get("password", "")}
    common = ["--project-dir", str(ROOT / "transform"), "--profiles-dir", str(prof)]
    # fresh checkouts have no dbt_packages/ (it is downloaded, never committed): install them first (idempotent)
    deps = subprocess.run([str(dbt), "deps", *common], capture_output=True, text=True, env=env, cwd=ROOT / "transform", check=False)  # noqa: S603
    if deps.returncode != 0:
        pytest.fail("dbt deps failed (needs network access to the dbt package hub):\n" + deps.stdout[-2000:] + deps.stderr[-500:])
    cmd = [str(dbt), "build", "--full-refresh", "--project-dir", str(ROOT / "transform"),
           "--profiles-dir", str(prof), "--target-path", str(prof / "target"), "--log-path", str(prof / "logs"),
           "--vars", json.dumps(EXPECTED["segments_vars"])]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT / "transform", check=False)  # noqa: S603
    if res.returncode != 0:
        pytest.fail("dbt build failed on fixtures:\n" + res.stdout[-4000:] + res.stderr[-1000:])
    yield conn
    conn.close()


@pytest.fixture
def rows(warehouse):  # type: ignore[no-untyped-def]
    def _q(sql: str, params: tuple = ()) -> list[tuple]:  # type: ignore[type-arg]
        with warehouse.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return _q


@pytest.fixture
def redshift_env(monkeypatch: pytest.MonkeyPatch, pg_dsn: str):  # type: ignore[no-untyped-def]
    """Point the backend's production data source at the Postgres stand-in."""
    from backend.core.settings import get_settings

    parts = dict(p.split("=", 1) for p in pg_dsn.split())
    for k, v in {
        "ENV": "local", "DATA_SOURCE": "redshift", "WAREHOUSE_DRIVER": "postgres", "WAREHOUSE_SSL": "false",
        "REDSHIFT_HOST": parts.get("host", "localhost"), "REDSHIFT_PORT": parts.get("port", "5432"),
        "REDSHIFT_DB": parts.get("dbname", ""), "REDSHIFT_USER": parts.get("user", ""),
        "REDSHIFT_PASSWORD": parts.get("password", ""),
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
