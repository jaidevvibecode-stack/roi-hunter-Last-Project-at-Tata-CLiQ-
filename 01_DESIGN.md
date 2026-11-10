# 01_DESIGN.md — Product-Level Ad Performance Platform

> System design for a SKU-level advertising analytics platform modelled on ROI Hunter and DeltaX.
> Phase 1 = Meta product-level dashboard. Phase 2 = profit + automation. Phase 3 = cross-platform SKU intelligence.
> Read `03_CONTEXT.md` first; come here for the section you need, not the whole file.

---

## 0. Table of contents

1. Goal and success criteria
2. Competitive research: ROI Hunter and DeltaX (what they do, how, codebases)
3. The hard truth about Meta product-level data (read before building anything)
4. Metric definitions (single source of truth)
5. Attribution methodology for product-level ROAS
6. System architecture
7. Data sources and ingestion design
8. Redshift data model
9. Transformation layer (dbt)
10. Backend API
11. Frontend dashboard
12. Data quality, reconciliation and observability
13. Security and access
14. Phase 2 design (profit + automation)
15. Phase 3 design (cross-platform)
16. Feature parity map vs ROI Hunter / DeltaX
17. Known risks and non-goals

---

## 1. Goal and success criteria

### Phase 1 deliverable
A web dashboard where a user picks a date range and sees, **per product (SKU / catalog item)**:

| Metric | Source |
|---|---|
| Cost to show ads (Spend, CPM, cost per impression, CPC) | Meta Insights API, `product_id` breakdown |
| Impressions | Meta Insights API, `product_id` breakdown |
| Clicks (link clicks primary, all clicks secondary) | Meta Insights API, `product_id` breakdown |
| CTR | Derived: link_clicks / impressions |
| ROAS | Derived: first-party attributed revenue (Mixpanel/Redshift) / Meta product spend |

Plus filters (date, account, campaign, ad set, ad, category, brand, availability), sorting, product drill-down, trend charts, CSV export, and a data-health page.

> **Open definition — the agent must confirm with the user:** "cost to show an ad per product" is interpreted as **Spend per product** (headline) with **CPM** and **cost per impression** as supporting columns. If the user means something else (e.g., cost per click, or a unit-economics "cost to serve"), stop and re-spec.

### Success criteria (Phase 1 acceptance)
1. Sum of product-level spend for a date range reconciles to Ads Manager catalog-ad spend within **±2%** (breakdown values are estimated by Meta; the unexplained gap is shown as "unallocated spend", never hidden).
2. ≥ 95% of spend maps to a known product in the catalog dimension (ID match rate).
3. ≥ 90% of first-party purchase revenue for catalog products maps to a Meta catalog item (SKU match rate) — or a documented reason why not.
4. Dashboard loads the product table for 30 days in < 3 s (p95) for up to 50k products.
5. Data refreshes daily automatically; freshness visible in UI.
6. Every ROAS number displays which attribution model produced it.

---

## 2. Competitive research: ROI Hunter and DeltaX

### 2.1 ROI Hunter (Brno, Czech Republic; founded 2014; acquired by Pattern, Dec 2025)

**What it is.** A "Product Performance Management" / catalog-advertising platform for e-commerce. Its core idea: merge product feed data + ad platform data + analytics + business data (margin, returns, reviews, stock) into one SKU-level view, then use that view to decide which products get promoted.

**Core mechanism (reverse-engineered from public material):**
1. **Ingest the product feed/catalog** (XML/CSV feed, Meta catalog, Google Merchant Center).
2. **Ingest ad-platform product-level delivery** (Meta DPA/Advantage+ catalog ads, Google PMax/Shopping, Snap DPA; TikTok in beta).
3. **Ingest analytics** (GA4, Adobe Analytics, Branch.io) to get product-level revenue/conversions the ad platforms won't give.
4. **Ingest business data** (margins, return rates, reviews, new arrivals, deadstock).
5. **Unify on product ID** → one product-level report.
6. **Segment products** by rules/metrics (e.g., high margin + low exposure = "under-promoted"; high spend + high return rate = "exclude").
7. **Act**: push segments back as **product sets / custom labels** to the ad platforms, launch/pause/scale campaigns, generate **dynamic creative templates** (price/image/name layers) per product.
8. Their stated problem statement: platform algorithms concentrate spend on a small fraction of the catalog (they cite ~80% of spend on <10% of products) and optimise for engagement rather than profit.

**Codebase.** Proprietary. The public GitHub org (`github.com/roihunter`) contains only archived e-commerce plugins (Magento 1, WooCommerce, PrestaShop — "ROI Hunter Easy", which installed tracking/remarketing), a Facebook-webhook proxy, and hiring task repos. **There is no public source for their analytics engine.** What the plugins reveal: they capture product/cart/order/page DTOs on-site (i.e., their own first-party product-level tracking) — the same role Mixpanel plays for us.

### 2.2 DeltaX (Bengaluru, India; founded 2012)

**What it is.** A cross-channel ad platform for agencies and advertisers: buy, track, attribute, optimise and report across search, social, display, video, Amazon.

**Three modules:**
- **Insights** — unified view across media + analytics + CRM; cross-channel planning; alerts/rule-based notifications; scheduled reports (Excel/PPT/CSV/PDF); currency conversion to a reporting currency; unified API; a **Portfolio Optimizer** using high-frequency Bayesian optimisation for bid/budget across Google, Meta, Amazon; media-plan pacing (planned vs actual); an AI "Assistant" with account health scores and one-click-apply suggestions.
- **Measurement** — deterministic first-party tracking (web tags, iOS/Android SDKs, first-party domains, S2S); multi-goal tracking; built-in ETL to **stitch tracking data with publisher cost**; single-touch, multi-touch and data-driven attribution with a **model comparison** tool; CRM/offline conversion import; feeding quality signals back to platforms; affiliate tracking; data export to S3/warehouse.
- **Creative Solutions (DCO)** — feed-driven dynamic creatives, localisation, real-time triggers (weather, sports scores), bulk launch.

**Codebase.** Proprietary. From public job postings: C#/.NET (ASP.NET MVC historically), REST APIs, Vue.js front-end, SQL, services integrating Google Ads / Meta Marketing / Bing APIs; ad-serving, tracking and attribution stack on AWS, horizontally scaled.

### 2.3 What we copy (the *mechanism*, not the code)

| Concept | From | Our implementation |
|---|---|---|
| SKU-level single source of truth | ROI Hunter | `mart.product_performance_daily` in Redshift keyed on canonical `product_key` |
| Platform delivery + first-party revenue join | Both | Meta `product_id` breakdown ⨝ Mixpanel/Redshift purchases on SKU + ad_id |
| Stitch tracking with publisher cost (built-in ETL) | DeltaX | Python ingestion + dbt |
| Attribution model comparison | DeltaX | Multiple attribution models side-by-side (Section 5) |
| Product segmentation → product sets | ROI Hunter | Phase 2 segmentation + custom-label write-back |
| Margin-aware decisions (POAS) | ROI Hunter | Phase 2 |
| Alerts, scheduled reports, pacing, currency conversion | DeltaX | Phase 2 |
| Bayesian budget optimiser | DeltaX | Phase 3 (recommendation-only first) |
| Cross-channel product view | Both | Phase 3 channel adapters |
| Dynamic creative templates | Both | **Non-goal** unless explicitly requested (large separate product) |

---

## 3. The hard truth about Meta product-level data

These constraints drive the entire design. The coding agent must **verify each one in the Phase 0 spike** against the live account rather than trusting this document blindly.

1. **`product_id` is a breakdown on the Insights API** — available for catalog/dynamic (DPA, Advantage+ catalog) ads. It returns on-Meta metrics per product: `spend`, `impressions`, `clicks`, `inline_link_clicks`, and derived fields.
2. **Off-Meta conversions are NOT broken down by `product_id`** (Meta restriction since 27 April 2021). Web purchases/purchase value returned with this breakdown will not carry the product value. ⇒ **Meta cannot tell us revenue per product. ROAS per product must come from first-party data (Mixpanel/Redshift).**
3. **Breakdown values are estimated.** Summed product rows won't exactly equal ad-level totals → we store both levels and show the difference as "unallocated".
4. **High cardinality.** ads × products × days can be millions of rows. Use **async report runs**, `time_increment=1`, chunk by day (and by ad set/campaign if a job fails), respect rate-limit headers.
5. **Only catalog ads have product rows.** Non-catalog ads (single image/video of one product) must be mapped to products another way (Phase 2: ad→product mapping via landing URL or naming convention; ask user).
6. **The `product_id` value format** must be inspected in the spike (it may be Meta's internal catalog item ID and/or include the product name). It must be mapped to `retailer_id` (your SKU) via the Catalog API `/{catalog_id}/products` (fields: `id`, `retailer_id`, `name`, `category`, `brand`, `price`, `availability`, `product_type`, `custom_label_0..4`, `image_url`, `url`).
7. **Attribution settings.** Ad-level Meta purchases/`action_values` depend on attribution windows; the API default differs from Ads Manager unless `use_unified_attribution_setting=true`. Store the setting used in every row.
8. **Restatement.** Meta metrics can change for days after the fact (conversions up to ~28 days). Re-pull trailing windows.
9. **History limit.** Insights are retrievable for roughly the trailing 37 months only.
10. **API version.** Pin the Graph API version in config (docs currently show v25.x). Never hardcode in multiple places.

---

## 4. Metric definitions (single source of truth)

**Rule: ratios are always recomputed from summed components at the requested grain. Never average ratios.**

| Metric | Formula | Null rule |
|---|---|---|
| `spend` | Σ spend (account currency → reporting currency) | 0 |
| `impressions` | Σ impressions | 0 |
| `link_clicks` | Σ inline_link_clicks | 0 |
| `clicks_all` | Σ clicks | 0 |
| `ctr` | link_clicks / impressions | NULL if impressions = 0 |
| `ctr_all` | clicks_all / impressions | NULL if impressions = 0 |
| `cpm` | spend / impressions × 1000 | NULL if impressions = 0 |
| `cost_per_impression` | spend / impressions | NULL if impressions = 0 |
| `cpc` | spend / link_clicks | NULL if link_clicks = 0 |
| `attributed_revenue[model]` | Σ revenue per attribution model (Section 5) | 0 |
| `attributed_orders[model]` | Σ distinct orders | 0 |
| `attributed_units[model]` | Σ units | 0 |
| `roas[model]` | attributed_revenue / spend | NULL if spend = 0 |
| `cvr[model]` | attributed_orders / link_clicks | NULL if link_clicks = 0 |
| `aov[model]` | attributed_revenue / attributed_orders | NULL if 0 orders |
| `unallocated_spend` | ad-level catalog spend − Σ product-level spend | — |
| `spend_share` | product spend / total product spend in filter | — |

Phase 2 adds: `gross_profit = revenue − COGS − (optional) shipping/fees/returns`, `poas = gross_profit / spend`, `return_rate`, `net_revenue`.

Revenue must be defined once: **gross item revenue excluding tax and shipping, before refunds** in Phase 1 (confirm with user; alternative definitions are configuration, not code forks).

---

## 5. Attribution methodology for product-level ROAS

Because Meta withholds product-level conversions, we build our own — as ROI Hunter (GA4/Adobe) and DeltaX (own tracking) do. Every model is computed and stored; the UI has a model selector and a **Model Comparison** view.

### Prerequisites (verify in Phase 0)
- **P1. Ad ID on the click.** Ad URL parameters must include the ad ID, e.g. `utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}&utm_content={{ad.id}}`. Mixpanel must capture UTMs (it does automatically for `utm_*` on web SDK) and/or `fbclid`.
- **P2. Product ID on the landing.** The product clicked in a DPA lands on that product's page. The landing `Product Viewed` (or page view) event must carry the SKU. Optionally add a product placeholder to URL parameters if Meta supports it for the account's catalog ads (agent: check; do not assume).
- **P3. Purchase events carry line items.** Mixpanel `Order Completed`/`Purchase` event (or Redshift orders + order_items) must have SKU, quantity, price, order_id, user identity.
- **P4. ID alignment.** Meta catalog `retailer_id` == Mixpanel product id == Redshift SKU. If not, a mapping table is required (ask user for it).

If P1 is missing, only models M3/M4 are possible until URL parameters are added (going-forward only; no backfill possible). The agent must report this explicitly.

### Models

| ID | Name | Logic | Strength / weakness |
|---|---|---|---|
| **M1** | Same-SKU click attribution (default) | Purchase of SKU X within N days (default 7) after a Meta ad click session whose landing product = X. Credit to that ad_id + SKU X. | Most defensible per-product number; undercounts halo |
| **M2** | Halo / session-basket attribution | All items in orders within N days after a Meta click session that landed on SKU X are credited to X (the clicked product), split by revenue. | Shows "gateway" products that drive other purchases |
| **M3** | Proportional allocation of Meta-reported value | Meta ad-level `action_values` (purchase) allocated to products in that ad by each product's share of link clicks (fallback: impressions). | Matches Meta totals; the per-product split is modelled, label it "modelled" |
| **M4** | Purchased-SKU last-touch (first-party) | For each purchased SKU, if the order's last paid touch was a Meta ad (utm), credit the purchased SKU with that ad's product spend context. | Useful when landing product unknown |

Rules:
- Lookback window `N` configurable (1/7/28 days). Default 7-day click.
- View-through attribution is **not** available first-party; only M3 inherits Meta's view-through.
- De-duplicate orders by `order_id`; one order line credited once per model.
- Identity: use Mixpanel `distinct_id` (post-identity-merge) or user_id; document the identity rule in CONTEXT.
- Timezone: attribute in the **Meta ad account timezone** (store UTC + account tz; convert Mixpanel UTC times).
- Always show a banner: "Meta does not report conversions per product. Revenue is measured from your first-party data using model {X}."

---

## 6. System architecture

```
                ┌───────────────────── Scheduler (Phase 1: cron/GitHub Actions/ECS task; Phase 2+: Dagster or Airflow) ─────────────────────┐
                │                                                                                                                            │
 Meta Marketing API ──► ingest/meta_insights  ──┐                                                                                            │
 Meta Catalog API   ──► ingest/meta_catalog   ──┤                                                                                            │
 Meta Ads objects   ──► ingest/meta_objects   ──┼──► S3 (raw JSON/Parquet, partitioned by date) ──► Redshift COPY ──► raw_* schemas        │
 Mixpanel Export    ──► ingest/mixpanel       ──┘      (fallback: direct batched INSERT if no S3)                                            │
 (or Mixpanel Data Pipeline → Redshift directly, if already enabled)                                                                          │
 Existing Redshift orders tables ─────────────────────────────────────────────────────────────────► (read in place, never modified)         │
                                                                                                                                             │
                              dbt (Redshift): staging ► intermediate ► marts (product_performance_daily, attribution, DQ)  ◄─────────────────┘
                                                        │
                                                        ▼
                                FastAPI backend (read-only SQL on marts, caching, auth)
                                                        │
                                                        ▼
                                Next.js dashboard (TypeScript, TanStack Table, ECharts/Recharts)
```

### Default stack (agent may propose changes; user must approve)

| Layer | Choice | Why | Fallback |
|---|---|---|---|
| Ingestion | Python 3.11+, `facebook-business` SDK + `httpx`, `tenacity` retries, `pydantic` models | Official SDK, typed | Raw Graph API calls |
| Staging storage | S3 (Parquet via `pyarrow`) | Redshift COPY is fastest & cheapest | `redshift_connector` batched inserts |
| Warehouse | Amazon Redshift (existing) | Given | — |
| Transform | dbt-core + dbt-redshift | Testable SQL, lineage, docs | Plain SQL files + runner |
| Orchestration | Phase 1: simple scheduled job (cron on EC2/ECS scheduled task/GitHub Actions) | Minimal ops | Dagster (Phase 2+) |
| Backend | FastAPI + SQLAlchemy Core (no ORM for analytics), `redshift_connector` | Fast, typed | — |
| Cache | Redis (optional Phase 1) or in-process TTL cache | Dashboard speed | Redshift result cache only |
| Frontend | Next.js (App Router) + TypeScript + Tailwind + TanStack Table + ECharts | Big-table performance, rich charts | Metabase/Superset as a **temporary** Phase 1 viewer if timeline forces it (ask) |
| Auth | Ask user (Google SSO / company SSO / basic auth behind VPN) | — | — |
| Deploy | Docker; target infra: ask user (AWS ECS/EC2 likely since Redshift) | — | — |
| Secrets | AWS Secrets Manager / SSM, `.env` only locally | — | — |

Repository layout (monorepo):

```
/ingestion/            python package: meta/, mixpanel/, common/ (config, logging, s3, redshift, rate_limit)
/transform/            dbt project: models/staging, models/intermediate, models/marts, tests, macros
/backend/              FastAPI app: api/, queries/, schemas/, auth/, tests/
/frontend/             Next.js app
/infra/                Dockerfiles, compose, IaC (only if user approves)
/docs/                 01_DESIGN.md, 02_INSTRUCTIONS.md, 03_CONTEXT.md, 04_PLAN.md, runbooks/, adr/
/scripts/              spikes, one-off backfills (never used by prod paths)
```

---

## 7. Data sources and ingestion design

### 7.1 Meta Insights — two pulls

**Pull A: ad-level daily (truth for totals + Meta-reported conversions)**
- Endpoint: `POST /act_{ad_account_id}/insights` (async) → poll `/{report_run_id}` → GET `/{report_run_id}/insights`
- Params: `level=ad`, `time_increment=1`, `time_range={since,until}`, `use_unified_attribution_setting=true`, `action_report_time` (store which), fields:
  `account_id, account_currency, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name, date_start, spend, impressions, clicks, inline_link_clicks, reach, frequency, actions, action_values, purchase_roas`
- Table: `raw_meta.ad_insights_daily`

**Pull B: ad × product daily (the product-level core)**
- Same endpoint, `level=ad`, `breakdowns=product_id`, `time_increment=1`
- Fields: `account_id, campaign_id, adset_id, ad_id, date_start, spend, impressions, clicks, inline_link_clicks` (+ `actions` only to confirm in spike that off-Meta values are absent/unbroken)
- Filter to catalog ads where possible (e.g., filtering on objective/ad set promoted object product_set) to reduce empty work — verify supported filters in spike.
- Table: `raw_meta.ad_product_insights_daily`

**Chunking & limits**
- One async job per (account, single day). If a job fails with too-much-data / timeout, split by campaign, then by ad set.
- Read `x-business-use-case-usage` / `x-fb-ads-insights-throttle` headers; back off when > 75%; exponential backoff with jitter on error codes 4, 17, 613, 80000–80014 and subcode 1504022.
- Concurrency cap configurable (default 2 jobs per account).

**Windows**
- Daily run: re-pull **trailing 7 days** (restatement).
- Weekly run: re-pull **trailing 28 days**.
- Backfill command: arbitrary range, default 90 days, chunked, resumable (checkpoint table `ops.ingestion_checkpoints`).

### 7.2 Meta objects (dimensions)
- `/act_{id}/campaigns`, `/adsets`, `/ads` with fields: ids, names, status, effective_status, objective, created_time, `promoted_object`, `product_set_id` (ad set), creative `url_tags`, creative `object_story_spec`/`asset_feed_spec` summary.
- Purpose: names/status history, detect catalog ads, audit `url_tags` for `{{ad.id}}` (prerequisite P1 audit).
- Snapshot daily into `raw_meta.ads_snapshot` (SCD2 in dbt).

### 7.3 Meta Catalog
- `/{business_id}/owned_product_catalogs` → catalog IDs (or user provides IDs).
- `/{catalog_id}/products` paginated, fields listed in Section 3.6; also `/{catalog_id}/product_sets`.
- Full snapshot daily → `raw_meta.catalog_products` (with `snapshot_date`). Large catalogs: use pagination with `limit=500`; if too slow, ask about catalog feed file access instead.

### 7.4 Mixpanel
Decision tree (agent asks user which applies):
1. **Mixpanel Data Pipelines already export to Redshift/S3** → read those tables; no custom ingestion. Preferred.
2. **Not enabled, plan allows** → user enables Data Pipelines (Redshift/S3) — add-on on Growth/Enterprise plans.
3. **Otherwise** → custom ingestion via Raw Event Export API `https://data.mixpanel.com/api/2.0/export` (JSONL, service-account auth, UTC dates for newer projects, `event=[...]` filter). Pull only needed events: product view, add to cart, purchase/order completed (+ session start if used). Respect export rate limits (approx. 60 queries/hour, 3/second — verify current limits). Day-by-day, idempotent by `$insert_id`.
- Also required: the **event & property dictionary** (names of purchase event, SKU property, price, quantity, order_id, UTM props). Agent must ask; never guess property names.
- EU/IN data residency: Mixpanel EU projects use a different host — ask.

### 7.5 Redshift existing data
- Ask the user for: orders / order_items / products / COGS / returns tables, their schemas, owners, freshness, and whether we may read them. **Never write to existing schemas.** Create our own schemas: `raw_meta`, `raw_mixpanel` (if needed), `stg`, `int`, `mart`, `ops`.
- If orders in Redshift are more reliable than Mixpanel purchase events (usually true), use **Redshift orders as revenue truth** and Mixpanel only for click/session/landing linkage via order_id or user id. Agent confirms with user.

### 7.6 Currency & timezone
- Store amounts in source currency + `fx_rate` + reporting currency. FX source: ask user (fixed monthly rates vs daily API). Phase 1 may be single-currency; verify.
- Store timestamps in UTC; `report_date` in ad account timezone.

---

## 8. Redshift data model

### 8.1 Raw (append/overwrite by partition; mirror source fields)
```sql
raw_meta.ad_insights_daily(
  account_id varchar, date_start date, campaign_id varchar, adset_id varchar, ad_id varchar,
  campaign_name varchar, adset_name varchar, ad_name varchar, account_currency varchar(3),
  spend decimal(18,6), impressions bigint, clicks bigint, inline_link_clicks bigint, reach bigint, frequency decimal(12,6),
  actions super, action_values super, purchase_roas super,
  attribution_setting varchar, api_version varchar, ingested_at timestamp, run_id varchar)
  DISTKEY(ad_id) SORTKEY(date_start);

raw_meta.ad_product_insights_daily(
  account_id varchar, date_start date, campaign_id varchar, adset_id varchar, ad_id varchar,
  product_id_raw varchar(1024),           -- exactly as returned by Meta
  spend decimal(18,6), impressions bigint, clicks bigint, inline_link_clicks bigint,
  api_version varchar, ingested_at timestamp, run_id varchar)
  DISTKEY(product_id_raw) SORTKEY(date_start);

raw_meta.catalog_products(snapshot_date date, catalog_id varchar, id varchar, retailer_id varchar,
  retailer_product_group_id varchar, name varchar(1024), brand varchar, category varchar(1024), product_type varchar(1024),
  price varchar, sale_price varchar, currency varchar(3), availability varchar, url varchar(2048), image_url varchar(2048),
  custom_label_0..4 varchar, raw super, ingested_at timestamp);

raw_meta.ads_snapshot(snapshot_date date, level varchar, id varchar, parent_id varchar, name varchar, status varchar,
  effective_status varchar, objective varchar, product_set_id varchar, url_tags varchar(4096), raw super, ingested_at timestamp);

raw_mixpanel.events(event varchar, event_time timestamp, distinct_id varchar, insert_id varchar,
  properties super, ingested_at timestamp) DISTKEY(distinct_id) SORTKEY(event_time);
```

### 8.2 Ops
```sql
ops.ingestion_runs(run_id, source, started_at, finished_at, status, date_from, date_to, rows_loaded, error text);
ops.ingestion_checkpoints(source, account_id, chunk_key, date, status, updated_at);
ops.dq_results(check_name, run_at, status, observed numeric, threshold numeric, details super);
```

### 8.3 Marts (what the API reads)
```
mart.dim_product            product_key (surrogate), retailer_id, meta_item_ids[], name, brand, category_l1..l4, product_type,
                            price, availability, image_url, url, is_active, first_seen, last_seen
mart.dim_ad                 ad_id, ad_name, adset_id/name, campaign_id/name, account_id, objective, is_catalog_ad,
                            has_ad_id_utm (bool), status, valid_from, valid_to
mart.fct_ad_product_daily   report_date, account_id, campaign_id, adset_id, ad_id, product_key,
                            spend_rc, impressions, link_clicks, clicks_all      (rc = reporting currency)
mart.fct_ad_daily           report_date, ad_id, spend_rc, impressions, link_clicks, meta_purchases, meta_purchase_value_rc
mart.fct_product_attribution_daily
                            report_date, ad_id, product_key, attribution_model, lookback_days,
                            orders, units, revenue_rc
mart.product_performance_daily   (the main serving table; one row per report_date × ad_id × product_key × attribution_model)
mart.product_performance_summary_* (optional pre-aggregations: by product×day, by product×campaign×day)
mart.id_match_report        daily match-rate stats (spend matched to catalog, revenue matched to catalog)
mart.spend_reconciliation   report_date, ad_level_catalog_spend, product_level_spend, unallocated_spend, pct
```
Serving table sort key: `report_date`; dist key: `product_key` (or `EVEN` if skewed — measure).

---

## 9. Transformation layer (dbt)

- `stg_meta__ad_product_insights`: parse `product_id_raw` → `meta_item_id` (rule determined in spike; document in CONTEXT), cast types, dedupe on (date, ad_id, meta_item_id) keeping latest `ingested_at`.
- `stg_meta__catalog_products`: latest snapshot per item; normalise category path.
- `int_product_key_map`: meta_item_id ↔ retailer_id ↔ mixpanel sku ↔ redshift sku (+ optional user-supplied mapping seed `seeds/sku_mapping.csv`).
- `int_meta_click_sessions`: Mixpanel sessions/landings with `utm_content` (ad_id) or `fbclid`, landing SKU.
- `int_orders_lines`: canonical order lines (Redshift orders preferred, else Mixpanel purchase events).
- `int_attribution_m1..m4`: one model per file, each tested.
- Marts as above.
- dbt tests: unique/not_null keys, accepted_values, relationships, custom tests: spend reconciliation, match-rate thresholds, no negative metrics, row-count anomaly vs 7-day average.
- Incremental models with `delete+insert` on `report_date` for trailing windows.

---

## 10. Backend API (FastAPI, read-only)

Base: `/api/v1`. All endpoints accept: `start_date`, `end_date`, `compare_start`, `compare_end` (optional), `account_ids[]`, `campaign_ids[]`, `adset_ids[]`, `ad_ids[]`, `categories[]`, `brands[]`, `availability[]`, `attribution_model` (default M1), `lookback_days`, `currency`.

| Endpoint | Returns |
|---|---|
| `GET /meta/freshness` | last successful run per source, latest data date |
| `GET /overview` | KPI totals (spend, impressions, link_clicks, CTR, CPM, CPC, revenue, ROAS, unallocated spend) + deltas vs compare period |
| `GET /products` | paginated product table; `sort`, `order`, `page`, `page_size` (≤500), `search`; columns per Section 4 |
| `GET /products/{product_key}` | product detail: attributes + totals |
| `GET /products/{product_key}/trend` | daily series |
| `GET /products/{product_key}/breakdown?by=campaign|adset|ad` | where the product's spend went |
| `GET /trends` | daily totals |
| `GET /filters/options` | distinct accounts, campaigns, categories, brands (scoped to date range) |
| `GET /attribution/compare` | per-product ROAS under all models |
| `GET /data-quality` | latest DQ results, match rates, reconciliation |
| `GET /export/products.csv` | streaming CSV of current table view |

Rules: parameterised SQL only; whitelist sort columns; ratios computed in SQL from sums; response models in `pydantic`; p95 < 3s; TTL cache keyed on normalised params; auth middleware on everything except `/health`.

---

## 11. Frontend dashboard

### Pages
1. **Overview** — KPI cards (Spend, Impressions, Link clicks, CTR, CPM, ROAS, Revenue, Unallocated spend) with period-over-period deltas; daily trend chart (spend vs revenue, dual axis); top 10 / bottom 10 products by spend and by ROAS; spend concentration chart (Pareto: % of spend on top x% of products — the ROI Hunter headline insight).
2. **Products** (primary Phase 1 screen) — virtualised table: image thumb, name, SKU, category, brand, availability, Spend, Impressions, CPM, Cost/impression, Link clicks, CTR, CPC, Orders, Revenue, ROAS, Spend share. Column chooser, sticky header, multi-sort, search, filters drawer, CSV export, attribution model selector with tooltip explaining the model.
3. **Product detail** — attributes, KPI cards, trend chart, breakdown by campaign/ad set/ad, attribution model comparison table.
4. **Campaign → Products drill-down** — choose campaign/ad set/ad, see its product distribution.
5. **Data health** — freshness per source, ID match rates, spend reconciliation chart, DQ check list, latest ingestion runs.
6. (Phase 2) **Segments**, **Alerts**, **Reports**. (Phase 3) **Channels**.

### UX rules
- Global filter bar persisted in URL query params (shareable links).
- Every ROAS shows model badge (e.g., "M1 · 7d click").
- Empty/NULL ratios render as "—", never 0 or ∞.
- Currency and number formatting locale-aware (ask user: INR lakh/crore formatting or international).
- Loading skeletons; error states with retry; no silent failures.
- Accessibility: keyboard navigable table, colour-blind-safe palette, contrast AA.

---

## 12. Data quality, reconciliation and observability

Checks (dbt tests + `ops.dq_results`), each with threshold and severity:
- Freshness: Meta data for yesterday present by 09:00 account tz (warn), missing 2 days (error).
- Spend reconciliation: |unallocated_spend| / ad-level catalog spend ≤ 2% (warn), ≤ 5% (error).
- Spend → catalog match ≥ 95%; revenue → catalog match ≥ 90%.
- Row-count anomaly: today vs trailing 7-day mean ±50% (warn).
- UTM coverage: % of active catalog ads with `{{ad.id}}` in url_tags (warn < 100%).
- Duplicate primary keys = 0 (error).
- **Manual validation protocol**: for 3 random products × 3 dates, compare against Ads Manager (breakdown by product) screenshots supplied by user; record in `docs/validation/`.

Observability: structured JSON logs, run IDs propagated, alert on failed runs (Slack/email — ask user for channel).

---

## 13. Security and access

- Meta: **System User access token** from Business Manager (non-expiring or long-lived), scopes at minimum `ads_read` + catalog read access (`catalog_management` if reading/writing catalogs; Phase 2 write-back requires it). App must have appropriate Marketing API access tier; standard access improves rate limits.
- Phase 1 is strictly **read-only** against Meta. Any write (product sets, custom labels, budgets) is Phase 2+ and requires explicit user approval per feature.
- Redshift: dedicated service user with `SELECT` on source tables, `ALL` only on our schemas.
- Secrets never in git; `.env.example` lists names only.
- PII: do not pull emails/phones from Mixpanel; hash or drop user identifiers not needed for attribution; ask user about data policies (DPDP Act for India, GDPR if EU users).
- Dashboard auth mandatory before any deploy beyond localhost.

---

## 14. Phase 2 design (profit + automation) — "ROI Hunter core"

1. **Profitability**: ingest COGS/margin per SKU (Redshift table or CSV seed — ask), shipping/fees, returns → `gross_profit`, `poas`, `net_roas`, `return_rate`.
2. **Non-catalog ad → product mapping**: rules by landing URL SKU, UTM, or naming convention (ask user which exists).
3. **Product segmentation engine**: configurable rule sets, default quadrant model on spend/impressions vs CTR/ROAS/POAS:
   - Star (high exposure, high return), Promising/under-promoted (low exposure, high return), Window-shopper/over-promoted (high exposure, low return), Low priority.
   - Plus business rules: out-of-stock, high return rate, new arrival, low margin.
   - Output: `mart.product_segments_daily` + UI Segments page.
4. **Feed write-back (optional, needs approval)**: push segment as `custom_label_N` via catalog batch API or supplementary feed so Meta product sets can target segments. Dry-run mode + diff preview + audit log mandatory.
5. **Alerts & rules** (DeltaX-style): threshold/anomaly rules (e.g., product ROAS < X with spend > Y for 3 days) → Slack/email; recommendation-only.
6. **Scheduled reports**: weekly CSV/XLSX/PDF email.
7. **Attribution model comparison UI** and configurable windows.
8. **Pacing**: planned vs actual spend by campaign/month (user uploads plan).
9. **Inventory awareness**: flag spend on out-of-stock SKUs (from catalog availability history).
10. **Orchestration upgrade** to Dagster/Airflow if job count justifies.

## 15. Phase 3 design (cross-platform) — "ROI Hunter + DeltaX breadth"

1. **Channel adapter interface** (`ingestion/common/channel.py`): `fetch_product_delivery(date)`, `fetch_ad_delivery(date)`, `fetch_catalog()`, returning a normalised schema with `channel` column.
2. **Adapters** (each needs credentials/approval; each verified by a spike):
   - Google Ads — Shopping/PMax product-level via GAQL `shopping_performance_view` (product item id; conversions are available at product level there — verify).
   - Google Merchant Center — product status, price competitiveness, disapprovals.
   - TikTok Ads (catalog/Smart+), Snapchat (DPA), Pinterest (shopping) — capabilities differ; each adapter documents what is and isn't available per product.
   - GA4 BigQuery export (if the user has it) as an additional first-party source.
3. **Unified mart** `mart.channel_product_performance_daily` (channel × product × day) and cross-channel product scorecard; cross-channel dedupe of first-party revenue (a single order credited once per model, with channel path).
4. **Multi-touch attribution** over first-party journeys (linear, time-decay, position-based/U-shaped, first/last touch) + model comparison.
5. **Budget optimisation**: Bayesian model of product/campaign response curves → **recommendations** first; automated execution only with explicit approval, caps and kill-switch.
6. **Incrementality**: support for geo/holdout test readouts (design only unless requested).
7. **Deeper SKU data**: variant grouping (`retailer_product_group_id`), price-change impact, stock-days, lifecycle stage, new vs returning customers, LTV per acquiring product.
8. **Reporting API** for other internal consumers.

---

## 16. Feature parity map

| Capability | ROI Hunter | DeltaX | Our phase |
|---|---|---|---|
| Product-level spend/impr/clicks/CTR | ✔ | partial | **1** |
| Product-level revenue/ROAS via first-party join | ✔ | ✔ (own tracking) | **1** |
| Data health / reconciliation | internal | ✔ | **1** |
| Margin / POAS / returns | ✔ | — | 2 |
| Product segmentation + product sets write-back | ✔ | — | 2 |
| Alerts, scheduled reports, pacing, FX | partial | ✔ | 2 |
| Attribution model comparison | — | ✔ | 2 (basic in 1) |
| Cross-channel product view | ✔ (Meta/Google/Snap/TikTok) | ✔ (100+ channels) | 3 |
| Multi-touch / data-driven attribution | — | ✔ | 3 |
| Bayesian budget optimiser | — | ✔ | 3 |
| Own tracking SDK / first-party domain | plugins | ✔ | Non-goal (Mixpanel covers) |
| Dynamic creative templates / DCO | ✔ | ✔ | Non-goal unless requested |
| Campaign creation/launch UI | ✔ | ✔ | Non-goal unless requested |

## 17. Known risks and non-goals

Risks: missing `{{ad.id}}` UTMs (no backfill possible); SKU ID mismatch across systems; Meta estimation gaps; API/permission changes; Mixpanel identity merge issues; high cardinality costs on Redshift; attribution disagreement with Ads Manager (expected — explain, don't "fix").

Non-goals (unless the user explicitly adds them): building an ad server, a tracking SDK, a creative studio, a campaign launcher, or any automated spend change without human approval.
