# ADR 0003 — Read-only by construction; recommendation-only automation

**Status:** accepted · **Date:** 2026-10-21

**Decision.** (1) Every API query passes `ingestion/common/sqlguard.py` (single SELECT/WITH, allow-listed schemas) and runs
in a READ ONLY session with a statement timeout. (2) Ingestion may write only to schemas we own (`raw_meta`, `raw_mixpanel`,
`ops`), validated per statement. (3) There is no code path that writes to Meta; recommendations are suggestions and
`write_back_enabled` is hard-wired `false`. (4) Creating schemas in the client warehouse requires an explicit approval flag.

**Why.** Tata data safety and blast-radius: a bug, injection or misconfiguration must not be able to change client
systems. Defence in depth: the DB user should *also* be read-only, but we do not rely on it.
