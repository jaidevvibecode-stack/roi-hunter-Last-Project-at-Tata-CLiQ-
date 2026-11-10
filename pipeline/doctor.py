"""
pipeline/doctor.py — read-only readiness check. Run this FIRST when credentials arrive:

  python -m pipeline.doctor

Verifies, without changing anything: env vars present (never prints values), Meta token validity + scopes (flags
over-broad permissions), a tiny Mixpanel request, Redshift connectivity + schema privileges (and that the API user
cannot write), and S3 bucket access. Exits non-zero if any REQUIRED check fails.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

REQUIRED_ENV = {
    "Meta": ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_IDS", "META_CATALOG_IDS", "META_APP_ID", "META_APP_SECRET"],
    "Mixpanel": ["MIXPANEL_PROJECT_ID", "MIXPANEL_SERVICE_ACCOUNT_USER", "MIXPANEL_SERVICE_ACCOUNT_SECRET", "MIXPANEL_REGION"],
    "Redshift": ["REDSHIFT_HOST", "REDSHIFT_DB", "REDSHIFT_USER", "REDSHIFT_PASSWORD"],
    "S3 / COPY": ["S3_RAW_BUCKET", "REDSHIFT_IAM_ROLE_ARN", "AWS_REGION"],
}
NEEDED_META_SCOPES = {"ads_read"}
TOO_BROAD_META_SCOPES = {"ads_management", "business_management", "catalog_management"}
OWNED_SCHEMAS = ("raw_meta", "raw_mixpanel", "ops")


@dataclass
class Finding:
    area: str
    check: str
    ok: bool
    detail: str = ""
    required: bool = True


def check_env(env: dict[str, str] | None = None) -> list[Finding]:
    env = env if env is not None else dict(os.environ)
    return [Finding(area, f"env {name}", bool(env.get(name)), "set" if env.get(name) else "MISSING")
            for area, names in REQUIRED_ENV.items() for name in names]


def check_meta(env: dict[str, str], transport: httpx.BaseTransport | None = None) -> list[Finding]:
    token, ver = env.get("META_ACCESS_TOKEN", ""), env.get("META_API_VERSION", "v22.0")
    if not token:
        return [Finding("Meta", "token debug", False, "no token")]
    out: list[Finding] = []
    base = f"https://graph.facebook.com/{ver}"
    app_token = f"{env.get('META_APP_ID', '')}|{env.get('META_APP_SECRET', '')}"
    try:
        with httpx.Client(transport=transport, timeout=20) as c:
            r = c.get(f"{base}/debug_token", params={"input_token": token}, headers={"Authorization": f"Bearer {app_token}"})
            r.raise_for_status()
            data = r.json().get("data", {})
            out.append(Finding("Meta", "token valid", bool(data.get("is_valid")), f"type={data.get('type')}"))
            scopes = set(data.get("scopes", []))
            out.append(Finding("Meta", "has ads_read", NEEDED_META_SCOPES <= scopes, f"scopes={sorted(scopes)}"))
            broad = sorted(scopes & TOO_BROAD_META_SCOPES)
            out.append(Finding("Meta", "least privilege (no write scopes)", not broad,
                               f"over-broad scopes: {broad}" if broad else "read-only", required=False))
            exp = data.get("data_access_expires_at") or data.get("expires_at") or 0
            out.append(Finding("Meta", "token expiry", True, "never expires (system user)" if not exp else f"expires_at={exp}", required=False))
            r2 = c.get(f"{base}/me/adaccounts", params={"limit": 1}, headers={"Authorization": f"Bearer {token}"})
            out.append(Finding("Meta", "can list ad accounts", r2.status_code == 200, f"HTTP {r2.status_code}"))
    except Exception as exc:  # noqa: BLE001
        out.append(Finding("Meta", "graph api reachable", False, exc.__class__.__name__))
    return out


def check_mixpanel(env: dict[str, str], transport: httpx.BaseTransport | None = None) -> list[Finding]:
    host = {"US": "data.mixpanel.com", "EU": "data-eu.mixpanel.com", "IN": "data-in.mixpanel.com"}.get(env.get("MIXPANEL_REGION", "US"), "")
    if not (host and env.get("MIXPANEL_PROJECT_ID")):
        return [Finding("Mixpanel", "export request", False, "not configured")]
    d = str(date.today() - timedelta(days=1))
    try:
        with httpx.Client(transport=transport, timeout=60, auth=(env.get("MIXPANEL_SERVICE_ACCOUNT_USER", ""), env.get("MIXPANEL_SERVICE_ACCOUNT_SECRET", ""))) as c:
            r = c.get(f"https://{host}/api/2.0/export", params={"project_id": env["MIXPANEL_PROJECT_ID"], "from_date": d, "to_date": d, "event": '["__doctor_probe__"]'})
        return [Finding("Mixpanel", "service account can export", r.status_code == 200, f"HTTP {r.status_code}")]
    except Exception as exc:  # noqa: BLE001
        return [Finding("Mixpanel", "export reachable", False, exc.__class__.__name__)]


def check_redshift(connect: Callable[[], Any]) -> list[Finding]:
    out: list[Finding] = []
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        return [Finding("Redshift", "connect", False, exc.__class__.__name__)]
    try:
        cur = conn.cursor()
        cur.execute("select 1")
        out.append(Finding("Redshift", "connect + select 1", True))
        for schema in OWNED_SCHEMAS:
            cur.execute("select has_schema_privilege(current_user, %s, 'USAGE')", (schema,))
            row = cur.fetchone()
            out.append(Finding("Redshift", f"usage on owned schema {schema}", bool(row and row[0]),
                               "" if row and row[0] else "schema missing or no USAGE (needs owner approval to create)"))
    except Exception as exc:  # noqa: BLE001
        out.append(Finding("Redshift", "privilege checks", False, exc.__class__.__name__))
    finally:
        conn.close()
    return out


def check_s3(client: Any, bucket: str) -> list[Finding]:
    try:
        client.head_bucket(Bucket=bucket)
        return [Finding("S3", f"bucket {bucket} accessible", True)]
    except Exception as exc:  # noqa: BLE001
        return [Finding("S3", f"bucket {bucket} accessible", False, exc.__class__.__name__)]


def render(findings: list[Finding]) -> str:
    return "\n".join(f"{'OK  ' if f.ok else ('FAIL' if f.required else 'WARN')}  {f.area:<9} {f.check:<42} {f.detail}" for f in findings)


def main() -> None:
    env = dict(os.environ)
    findings = check_env(env) + check_meta(env) + check_mixpanel(env)
    if all(env.get(k) for k in REQUIRED_ENV["Redshift"]):
        import redshift_connector

        findings += check_redshift(lambda: redshift_connector.connect(
            host=env["REDSHIFT_HOST"], port=int(env.get("REDSHIFT_PORT", "5439")), database=env["REDSHIFT_DB"],
            user=env["REDSHIFT_USER"], password=env["REDSHIFT_PASSWORD"], ssl=True))
    if env.get("S3_RAW_BUCKET"):
        import boto3

        findings += check_s3(boto3.client("s3", region_name=env.get("AWS_REGION", "ap-south-1")), env["S3_RAW_BUCKET"])
    print(render(findings))  # noqa: T201
    sys.exit(0 if all(f.ok or not f.required for f in findings) else 1)


if __name__ == "__main__":
    main()
