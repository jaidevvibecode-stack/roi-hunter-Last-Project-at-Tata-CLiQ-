# 03_CONTEXT.md — Smart Context (read first, every session)

> Compact, living memory for the coding agent. Keep < 250 lines. Update at the end of every task.
> Full detail lives in `01_DESIGN.md` (cite §numbers), rules in `02_INSTRUCTIONS.md`, tasks in `04_PLAN.md`.

## 1. One-liner
SKU-level ad analytics platform (ROI Hunter / DeltaX style). Phase 1: dashboard of per-product **Spend (cost to show), CPM, Impressions, Link clicks, CTR, ROAS** for Meta catalog ads, using **Meta API + Mixpanel + Redshift**.

## 2. Status (agent updates)
- Current phase: **Phase 0 — blocked on access**; Phase 1 code complete and *executed on fixtures* ahead of validation
- Current task: **P0.2 (needs Meta credentials)** — then spikes P0.3–P0.8 (see docs/integration_playbook.md)
- Last completed: 2026-10-21 — portable SQL executed on a Postgres stand-in (4 real bugs found+fixed), M1–M4 unit-tested, DQ runner, scheduler, doctor, CLI, typed API client, docker smoke test
- Verified (automated): see README "Verification". NOT verified: anything against real Meta / Mixpanel / Redshift (`[~]` in 04_PLAN)
- Dashboard runs on **synthetic demo data** by default (`DATA_SOURCE=demo`, labelled); with `DATA_SOURCE=redshift` it reads the dbt marts (proven on fixtures only)
- Blockers: Q1–Q14 open; Meta/Mixpanel/Redshift credentials; Mixpanel property names, Meta product_id format and SKU alignment unverified
- Last updated: 2026-10-21 by agent

## 3. Non-negotiable facts (pre-researched — verify in Phase 0, then mark ✅)
| # | Fact | Verified |
|---|---|---|
| F1 | Meta Insights `breakdowns=product_id` gives spend/impressions/clicks/inline_link_clicks per product for catalog ads | ☐ |
| F2 | Off-Meta actions (web purchases, purchase value) do **not** carry product_id breakdown values (since 2021-04-27) ⇒ product ROAS needs first-party data | ☐ |
| F3 | Breakdown values are estimated ⇒ Σ product spend ≠ ad spend exactly; show `unallocated_spend` | ☐ |
| F4 | Insights history ≈ trailing 37 months | ☐ |
| F5 | Meta conversions restate for up to ~28 days ⇒ re-pull trailing 7d daily, 28d weekly | ☐ |
| F6 | API default attribution ≠ Ads Manager unless `use_unified_attribution_setting=true` | ☐ |
| F7 | Mixpanel Raw Export API: `data.mixpanel.com/api/2.0/export`, JSONL, UTC dates (projects after 2023-01-01), rate-limited (~60/hr, 3/s — verify) | ☐ |
| F8 | Mixpanel Data Pipelines can sync to Redshift/S3 (paid add-on) | ☐ |
| F9 | `product_id` value format returned by Meta = ? (fill in from spike) | ☐ |
| F10 | Pinned Graph API version = ? | ☐ |

## 4. Metric formulas (never average ratios; recompute from sums)
```
ctr = link_clicks / impressions          cpm = spend / impressions * 1000
cost_per_impression = spend / impressions cpc = spend / link_clicks
roas[m] = attributed_revenue[m] / spend   cvr[m] = orders[m] / link_clicks
unallocated_spend = ad_level_catalog_spend − Σ product_spend
Division by zero → NULL (UI shows "—")
```
Money = DECIMAL(18,6) / Python Decimal. Dates: store UTC, report in ad-account tz.

## 5. Attribution models (§5)
- **M1 (default)** same-SKU click: purchase of SKU X ≤ N days after Meta click session landing on X.
- **M2** halo: all order items after click on X credited to X.
- **M3** modelled: Meta ad-level purchase value split by product link-click share.
- **M4** purchased-SKU last paid touch = Meta.
- Default lookback 7d click. Every ROAS in UI shows its model badge.
- Prereqs: `utm_content={{ad.id}}` on ads (P1), landing event has SKU (P2), purchases have line items (P3), IDs aligned (P4).

## 6. Key joins
```
Meta product row.product_id_raw ──parse──► meta_item_id ──catalog──► retailer_id (SKU)
retailer_id == Mixpanel <sku property> == Redshift <sku column>      (or seeds/sku_mapping.csv)
Mixpanel session.utm_content == Meta ad_id
order.order_id dedupes revenue
```

## 7. Stack & layout (§6) — approved? ✅ (2026-09-23)
Python ingestion (facebook-business SDK) → S3 Parquet → Redshift COPY (fallback: batched INSERT) → dbt → FastAPI → Next.js (TS, TanStack Table, ECharts). Scheduler Phase 1: simple cron/scheduled task.
```
/ingestion /transform(dbt) /backend /frontend /infra /docs /scripts/spikes
Schemas we own: raw_meta raw_mixpanel stg int mart ops
```
Scaffold status: all layers have code; see §2 for what is validated (very little). Run: `DATA_SOURCE=demo uvicorn backend.main:app` + `npm run dev` in /frontend.

## 8. Open questions / blockers (agent maintains)
| ID | Question | Status | Answer / link |
|---|---|---|---|
| Q1 | Meta: Business ID, ad account IDs, catalog IDs, System User token with ads_read + catalog read | OPEN | |
| Q2 | Meta app access tier (development vs standard/advanced) | OPEN | |
| Q3 | Do all catalog ads have `utm_content={{ad.id}}` (or similar) URL params? Since when? | OPEN | |
| Q4 | Mixpanel: project ID, region (US/EU/IN), service account; is Data Pipelines → Redshift already on? | OPEN | |
| Q5 | Mixpanel event dictionary: product-view event, purchase event, SKU/price/qty/order_id property names | OPEN | |
| Q6 | Redshift: host, db, service user, schemas we may create, S3 bucket + IAM role for COPY | OPEN | |
| Q7 | Redshift orders/order_items/products tables & columns; revenue truth = Redshift or Mixpanel? | OPEN | |
| Q8 | Is Meta `retailer_id` identical to Mixpanel & Redshift SKU? If not, mapping source? | OPEN | |
| Q9 | Revenue definition (gross item revenue excl. tax/shipping, pre-refund?) | OPEN | |
| Q10 | "Cost to show an ad per product" = Spend + CPM + cost/impression? | OPEN | |
| Q11 | Reporting currency, FX source, number format (INR lakh/crore?), reporting timezone | OPEN | |
| Q12 | Hosting target, dashboard auth method, alert channel (Slack/email) | OPEN | |
| Q13 | Data volume: # products in catalog, # active catalog ads, daily spend scale | OPEN | |
| Q14 | Data/privacy policy constraints (DPDP/GDPR, PII rules) | OPEN | |

## 9. Verified facts log (append one line per finding)
- <YYYY-MM-DD> — <fact> — <evidence path e.g. docs/samples/meta_product_breakdown.json>

## 10. Decisions log (append; never delete)
- <YYYY-MM-DD> — <decision> — <why> — <who approved>
- 2026-10-21 — Demo data source (`DATA_SOURCE=demo`) added, allowed only when ENV=local; every API response carries meta.data_source and the UI shows a DEMO badge — lets stakeholders preview the product without access, without demo numbers passing as real — agent (user requested preview)
- 2026-10-21 — Backend fails closed outside ENV=local (auth, CORS, secret, no demo) and the DB layer is read-only by construction (SELECT-only guard, mart/ops schemas only) — Tata data safety — agent
- 2026-10-21 — Recommendations are recommendation-only; `write_back_enabled=false`; no Meta write path exists — matches DESIGN §14 / P2.10 gate — agent
- 2026-10-21 — dbt models written in portable SQL (dialect macros in transform/macros/cross_db.sql); CI + docker smoke run the SAME models on Postgres with hand-built fixtures — gives executed, asserted logic; Redshift-specific branches remain unproven until first real run — agent (ADR 0001)
- 2026-10-21 — Mixpanel event/property names moved to config/mixpanel_mapping.yml (mirrored in dbt vars; a test fails on drift) so spike P0.6 results are a config change — agent
- 2026-10-21 — Attributed revenue with no same-day delivery is KEPT (FULL OUTER JOIN, spend 0) rather than dropped — agent (ADR 0004)
- 2026-10-21 — dbt `generate_schema_name` overridden so models land in `stg/int/mart` verbatim (backend queries `mart.*`) — agent

## 11. Env var names (values never here)
```
META_ACCESS_TOKEN  META_APP_ID  META_APP_SECRET  META_BUSINESS_ID  META_AD_ACCOUNT_IDS  META_CATALOG_IDS  META_API_VERSION
MIXPANEL_PROJECT_ID  MIXPANEL_SERVICE_ACCOUNT_USER  MIXPANEL_SERVICE_ACCOUNT_SECRET  MIXPANEL_REGION
REDSHIFT_HOST  REDSHIFT_PORT  REDSHIFT_DB  REDSHIFT_USER  REDSHIFT_PASSWORD  REDSHIFT_IAM_ROLE_ARN
S3_RAW_BUCKET  S3_RAW_PREFIX  AWS_REGION
REPORTING_CURRENCY  REPORTING_TZ  DEFAULT_ATTRIBUTION_MODEL  DEFAULT_LOOKBACK_DAYS
APP_AUTH_*  ALERT_SLACK_WEBHOOK
```

## 12. Glossary
DPA = Dynamic Product Ads / catalog ads · retailer_id = advertiser's SKU in Meta catalog · product set = filtered catalog subset used by an ad set · POAS = profit on ad spend · unallocated spend = ad spend not assigned to a product row · M1–M4 = attribution models (§5).

## 13. Competitor cheat-sheet (§2)
ROI Hunter: unify feed + ad platforms + analytics + margins on product ID → segment → push product sets / custom labels → dynamic creatives. Proprietary code (public GitHub only has old tracking plugins).
DeltaX: cross-channel insights, first-party tracking + cost stitching, attribution model comparison, alerts, scheduled reports, pacing, FX, Bayesian budget optimiser. Proprietary (.NET/C#, Vue.js, SQL, AWS per job posts).
