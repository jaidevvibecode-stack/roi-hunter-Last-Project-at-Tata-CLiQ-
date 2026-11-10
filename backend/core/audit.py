"""
backend/core/audit.py
----------------------
Structured access/audit log. Records who asked for what (endpoint, date range,
row count, latency). Never logs credentials, query text with PII, or row data.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Iterator

_log = logging.getLogger("audit")


@contextmanager
def audited(user: str, endpoint: str, **fields: object) -> Iterator[dict[str, object]]:
    ctx: dict[str, object] = {"rows": None}
    t0 = time.perf_counter()
    try:
        yield ctx
    finally:
        _log.info(
            json.dumps(
                {
                    "event": "api_access",
                    "user": user,
                    "endpoint": endpoint,
                    **{k: str(v) for k, v in fields.items()},
                    "rows": ctx["rows"],
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
        )
