from __future__ import annotations

import pytest

from ingestion.common.redshift import _check_write_target


def test_owned_schema_ok():
    _check_write_target("raw_meta.ad_insights", ["a", "b_c"])


@pytest.mark.parametrize("table", ["orders", "public.orders", "mart.x", "raw_meta.x; drop table y", "raw_meta.a.b"])
def test_bad_tables_rejected(table):
    with pytest.raises((ValueError, PermissionError)):
        _check_write_target(table, ["a"])


def test_bad_columns_rejected():
    with pytest.raises(ValueError):
        _check_write_target("ops.dq_results", ["a); drop table x;--"])
