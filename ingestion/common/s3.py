"""
ingestion/common/s3.py
-----------------------
Write raw ingestion data to S3 as Parquet, partitioned by date.

Partition scheme:  s3://{bucket}/{prefix}/{source}/{year}/{month}/{day}/{run_id}.parquet
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

log = logging.getLogger(__name__)


def _pydantic_to_arrow(records: list[BaseModel]) -> pa.Table:
    """
    Convert Pydantic models to a PyArrow table with COPY-friendly types:
      * date / datetime stay native (date32 / timestamp) — never stringified
      * Decimal -> float64 (raw layer; dbt casts to DECIMAL(18,6))
      * dict / list -> JSON text (nested structs with varying/empty keys break Parquet and COPY)
    """
    cleaned: list[dict[str, Any]] = []
    for r in records:
        row: dict[str, Any] = {}
        for k, v in r.model_dump().items():
            if isinstance(v, (dict, list)):
                row[k] = json.dumps(v, default=str, sort_keys=True)
            elif isinstance(v, Decimal):
                row[k] = float(v)
            else:
                row[k] = v
        cleaned.append(row)
    return pa.Table.from_pylist(cleaned)


class S3Writer:
    """Write Parquet files to S3 for a given source."""

    def __init__(
        self,
        bucket: str,
        prefix: str,
        aws_region: str = "ap-south-1",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._client = boto3.client("s3", region_name=aws_region)

    def write(
        self,
        records: list[BaseModel],
        source: str,
        partition_date: date,
        run_id: str,
    ) -> str:
        """
        Serialise records to Parquet and upload to S3.
        Returns the S3 URI of the written file.
        Raises on upload failure (let caller handle retry).
        """
        if not records:
            log.info("No records to write", extra={"source": source, "date": str(partition_date)})
            return ""

        table = _pydantic_to_arrow(records)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        buf.seek(0)

        key = (
            f"{self._prefix}/{source}/"
            f"{partition_date.year}/{partition_date.month:02d}/{partition_date.day:02d}/"
            f"{run_id}.parquet"
        )

        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=buf.read(),
            ContentType="application/octet-stream",
        )

        uri = f"s3://{self._bucket}/{key}"
        log.info(
            "Parquet written to S3",
            extra={"uri": uri, "rows": len(records), "source": source},
        )
        return uri
