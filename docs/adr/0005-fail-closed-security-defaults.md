# ADR 0005 — Fail closed

**Status:** accepted · **Date:** 2026-10-21

Outside `ENV=local` the API refuses to start unless basic auth with a bcrypt hash, a ≥32-char secret key, explicit
CORS/host allow-lists and a non-demo data source are configured; `ENV=prod` additionally requires Redshift with TLS.
The dashboard's `proxy.ts` returns 503 in production when no credentials are configured. The browser never receives
backend credentials (server-side proxy, GET-only, path allow-list). Tested in `backend/tests/test_security.py`,
`frontend/tests/unit/uiAuth.test.ts` and the docker smoke test.
