# Integration playbook — what happens the day access arrives

**Honest estimate: 1–2 weeks of elapsed time with good access, not a day.** The code, SQL logic, security and UI are
built and tested on synthetic fixtures. What is *unknown* is how the three real systems look. Each step below is
mechanical and the tooling exists; the time goes into discovering surprises and fixing them.

| Day | Step | Command / file | Done when |
|---|---|---|---|
| 0 | Get access (checklist in `04_PLAN.md`): Meta System User token (`ads_read` + catalog read), Mixpanel service account, **read-only** Redshift user for the API + a separate user that may write to *our* schemas, S3 bucket + IAM role for COPY | — | `.env` filled (never committed) |
| 1 | Readiness check | `python -m pipeline.doctor` | all ✅ — also flags over-broad Meta scopes (we need read-only) |
| 1 | Discovery spikes P0.2–P0.8 | `python scripts/spikes/*.py` | findings logged in `03_CONTEXT.md` (F1–F10) |
| 2 | Fix the placeholders the spikes reveal | `config/mixpanel_mapping.yml` **and** the mirrored dbt vars (a test fails if they drift); Meta `product_id` parse rule in `stg_meta__ad_product_insights.sql`; `transform/seeds/sku_mapping.csv` if SKU formats differ | `pytest` green |
| 2 | Create our schemas (needs the warehouse owner's OK) | `python -m ingestion.cli init-schemas --i-have-approval` | `raw_meta`, `raw_mixpanel`, `ops` exist |
| 3 | Backfill 90 days | `python -m ingestion.cli backfill --source meta_ad --from … --to …` then `meta_product`, `mixpanel`, plus `objects` and `catalog` | resumable; re-run is safe |
| 3 | Reconcile with the business | Compare 3 dates of spend with an Ads Manager export (±0.5%) and revenue with the finance report | numbers agree or the gap is explained |
| 4 | Build the marts on Redshift | `cd transform && dbt deps && dbt build` | all models + 31 tests + 11 unit tests pass |
| 4–5 | Data quality | `python -m pipeline.run_daily --steps dq` | `error` checks pass; warnings understood (`mart.id_match_report`) |
| 5 | Trace 5 real orders end to end | follow `docs/validation/attribution_trace.md` | document written for real data |
| 6 | Point the API at real data | `ENV=staging DATA_SOURCE=redshift`, bcrypt hash, secret key (fails closed otherwise) | `/api/v1/overview` totals = marts |
| 7 | Schedule + alert | `docker compose up pipeline` (scheduler, 06:30 IST) and `ALERT_SLACK_WEBHOOK` | 3 unattended days; a forced failure alerts |
| 8–10 | UAT with the business | validation pack | success criteria in `01_DESIGN.md §1` |

## What I expect to break on first contact (unverified assumptions)
1. **Redshift-specific SQL** is written but has never run on Redshift: the `action_value` macro (`json_parse` + lambda `filter`), `percentile_cont`, `dateadd`, `FULL OUTER JOIN` performance. The same models *do* run on Postgres; the dialect macros (`transform/macros/cross_db.sql`) are the single place to adjust.
2. **Meta `product_id` format** (F9) — the parse rule is a placeholder.
3. **Mixpanel property/event names** — placeholders in `config/mixpanel_mapping.yml`.
4. **UTM coverage** — if ads lack `utm_content={{ad.id}}`, M1/M2/M4 are weak or empty and history cannot be backfilled (the DQ check `utm_content_coverage` measures it).
5. **SKU alignment** across Meta / Mixpanel / Redshift (P0.8) — measured by `mart.id_match_report`.
6. **Volumes**: very large accounts may need the campaign/ad-set auto-split (implemented, tested with fakes, never exercised against Meta) and COPY instead of INSERT (implemented, never run against S3/Redshift).
7. **Rate limits** — Mixpanel export ~60 calls/hour: retry on 429 is implemented and tested; Meta header-based back-off exists (`rate_limit.py`) but is not yet fed with real response headers (needs SDK-level hook, spike P0.2).

8. **M1 click detection assumes UTMs and the SKU are on the same product-view event.** If the site carries UTMs only on the landing event, M1 will be sparse until a session-carry-forward step is added (M2/M4 are less sensitive). Check in spike P0.6 — `utm_content_coverage` and the M1 row counts tell you quickly.
9. **Meta conversion window.** Default is the ad account's own (unified) setting so numbers match Ads Manager; every row stores which setting was used (`attribution_setting`). To pin explicit windows set `META_USE_UNIFIED_ATTRIBUTION=false` + `META_ATTRIBUTION_WINDOWS=7d_click`; how Meta combines these options must be confirmed in spike P0.3 before trusting M3.
10. **Only the 7-day-click window is modelled.** The API refuses other `lookback_days` (422) rather than returning empty rows; adding 1d/28d means extending the mart spine and the attribution models.
11. **Unmapped products are not in the product table** (inner join to the catalog map) but are reported separately as `unmapped_spend` on the Overview and in `mart.id_match_report` / the `spend_id_match_rate` check — so totals never silently shrink.
12. **Mixpanel "day" is the project's timezone setting** (UTC for projects created after 2023). Confirm in P0.6; the loader replaces whole UTC-day partitions.

## Explicitly not built yet (be upfront)
Margin / returns / POAS (needs a data source), feed write-back (gated by plan P2.10), non-Meta channels (Phase 3),
Redshift orders as revenue source of truth (optional hook is documented, not enabled), historical stock availability.
