"""DQ runner on the dbt-built fixture warehouse (integration) + pure logic tests."""
from __future__ import annotations

from datetime import date

import pytest

from ingestion.common.models import DQStatus
from ingestion.common.redshift import RedshiftLoader
from ingestion.common.sqlguard import UnsafeQueryError
from pipeline import dq


def test_all_configured_checks_load_and_pass_the_sql_guard():
    checks = dq.load_checks()
    assert len(checks) >= 9 and len({c.name for c in checks}) == len(checks)


def test_edited_check_that_writes_is_rejected(tmp_path):
    bad = tmp_path / "c.yml"
    bad.write_text("checks:\n  - {name: x, sql: 'delete from mart.dim_product', op: eq, threshold: 0, severity: error}\n")
    with pytest.raises(UnsafeQueryError):
        dq.load_checks(bad)


@pytest.mark.parametrize("op,thr,obs,status", [("le", 2, 1, "ok"), ("le", 2, 3, "warn"), ("ge", 0.95, 0.9, "warn"), ("eq", 0, 0, "ok"), ("eq", 0, 1, "warn")])
def test_comparators(op, thr, obs, status):
    c = dq.Check("t", "", "select 1", op, thr, "warn", "warn")
    assert dq.evaluate(c, obs).status == DQStatus(status)


def test_null_uses_on_null_and_severity_error_is_error():
    c = dq.Check("t", "", "select 1", "le", 2, "error", "error")
    assert dq.evaluate(c, None).status == DQStatus.ERROR and dq.evaluate(c, 5).status == DQStatus.ERROR
    assert dq.evaluate(dq.Check("t", "", "x", "le", 2, "error", "ok"), None).status == DQStatus.OK


def test_literal_percent_signs_survive_parameter_binding():
    sql, params = dq._bind("select 1 where x like '%ad.id%' and d = :as_of", date(2026, 3, 4))
    assert "like '%%ad.id%%'" in sql and sql.endswith("d = %s") and len(params) == 1
    assert dq._bind("select 1 where x like '%a%'", date(2026, 3, 4)) == ("select 1 where x like '%a%'", [])


def test_params_are_bound_not_interpolated():
    sql, params = dq._bind("select :as_of, :purchase_event, :as_of", date(2026, 3, 4))
    assert sql == "select %s, %s, %s" and params[0] == date(2026, 3, 4) and params[2] == date(2026, 3, 4)


@pytest.mark.integration
class TestOnFixtureWarehouse:
    """Expected statuses are derived by hand from tests/fixtures/dataset.json (see comments)."""

    @pytest.fixture
    def run(self, warehouse):
        def _run(as_of: date):
            return {r.check_name: r for r in dq.run_checks(warehouse, dq.load_checks(), as_of)}
        return _run

    def test_known_fixture_state(self, run):
        r = run(date(2026, 3, 4))   # one day after the fixture data ends
        want = {
            "freshness_meta_days": ("ok", 1),                          # 03-04 minus latest data date 03-03
            "catalog_snapshot_age_days": ("ok", 1),
            "spend_id_match_rate": ("ok", 650 / 660),                  # 10 of 660 product-level spend is unmapped product m9
            "revenue_id_match_rate": ("ok", 325 / 335),                # SKU-Z (10) is not in the catalog
            "duplicate_order_lines": ("ok", 0),                        # duplicate $insert_id already collapsed in staging
            "spend_reconciliation_gap_pct": ("warn", 5 / 235 * 100),   # worst day 03-01: 5 unallocated of 235
            "purchase_events_missing_order_id_rate": ("warn", 1 / 8),  # event p7 has no order_id
            "negative_spend_rows": ("warn", 1),                        # raw ad3 row with spend -5
            "utm_content_coverage": ("warn", None),                    # no ads snapshot loaded in fixtures -> cannot measure
        }
        assert set(r) == set(want)
        for name, (status, observed) in want.items():
            assert r[name].status.value == status, (name, r[name])
            if observed is not None:
                assert float(r[name].observed) == pytest.approx(observed, abs=1e-4), name
            else:
                assert r[name].observed is None

    def test_stale_data_is_an_error(self, run):
        assert run(date(2026, 10, 21))["freshness_meta_days"].status == DQStatus.ERROR

    def test_summary_and_persistence_feed_the_api(self, warehouse, run, redshift_env):
        from backend.data.redshift_source import RedshiftDataSource

        results = list(run(date(2026, 3, 4)).values())
        summary = dq.summarize(results)
        assert not summary["has_errors"] and "negative_spend_rows" in summary["warnings"]
        with warehouse.cursor() as cur:
            cur.execute("truncate ops.dq_results")
        warehouse.commit()
        dq.persist(RedshiftLoader(warehouse), results)
        api = RedshiftDataSource().data_quality()
        names = {c["check_name"]: c for c in api["checks"]}
        assert set(names) == {r.check_name for r in results}
        assert names["negative_spend_rows"]["status"] == "warn" and names["negative_spend_rows"]["details"]["op"] == "eq"
        assert api["last_run"] is not None

    def test_a_check_with_broken_sql_becomes_an_error_not_a_crash(self, warehouse):
        bad = dq.Check("broken", "", "select 1 / 0 from mart.dim_product limit 1", "le", 1, "warn", "warn")
        res = dq.run_checks(warehouse, [bad], date(2026, 3, 4))[0]
        assert res.status == DQStatus.ERROR and res.details["check_failed_to_run"] == "DivisionByZero"
        assert dq.run_checks(warehouse, [dq.load_checks()[0]], date(2026, 3, 4))[0].status == DQStatus.OK  # conn still usable
