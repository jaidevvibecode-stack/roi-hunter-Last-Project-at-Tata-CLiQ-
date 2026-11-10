# SECURITY.md — data safety posture

This system reads advertising and customer-behaviour data. Principles, in priority order:

1. **Read-only by construction.** The platform never writes to Meta, Mixpanel, or any *existing* Tata Redshift schema.
   - API → Redshift: `backend/core/db.py` runs every query through `validate_select` (single `SELECT`/`WITH` only; DDL/DML/`COPY`/`UNLOAD`/`INTO`/`SET` rejected; only `mart` and `ops` schemas readable), in a `READ ONLY` session with a statement timeout. Tested in `backend/tests/test_security.py` (incl. every query the Redshift source emits).
   - Ingestion → Redshift: `ingestion/common/redshift.py::_check_write_target` allows writes only to schemas we own (`raw_meta`, `raw_mixpanel`, `ops`) and plain identifiers; COPY's S3 URI and IAM role ARN (which cannot be parameterised) are strictly regex-validated; creating our schemas needs an explicit approval flag. Tested, including attempts to write to `mart` / `public`.
   - Data-quality checks (`config/dq_checks.yml`) go through the same SELECT-only guard — an edited check cannot write.
   - The API's DB session is READ ONLY at the database level too (integration test asserts a `CREATE TABLE` is refused even if the guard were bypassed).
   - Provision the DB user read-only as well (defence in depth): `GRANT SELECT` on `mart`, `ops` only.
   - There is **no write-back to ad platforms**. Recommendations are suggestions; `write_back_enabled` is `false`. Any future write path needs an explicit approval gate (plan P2.10).
2. **Fail closed.** Outside `ENV=local` the API refuses to start unless: auth is `basic` with a bcrypt hash, `APP_SECRET_KEY` ≥ 32 chars, no wildcard CORS/hosts, and `DATA_SOURCE` is not `demo` (`backend/core/settings.py`).
3. **Secrets never in code or browser.** Secrets are `SecretStr` env vars (see `.env.example`; real `.env*` is git-ignored). The frontend reaches the API only via a server-side proxy (`frontend/app/api/proxy`) — backend credentials are server-only env vars, GET-only, path-allowlisted (`/api/v1/*`, `/health`). The docker smoke test asserts the API password never appears in any browser-bound response. Use AWS Secrets Manager / SSM in deployment.
   - **Dashboard login:** `frontend/proxy.ts` (Next 16 proxy) gates every page and the proxy route with basic auth (scrypt-hashed password, constant-time compare). In production it returns **503 if credentials are not configured** — never open by default (`frontend/tests/unit/uiAuth.test.ts`).
   - **Browser hardening:** CSP (`connect-src 'self'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, HSTS, no `X-Powered-By` (asserted in Playwright).
   - **Containers:** non-root user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, healthchecks (`infra/docker-compose.yml`).
4. **Least data.** Mixpanel `distinct_id` is hashed (md5) in the first staging model; a dbt test (`transform/tests/assert_no_pii_columns.sql`) fails if email/phone/name-like columns appear in `stg/int/mart`. Logs are scrubbed of tokens, emails and Indian phone numbers (`ingestion/common/logging_utils.py::redact`). Aggregates only reach the dashboard — no customer-level rows.
5. **Defence at the edge.** Security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, HSTS, `no-store`), trusted-host check, per-IP rate limit, query-param length caps, generic 500s (no stack traces), `/docs` disabled outside local, audit log of who queried what (`backend/core/audit.py`).
6. **Injection-safe.** All SQL is parameterised; sort columns are whitelisted; `LIKE` wildcards in search are escaped; CSV export neutralises spreadsheet formulas (`= + - @`).

## Before any non-local deployment (checklist)
- [ ] Put the frontend behind company SSO / VPN (the app's basic auth protects the API, not end-user identity).
- [ ] Set `ENV=prod`, provision bcrypt hash + `APP_SECRET_KEY`, restrict `CORS_ORIGINS` / `ALLOWED_HOSTS`.
- [ ] Create a dedicated read-only Redshift user for the API and a separate write-limited user for ingestion.
- [ ] Meta token: System User, `ads_read` only (+ catalog read); store in Secrets Manager; rotate per runbook.
- [ ] Confirm DPDP/GDPR handling with Tata infosec (Q14); confirm Mixpanel data-residency region.
- [ ] Run `pip-audit`, `npm audit`, `bandit`, `detect-secrets` in CI (workflow provided) and review results.
- [ ] Independent security review / pen-test — this repo has had automated checks only.

## Verified automatically (see README "Verification")
Auth on/off and fail-closed settings · security headers · rate limit · host allow-list · SQL-injection attempts on sort/search · read-only guard and DB-level read-only session · write-schema allow-list · CSV formula neutralisation · log redaction · over-broad Meta token detection (`pipeline.doctor`) · docker stack in `ENV=staging` refusing unsafe config · API credentials never reaching the browser.

## Known limitations (be honest)
- Rate limiting is in-memory per process (use an API gateway / WAF in production).
- Basic auth (API and dashboard) is a baseline: one shared identity, no per-user audit trail or RBAC; the dashboard forwards a single backend credential for everyone. SSO (OIDC) with per-user identity is the intended end state.
- The SQL guard is regex-based defence in depth (it also bans quoted identifiers, scans every `schema.` reference and pins `search_path=mart,ops`); the real control is a read-only database user — provision one.
- Behind a proxy the per-IP rate limit only sees real clients if `TRUST_FORWARDED_FOR=true` and a trusted proxy sets `X-Forwarded-For`; it is in-memory per worker.
- Redshift SQL, S3 COPY, Meta and Mixpanel calls have **not** run against the real services (no access yet).
- No independent penetration test; checks are automated (bandit, ruff, detect-secrets, pip-audit/npm audit advisory in CI).

## Reporting
Report suspected vulnerabilities to the project owner privately; do not file public issues containing data or credentials.
