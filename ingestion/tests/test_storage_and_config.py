"""S3/Parquet typing, DDL generation, COPY safety, and config <-> dbt sync guards."""
from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from ingestion.common.ddl import OPS_TABLES, TABLES, columns_for, generate_ddl
from ingestion.common.models import RawAdInsightRow, RawMixpanelEventRow
from ingestion.common.redshift import RedshiftLoader, _check_copy_inputs
from ingestion.common.s3 import S3Writer, _pydantic_to_arrow
from ingestion.mixpanel.events import load_mapping

ROOT = Path(__file__).resolve().parents[2]


# ── Parquet typing ────────────────────────────────────────────────────────────
def test_parquet_keeps_native_types_and_json_encodes_nested():
    rows = [
        RawAdInsightRow(account_id="a", date_start=date(2026, 3, 1), campaign_id="c", adset_id="s", ad_id="x",
                        spend=Decimal("1.5"), actions=[{"action_type": "purchase", "value": "1"}]),
        RawAdInsightRow(account_id="a", date_start=date(2026, 3, 1), campaign_id="c", adset_id="s", ad_id="y"),  # empty list
    ]
    t = _pydantic_to_arrow(rows)
    assert pa.types.is_date32(t.schema.field("date_start").type)
    assert pa.types.is_timestamp(t.schema.field("ingested_at").type)       # datetime must NOT become a string
    assert pa.types.is_floating(t.schema.field("spend").type)
    assert pa.types.is_string(t.schema.field("actions").type)
    assert json.loads(t.column("actions")[0].as_py())[0]["value"] == "1" and t.column("actions")[1].as_py() == "[]"
    buf = io.BytesIO()
    pq.write_table(t, buf)                                                   # empty/varying nested data must be writable
    assert buf.tell() > 0


def test_mixpanel_event_properties_with_varying_keys_are_parquet_safe():
    ev = [RawMixpanelEventRow(event="e", event_time=datetime(2026, 3, 1), distinct_id="u", insert_id="1", properties={}),
          RawMixpanelEventRow(event="e", event_time=datetime(2026, 3, 1), distinct_id="u", insert_id="2", properties={"k": {"n": 1}})]
    pq.write_table(_pydantic_to_arrow(ev), io.BytesIO())


def test_s3_key_layout_and_empty_input(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("ingestion.common.s3.boto3.client", lambda *a, **k: fake)
    w = S3Writer("my-bucket", "roi/raw/", "ap-south-1")
    assert w.write([], "meta", date(2026, 3, 1), "r1") == ""
    fake.put_object.assert_not_called()
    uri = w.write([RawMixpanelEventRow(event="e", event_time=datetime(2026, 3, 1), distinct_id="u", insert_id="1")],
                  "mixpanel", date(2026, 3, 1), "run9")
    assert uri == "s3://my-bucket/roi/raw/mixpanel/2026/03/01/run9.parquet"
    assert fake.put_object.call_args.kwargs["Bucket"] == "my-bucket"


# ── DDL ───────────────────────────────────────────────────────────────────────
def test_ddl_columns_equal_model_fields():
    ddl = generate_ddl("postgres")
    for table, model in TABLES.items():
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in ddl
        for name, _ in columns_for(model):
            assert f'"{name}"' in ddl
    for table in OPS_TABLES:
        assert table in ddl


def test_ddl_maps_nested_fields_to_text_and_dates_to_dates():
    cols = dict(columns_for(RawAdInsightRow))
    assert cols["actions"].startswith("VARCHAR") and cols["date_start"] == "DATE" and cols["ingested_at"] == "TIMESTAMP"
    assert cols["spend"] == "DOUBLE PRECISION" and cols["ad_id"] == "VARCHAR(256)"


@pytest.mark.parametrize("dialect", ["redshift", "postgres"])
def test_committed_sql_files_are_up_to_date(dialect):
    assert (ROOT / "infra" / "sql" / f"owned_schemas.{dialect}.sql").read_text() == generate_ddl(dialect) + "\n"


def test_ddl_only_touches_owned_schemas():
    for line in generate_ddl("redshift").splitlines():
        if line.startswith("CREATE"):
            assert any(s in line for s in ("raw_meta", "raw_mixpanel", "ops")), line


# ── COPY / bootstrap safety ───────────────────────────────────────────────────
GOOD_ARN = "arn:aws:iam::123456789012:role/RedshiftS3CopyRole"


@pytest.mark.parametrize("uri", ["s3://b/x.parquet'; DROP TABLE y;--", "http://evil/x", "s3://b/ x", "s3://UP/x"])
def test_copy_rejects_bad_uri(uri):
    with pytest.raises(ValueError):
        _check_copy_inputs(uri, GOOD_ARN)


def test_copy_rejects_bad_arn_and_accepts_good():
    with pytest.raises(ValueError):
        _check_copy_inputs("s3://bucket-1/a/b.parquet", "arn:aws:iam::1:role/x' ; drop")
    _check_copy_inputs("s3://bucket-1/roi/raw/meta/2026/03/01/r.parquet", GOOD_ARN)


def test_bootstrap_requires_explicit_approval():
    loader = RedshiftLoader(MagicMock())
    with pytest.raises(PermissionError):
        loader.bootstrap_owned_schemas("redshift")
    loader.bootstrap_owned_schemas("redshift", approved=True)


def test_replace_via_s3_orders_delete_then_copy_and_rolls_back_on_failure():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    loader = RedshiftLoader(conn, GOOD_ARN)
    loader.replace_partition_via_s3("raw_meta.ad_insights_daily", "date_start", date(2026, 3, 1), date(2026, 3, 1),
                                    "s3://bucket-1/a.parquet", ["ad_id", "spend"], ("account_id", "act_1"))
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert sqls[0].startswith("DELETE FROM raw_meta.ad_insights_daily") and "account_id = %s" in sqls[0]
    assert sqls[1].startswith("COPY raw_meta.ad_insights_daily") and "FORMAT AS PARQUET" in sqls[1]
    conn.commit.assert_called_once()

    cur.execute.side_effect = [None, RuntimeError("copy failed")]
    with pytest.raises(RuntimeError):
        loader.replace_partition_via_s3("raw_meta.ad_insights_daily", "date_start", date(2026, 3, 1), date(2026, 3, 1),
                                        "s3://bucket-1/a.parquet", ["ad_id"])
    conn.rollback.assert_called_once()                                        # partial delete never commits


def test_writes_outside_owned_schemas_are_refused():
    loader = RedshiftLoader(MagicMock())
    with pytest.raises(PermissionError):
        loader.replace_partition("public.orders", "d", date(2026, 1, 1), date(2026, 1, 1), ["a"], [])
    with pytest.raises(PermissionError):
        loader.replace_partition("mart.product_performance_daily", "d", date(2026, 1, 1), date(2026, 1, 1), ["a"], [])


# ── config <-> dbt drift guards ───────────────────────────────────────────────
def test_mixpanel_mapping_yaml_matches_dbt_vars():
    m, v = yaml.safe_load((ROOT / "config" / "mixpanel_mapping.yml").read_text()), yaml.safe_load((ROOT / "transform" / "dbt_project.yml").read_text())["vars"]
    assert v["purchase_event"] == m["purchase_event"] and v["product_view_event"] == m["product_view_event"]
    for k, prop in m["properties"].items():
        assert v[f"mx_prop_{k}"] == prop, k
    assert v["meta_utm_sources"] == m["meta_utm_sources"] and v["paid_utm_mediums"] == m["paid_utm_mediums"]


def test_segments_yaml_matches_dbt_vars():
    s, v = yaml.safe_load((ROOT / "config" / "segments.yml").read_text()), yaml.safe_load((ROOT / "transform" / "dbt_project.yml").read_text())["vars"]
    assert (s["target_roas"], s["high_spend_percentile"], s["min_spend_for_classification"]) == \
           (v["target_roas"], v["high_spend_percentile"], v["min_spend_for_classification"])


def test_loaded_mapping_exposes_export_events():
    m = load_mapping()
    assert m.purchase_event in m.export_events and m.product_view_event in m.export_events
    assert len(m.export_events) == len(set(m.export_events))
