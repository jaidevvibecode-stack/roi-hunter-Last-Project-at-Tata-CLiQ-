# ADR 0002 — Synthetic demo data source, clearly labelled

**Status:** accepted · **Date:** 2026-10-21

**Decision.** `DATA_SOURCE=demo` serves a deterministic synthetic catalogue so stakeholders can see the finished
product before access exists. It is allowed **only when `ENV=local`** (the API refuses to start otherwise), every API
response carries `meta.data_source`, and the UI shows a permanent "DEMO DATA · SYNTHETIC" badge. Data Health shows
integrations as *pending*.

**Consequences.** Demo numbers can never be mistaken for real results; switching to real data is one env var
(`DATA_SOURCE=redshift`) and exercises the real SQL path that integration tests already cover.
