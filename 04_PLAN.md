# 04_PLAN.md — Execution Plan

> Work top to bottom. One task at a time. Each task lists: **Design refs**, **Needs from user**, **Do**, **Acceptance**.
> If "Needs from user" is not satisfied → use the ASK-FIRST protocol (`02_INSTRUCTIONS.md §3`) before starting.
> Tick `[x]` with date + one-line note when done. Gates (🚦) require explicit user sign-off.
>
> **Legend:** `[x]` done AND verified · `[~]` **code complete, NOT validated against real data** (parsed/unit-tested only; needs access) · `[ ]` not done.
> Last reconciled: 2026-10-21. No task that depends on Meta / Mixpanel / Redshift access is ticked `[x]`.

---

## PHASE 0 — Discovery, access & feasibility spikes (target: 3–5 working days)

### [x] P0.1 Resource intake — 2026-09-23 — Scaffold built: all layers created (ingestion/meta/mixpanel/common, dbt staging+intermediate+marts, FastAPI all endpoints, Next.js 5-page dashboard, 6 spike scripts, Docker, docs). Q1–Q14 logged. Awaiting user answers.
- **Design refs:** §7, §13; CONTEXT §8
- **Needs from user:** everything in CONTEXT §8 Q1–Q14 (send as one batched request, grouped: Meta / Mixpanel / Redshift / Business definitions / Infra).
- **Do:** Send the request. Create repo skeleton (§6 layout), `.env.example`, `.gitignore`, README stub, pre-commit (ruff, black, mypy, prettier).
- **Acceptance:** Repo skeleton committed; all 14 questions logged with status; no secrets in repo.

### [ ] P0.2 Spike — Meta access & ad-level insights
- **Design refs:** §3, §7.1 Pull A
- **Needs:** Q1, Q2
- **Do:** `scripts/spikes/meta_ad_level.py`: token debug (scopes, expiry), list ad accounts, one-day async ad-level insights for one account. Save redacted sample. Record rate-limit headers.
- **Acceptance:** Sample in `docs/samples/`; F6, F10 verified in CONTEXT; token scopes documented.

### [ ] P0.3 Spike — Meta `product_id` breakdown
- **Design refs:** §3 (items 1–6), §7.1 Pull B
- **Needs:** Q1, at least one active catalog campaign
- **Do:** One-day, one-account async request `level=ad&breakdowns=product_id` with spend/impressions/clicks/inline_link_clicks/actions/action_values. Inspect `product_id` value format. Compare Σ product spend vs ad-level spend for same ads.
- **Acceptance:** F1, F2, F3, F9 verified; gap % recorded; row count & runtime recorded (for volume planning). If product rows are empty → 🔴 protocol (are there catalog ads? permissions?).

### [ ] P0.4 Spike — Meta Catalog
- **Design refs:** §7.3
- **Needs:** catalog IDs / catalog read permission
- **Do:** Pull 1 page of `/{catalog_id}/products` with listed fields; count products; join 100 product_id values from P0.3 to catalog items.
- **Acceptance:** Parse rule for `product_id_raw → meta_item_id → retailer_id` written in CONTEXT; join success % recorded.

### [ ] P0.5 Spike — URL-parameter (UTM) audit
- **Design refs:** §5 prerequisites P1, §7.2
- **Needs:** Q3
- **Do:** Pull ads + creatives `url_tags`; compute % of active catalog ads carrying ad ID in URL params.
- **Acceptance:** Coverage % recorded. If < 100% → `⚠️ RISK` to user with exact fix (template string to paste in Ads Manager URL parameters) and note that history cannot be backfilled.

### [ ] P0.6 Spike — Mixpanel
- **Design refs:** §7.4, §5 P2/P3
- **Needs:** Q4, Q5
- **Do:** If Data Pipelines → Redshift exists, query those tables; else raw export 1 day of the 3 needed events. Verify SKU, price, qty, order_id, UTM props, `fbclid`, distinct_id behaviour.
- **Acceptance:** F7/F8 verified; exact event/property names recorded; % of purchase events with SKU & order_id; % of sessions with utm_content.

### [ ] P0.7 Spike — Redshift
- **Design refs:** §7.5, §8
- **Needs:** Q6, Q7
- **Do:** Connect with service user; list permitted schemas; inspect orders/order_items/products schemas; test S3 COPY path (or confirm fallback).
- **Acceptance:** Source table map in CONTEXT; load method decided (COPY vs INSERT); our schemas created **only after user approves**.

### [ ] P0.8 ID alignment audit
- **Design refs:** §5 P4, §9 `int_product_key_map`
- **Needs:** Q8
- **Do:** Compare SKU sets: Meta retailer_id vs Mixpanel SKU vs Redshift SKU (overlap %, format differences like case, prefixes, variant vs parent).
- **Acceptance:** Match-rate table in `docs/validation/id_alignment.md`; normalisation rule or mapping source agreed.

### [ ] 🚦 P0.9 Feasibility report & GO/NO-GO
- **Do:** One-page report: what's verified, which attribution models are possible now (M1–M4), risks, volume estimates, final stack, open items. Get answers to Q9–Q12.
- **Acceptance:** User approves stack, definitions, and Phase 1 scope in writing (logged in Decisions).

---

## PHASE 1 — Meta product-level dashboard (target: 3–5 weeks)

### Ingestion
#### [~] P1.1 Common library — 2026-10-21 — code + tests: retry (incl. Mixpanel 429/5xx), models, write-guard, log redaction, **idempotent partition load, checkpoints and failure isolation proven on Postgres**, S3 Parquet typing. Redshift COPY/S3 path unit-tested with mocks only — never run against AWS.
- **Refs:** §6, INSTRUCTIONS §6
- **Do:** config (pydantic-settings), structured logging, retry/backoff w/ Meta error-code handling, rate-limit header monitor, S3 writer (Parquet), Redshift loader (COPY + fallback), `ops.ingestion_runs` / checkpoints writers.
- **Acceptance:** Unit tests for retry classification, Decimal handling, idempotent load (re-run same partition → same row count).

#### [~] P1.2 Meta objects & catalog ingestion — 2026-10-21 — objects/catalog ingestion written + tested with faked SDK (pagination incl. an infinite-loop fix, hierarchy, UTM audit); never run against Meta.
- **Refs:** §7.2, §7.3, §8.1
- **Do:** Daily snapshots of campaigns/ad sets/ads (incl. url_tags, product_set_id) and catalog products.
- **Acceptance:** Tables populated for all accounts/catalogs; runtime logged; re-run idempotent.

#### [~] P1.3 Meta ad-level insights ingestion (Pull A) — 2026-10-21 — Pull A written + tested with faked SDK (create/poll/paginate/parse, timeouts, failures) and idempotent load; never run against Meta; no Ads Manager reconciliation yet.
- **Refs:** §7.1
- **Do:** Async jobs per account×day; trailing-7d daily mode; 28d weekly mode; backfill CLI (`--from --to`, resumable).
- **Acceptance:** 90-day backfill complete; totals for 3 dates match Ads Manager export supplied by user (±0.5% spend).

#### [~] P1.4 Meta ad × product insights ingestion (Pull B) — 2026-10-21 — Pull B written + **auto-split by campaign then ad set implemented and tested**; never run against Meta; product_id format (F9) unverified.
- **Refs:** §7.1, §3
- **Do:** Same as P1.3 with `breakdowns=product_id`; auto-split on failure (campaign → ad set).
- **Acceptance:** 90-day backfill complete; reconciliation gap within tolerance (§12) or explained.

#### [~] P1.5 First-party data ingestion — 2026-10-21 — Mixpanel export client + parser + loader tested with mock HTTP; property names are PLACEHOLDERS (config/mixpanel_mapping.yml). Redshift orders as revenue source NOT built.
- **Refs:** §7.4, §7.5
- **Do:** Either (a) point dbt sources at existing Mixpanel pipeline tables / Redshift orders, or (b) build Mixpanel raw export job for needed events only (day-by-day, dedupe on `$insert_id`).
- **Acceptance:** 90 days loaded; daily purchase revenue in our tables matches the user's source-of-truth revenue report for 3 dates (tolerance agreed with user).

#### [~] P1.6 Scheduling — 2026-10-21 — scheduler (06:30 IST, Monday 28-day restatement), orchestrator with failure isolation, Slack alerts, `pipeline.doctor` — all unit-tested; runs in the pipeline container. 3 unattended days on real data NOT possible yet.
- **Refs:** §6
- **Needs:** Q12 (hosting)
- **Do:** Daily schedule (after Meta's day closes in account tz), weekly 28d restatement, failure alerts.
- **Acceptance:** 3 consecutive unattended successful daily runs; a forced failure produces an alert.

### Transformation
#### [~] P1.7 dbt project & staging models — 2026-10-21 — staging models executed on Postgres fixtures and `dbt parse` passes; Redshift dialect branches (macros) unverified.
- **Refs:** §9
- **Acceptance:** `dbt build` green; staging models documented; PK tests pass.

#### [~] P1.8 Product key map & dimensions — 2026-10-21 — int_product_key_map + deduped dim_product + id_match_report executed on fixtures (hand-checked); real match rate unknown until real data.
- **Refs:** §8.3 dim_product/dim_ad, §9 int_product_key_map
- **Acceptance:** `mart.id_match_report` shows ≥ 95% spend matched (or 🔴/⚠️ report with cause).

#### [~] P1.9 Delivery facts — 2026-10-21 — spend_reconciliation + model-spine/FULL OUTER JOIN executed and asserted on fixtures; currency conversion (Q11) not done.
- **Refs:** §8.3 fct_ad_product_daily, fct_ad_daily, spend_reconciliation
- **Acceptance:** Reconciliation mart populated; currency conversion applied per Q11.

#### [~] P1.10 Attribution models — 2026-10-21 — **M1–M4 executed; 11 isolated dbt unit tests + fixture end-to-end asserted vs hand-computed numbers; trace in docs/validation/attribution_trace.md.** Real-order traces (acceptance) still pending real data.
- **Refs:** §5
- **Do:** Implement models possible per P0.9 (at least M1 and M3 if prerequisites allow). Fixture-based unit tests with hand-computed expected results.
- **Acceptance:** Fixture tests pass; 5 real orders traced end-to-end and documented in `docs/validation/attribution_trace.md`.

#### [~] P1.11 Serving mart & performance — 2026-10-21 — product_performance_daily executed on fixtures; p95 < 3s unmeasured at production volume.
- **Refs:** §8.3 product_performance_daily, §10
- **Acceptance:** Product table query for 30 days < 3s p95 at production volume (measure; add pre-aggregations if needed).

#### [~] P1.12 Data quality checks — 2026-10-21 — **DQ runner built** (config/dq_checks.yml, 9 checks → ops.dq_results → API/Data Health), tested on fixtures incl. a stale-data failure; thresholds unverified on real data.
- **Refs:** §12
- **Acceptance:** All checks run daily and write `ops.dq_results`; thresholds configurable.

### Backend
#### [x] P1.13 FastAPI scaffold, auth, health — 2026-10-21 — basic auth (bcrypt), fail-closed settings, security middleware, read-only DB guard — verified by tests and by the docker smoke stack (ENV=staging).
- **Refs:** §10, §13
- **Needs:** Q12 (auth method)
- **Acceptance:** `/health` open; everything else requires auth; OpenAPI schema generated.

#### [~] P1.14 Endpoints — 2026-10-21 — all endpoints have response models + 100+ backend tests; **production SQL path executed against the dbt-built fixture warehouse** (27 integration tests) and through docker. Never run on Redshift.
- **Refs:** §10 (overview, products, product detail/trend/breakdown, trends, filters, attribution/compare, data-quality, freshness, export CSV)
- **Acceptance:** Tests for each endpoint incl. filter combos, sort whitelist, NULL ratios, pagination; SQL-injection test on sort/search params.

### Frontend
#### [~] P1.15 App shell & global filters — 2026-10-21 — URL-persisted filters, server-side auth proxy, dashboard login (proxy.ts, fails closed), **typed client generated from OpenAPI**; vitest + 11 Playwright e2e tests.
- **Refs:** §11
- **Acceptance:** Filters persisted in URL; auth flow working; typed API client generated from OpenAPI.

#### [~] P1.16 Products page (primary deliverable) — 2026-10-21 — built; verified on demo data and (via API) on fixture warehouse; server-side pagination (not 50k virtualised).
- **Refs:** §11 page 2
- **Acceptance:** Shows per product: Spend, CPM, cost/impression, Impressions, Link clicks, CTR, CPC, Orders, Revenue, ROAS (+ model badge); sort/search/filter/export; 50k rows usable (virtualised).

#### [~] P1.17 Overview page — 2026-10-21 — built on demo data; KPI-equals-table-sum is tested in backend.
- **Refs:** §11 page 1 (incl. spend-concentration Pareto)
- **Acceptance:** KPI totals equal sum of product table for same filters (automated test).

#### [~] P1.18 Product detail & campaign drill-down pages — 2026-10-21 — product detail drawer built; campaign drill-down page NOT built.
- **Refs:** §11 pages 3–4

#### [~] P1.19 Data health page — 2026-10-21 — built; shows 'pending' honestly in demo mode.
- **Refs:** §11 page 5, §12

### Release
#### [~] P1.20 Deployment — 2026-10-21 — hardened Dockerfiles (non-root, read-only FS, healthchecks) + compose; **whole stack smoke-tested in Docker (20 assertions)**. Cloud deployment, secret manager and SSO not done.
- **Needs:** Q12
- **Do:** Dockerise; deploy to approved target; secrets via secret manager; runbook `docs/runbooks/operations.md` (backfill, rerun, token rotation, adding an ad account).
- **Acceptance:** Deployed URL behind auth; runbook reviewed by user.

#### [ ] 🚦 P1.21 User acceptance
- **Do:** Walk-through with user; validation pack (Ads Manager comparisons, attribution traces, match rates).
- **Acceptance:** DESIGN §1 success criteria 1–6 met or exceptions signed off.

---

## PHASE 2 — Profit, segmentation & automation (target: 4–6 weeks) — see §14

- [ ] P2.1 COGS/margin/returns ingestion (needs source from user) → gross_profit, POAS, net ROAS
- [ ] P2.2 Non-catalog ad → product mapping (rules agreed with user)
- [~] P2.3 Product segmentation engine + Segments page — built early (config/segments.yml, mart.product_segments); demo data only
- [~] P2.4 Alerts & rules engine — rules + Recommendations page built (recommendation-only, config/rules.yml); Slack/email delivery NOT built
- [ ] P2.5 Scheduled reports (CSV/XLSX/PDF)
- [~] P2.6 Attribution model comparison UI — built; lookback windows other than 7d not yet modelled in dbt
- [~] P2.7 Out-of-stock spend detection — mart.oos_spend_daily uses LATEST availability only (no history yet)
- [ ] P2.8 Pacing (planned vs actual; plan upload)
- [ ] P2.9 Multi-currency with FX history
- [ ] 🚦 P2.10 Feed write-back of segments as custom labels — **only with explicit approval**, requires `catalog_management`; dry-run diff, audit log, rollback
- [ ] P2.11 Orchestrator upgrade (Dagster/Airflow) if job count justifies
- [ ] 🚦 P2.12 Phase 2 acceptance

## PHASE 3 — Cross-platform SKU intelligence (target: 6–10 weeks) — see §15

- [ ] P3.1 Channel adapter interface + unified `channel_product_performance_daily`
- [ ] P3.2 Google Ads adapter (Shopping/PMax product-level via GAQL) — spike first; needs developer token + OAuth
- [ ] P3.3 Google Merchant Center adapter (status, disapprovals, price)
- [ ] P3.4 TikTok / Snapchat / Pinterest adapters — one spike each; document per-product capability gaps with 🔴 protocol where applicable
- [ ] P3.5 GA4 BigQuery export source (if user has it)
- [ ] P3.6 Cross-channel dedupe of first-party revenue + journey paths
- [ ] P3.7 Multi-touch attribution models + comparison
- [ ] P3.8 Deep SKU analytics: variant groups, price-change impact, lifecycle, new vs returning, LTV by acquiring product
- [ ] P3.9 Bayesian budget recommendation engine (recommendations only; execution is a separate approved task with caps + kill-switch)
- [ ] P3.10 Internal reporting API
- [ ] 🚦 P3.11 Phase 3 acceptance

---

## Resource checklist (for the user — what the agent will ask for)

| Area | Item | Phase |
|---|---|---|
| Meta | Business Manager ID; ad account IDs; catalog IDs | 0 |
| Meta | Meta app (App ID/secret) with Marketing API; System User token with `ads_read` + catalog read | 0 |
| Meta | Confirmation/fix of URL parameters `utm_content={{ad.id}}` on all catalog ads | 0 |
| Meta | Ads Manager exports for validation dates | 1 |
| Mixpanel | Project ID, region, service account; Data Pipelines status; event/property dictionary | 0 |
| Redshift | Connection details, service user, permission to create our schemas; S3 bucket + IAM role for COPY | 0 |
| Redshift | Orders / order_items / products / COGS / returns table names & owners | 0 / 2 |
| Business | Revenue definition, currency, timezone, "cost to show" definition, attribution default | 0 |
| Infra | Hosting target, auth method, alert channel | 0–1 |
| Phase 3 | Google Ads developer token + OAuth, GMC ID, TikTok/Snap/Pinterest API access | 3 |
