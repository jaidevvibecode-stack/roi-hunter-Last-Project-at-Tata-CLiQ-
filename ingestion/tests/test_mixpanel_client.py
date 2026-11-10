"""Mixpanel export client against httpx.MockTransport: JSONL parsing, params, retry on 429/5xx, no retry on auth errors."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from ingestion.common.config import MixpanelSettings
from ingestion.common.retry import is_retryable
from ingestion.mixpanel.client import MixpanelExportClient


def client_with(handler):
    cfg = MixpanelSettings(project_id="123", service_account_user="svc", service_account_secret="s3cr3t", region="IN")
    c = MixpanelExportClient(cfg)
    c.__enter__()
    c._client = httpx.Client(transport=httpx.MockTransport(handler), base_url=c._base_url, auth=c._auth)
    return c


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)   # tenacity back-off


def test_parses_jsonl_skips_blank_and_corrupt_lines():
    body = '{"event":"a","properties":{"time":1}}\n\nNOT JSON\n{"event":"b","properties":{"time":2}}\n'
    c = client_with(lambda req: httpx.Response(200, text=body))
    assert [e["event"] for e in c.export_day(date(2026, 3, 1), ["a", "b"])] == ["a", "b"]


def test_sends_project_dates_event_filter_and_basic_auth_to_regional_host():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["auth"] = req.url, req.headers.get("authorization", "")
        return httpx.Response(200, text="")

    c = client_with(handler)
    c.export_day(date(2026, 3, 1), ["Order Completed", "Product Viewed"])
    q = dict(seen["url"].params)
    assert q["project_id"] == "123" and q["from_date"] == q["to_date"] == "2026-03-01"
    assert json.loads(q["event"]) == ["Order Completed", "Product Viewed"]
    assert c._base_url == "https://data-in.mixpanel.com" and seen["auth"].startswith("Basic ")


def test_rate_limit_429_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, text="rate limited") if calls["n"] < 3 else httpx.Response(200, text='{"event":"x","properties":{}}')

    assert len(client_with(handler).export_day(date(2026, 3, 1), ["x"])) == 1 and calls["n"] == 3


def test_server_error_503_is_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, text="")

    client_with(handler).export_day(date(2026, 3, 1), ["x"])
    assert calls["n"] == 2


def test_bad_credentials_401_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(httpx.HTTPStatusError):
        client_with(handler).export_day(date(2026, 3, 1), ["x"])
    assert calls["n"] == 1


def test_retry_classifier_for_http_errors():
    req = httpx.Request("GET", "https://x")
    assert is_retryable(httpx.HTTPStatusError("x", request=req, response=httpx.Response(429, request=req)))
    assert is_retryable(httpx.HTTPStatusError("x", request=req, response=httpx.Response(502, request=req)))
    assert not is_retryable(httpx.HTTPStatusError("x", request=req, response=httpx.Response(403, request=req)))
    assert is_retryable(httpx.ConnectTimeout("t"))


def test_unconfigured_client_refuses_to_start():
    with pytest.raises(RuntimeError, match="not configured"):
        MixpanelExportClient(MixpanelSettings())
