# ADR 0001 — Portable dbt SQL; Postgres as a *stand-in* for Redshift in CI

**Status:** accepted · **Date:** 2026-10-21

**Context.** We have no access to Tata's Redshift, yet the transformation logic (attribution, reconciliation, dedupe)
is the riskiest part of the product and was previously only parsed, never executed.

**Decision.** Keep Redshift as the production target but write models in the common SQL subset and isolate dialect
differences in `transform/macros/cross_db.sql` (`json_text`, `action_value`) plus dbt's built-in `dbt.dateadd`.
CI and the docker smoke stack run the *same* models on Postgres with hand-built fixtures and assert hand-computed results.

**Consequences.** (+) The logic is executed, unit-tested and regression-tested on every change; four real bugs were found
the first time it ran (see `docs/validation/attribution_trace.md`). (−) Postgres ≠ Redshift: the Redshift branch of each
macro, distribution/sort keys, `percentile_cont` semantics and performance are **not** proven until the first run on
Redshift (playbook step 4). We never claim otherwise.
