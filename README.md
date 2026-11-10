# ROI Hunter — SKU-level Ad Performance Platform

> Per-product Spend, CPM, Impressions, Link clicks, CTR and ROAS for **Meta catalog ads**, built from Meta + Mixpanel + Redshift.
> Modelled on [ROI Hunter](https://roihunter.com) and [DeltaX](https://deltax.com). Phase 1 scope; see `04_PLAN.md`.

## Project status — read first (updated 2026-10-21)

**The product is built and exhaustively tested on fixtures. It has not been connected to the real Meta, Mixpanel or Redshift** (no access yet), so nothing here proves real-world numbers. Connecting and validating is the remaining work — [docs/integration_playbook.md](docs/integration_playbook.md) lays it out step by step (**realistically 1–2 weeks**, mostly discovering how the real systems differ from our assumptions).

| Area | State |
|---|---|
| Design, plan, ADRs, security posture | done — [SECURITY.md](SECURITY.md), [docs/adr](docs/adr) |
| API (auth, read-only SQL guard, 10 endpoints with response models) | **done + verified** — on synthetic data, on a Postgres fixture warehouse, and inside Docker |
| Dashboard (7 pages, dashboard login, typed client generated from OpenAPI) | **done + verified** — 13 unit + 11 browser end-to-end tests |
| dbt models (staging → attribution M1–M4 → marts), segmentation, OOS spend, ID-match report | **executed** on hand-built fixtures; results asserted against hand-computed numbers ([trace](docs/validation/attribution_trace.md)); 4 real bugs were found by doing so |
| Ingestion (Meta Pull A/B with auto-split, catalog, objects, Mixpanel), loaders, CLI | **code complete**, idempotency/resume/failure-isolation proven on Postgres; **external calls tested with fakes only** |
| Pipeline: daily orchestrator, scheduler, data-quality runner (9 checks), Slack alerts, `doctor` | **code complete + tested**; runs in Docker |
| Docker: hardened images + whole-stack smoke test (20 assertions) | done |
| **Real-data validation** — spikes P0.2–P0.8, Mixpanel field names, Meta `product_id` format, SKU alignment, backfills, Ads Manager reconciliation, Redshift-dialect SQL | **blocked on access — not started** |
| Not built: margin/returns/POAS, feed write-back, other channels, historical stock | Phase 2/3 (`04_PLAN.md`) |

`[~]` in `04_PLAN.md` = *code complete, not validated on real data*. Demo-mode numbers are **synthetic** (permanent badge in the UI).

## Verification (reproduce with one command: `./scripts/verify_all.sh [--with-docker]`)

| Check | Result |
|---|---|
| Python tests (unit + integration) | 237 tests · coverage gate ≥ 85% (≈ 90%) |
| dbt on fixtures | 15 models · 31 data tests · **11 attribution unit tests** · seed — all pass |
| Production SQL path (`RedshiftDataSource` → marts) on Postgres stand-in | 27 integration tests vs hand-computed expectations |
| Lint / typing / security | ruff · mypy (typed defs required) · bandit (medium+) · detect-secrets — clean |
| Frontend | tsc · eslint · 13 vitest · production build · **11 Playwright tests in real Chrome** |
| OpenAPI contract | committed schema + generated TypeScript types checked for drift |
| Docker smoke test | Postgres + fixtures + dbt + API (`ENV=staging`, fail-closed) + dashboard login — 20 assertions |

Honest caveat: Postgres is a **stand-in** for Redshift (ADR 0001). The Redshift-specific branches of the dialect macros, S3 `COPY`, and all calls to Meta/Mixpanel are unproven until first contact.

## Repository layout
```
backend/     FastAPI read-only API (core/ security, data/ demo + redshift sources, services/ segmentation + rules)
ingestion/   Meta + Mixpanel clients, loaders (idempotent, resumable), CLI, DDL generated from the row models
pipeline/    daily run, scheduler, DQ runner, alerts, doctor
transform/   dbt: staging → intermediate (attribution M1–M4) → marts; macros/cross_db.sql isolates dialect differences
frontend/    Next.js 16 dashboard (proxy.ts auth, server-side API proxy, generated types, vitest + Playwright)
config/      mixpanel_mapping.yml, segments.yml, rules.yml, dq_checks.yml  (business-editable, no code change)
infra/       Dockerfiles, compose (prod-shaped + smoke), generated DDL for our schemas
tests/       hand-built fixtures + expected results, integration tests
docs/        playbook, ADRs, runbook, validation (attribution trace, ID alignment)
```

## Quick start (Python 3.12 recommended — dbt 1.11 needs ≤ 3.13)
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                                      # local defaults: DATA_SOURCE=demo, no auth (ENV=local only)

# demo dashboard on synthetic data
.venv/bin/uvicorn backend.main:app --port 8000
cd frontend && npm install && npm run dev                 # → http://localhost:3000   (login disabled in local dev)

# prove everything (needs a local Postgres for the integration tests; they skip without one)
createdb roi_hunter_ci   # + role roi_ci / password roi_ci_test_only, or set TEST_PG_DSN
./scripts/verify_all.sh --with-docker
```
Real data: fill `.env`, run `python -m pipeline.doctor`, then follow [docs/integration_playbook.md](docs/integration_playbook.md).

## Key design decisions
- Per-product ROAS comes from **first-party data** (Mixpanel/Redshift): Meta does not report per-product conversions off-Meta. Four attribution models (M1 same-SKU click, M2 halo, M3 modelled, M4 last paid touch) are computed; every ROAS shows its model.
- Meta's product-level spend is an estimate → `unallocated_spend` is shown, not hidden.
- Money is `DECIMAL(18,6)`; ratios are recomputed from sums and are NULL (never 0/∞) when undefined.
- **Read-only by construction**, **fail closed**, **recommendation-only** — [SECURITY.md](SECURITY.md).
- Business rules (Mixpanel names, segment thresholds, recommendation rules, DQ thresholds) live in `config/*.yml`.

## Docs
`01_DESIGN.md` design · `02_INSTRUCTIONS.md` agent rules · `03_CONTEXT.md` living status/decisions · `04_PLAN.md` task checklist ·
`docs/integration_playbook.md` · `docs/runbooks/operations.md` · `docs/adr/` · `docs/validation/` · `SECURITY.md`
