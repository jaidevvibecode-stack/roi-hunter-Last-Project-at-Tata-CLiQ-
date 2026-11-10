# Attribution trace — 5 orders, hand-derived, asserted by tests

**What this is.** The plan's P1.10 acceptance asks for real orders traced end-to-end. We cannot do that on real data
yet (no access), so this document traces the **hand-built fixture dataset** (`tests/fixtures/dataset.json`) through the
real dbt models. Every number below is asserted in `tests/integration/test_dbt_marts.py` against
`tests/fixtures/expected.json`, and each rule has an isolated unit test in
`transform/models/intermediate/unit_tests.yml`. **When real data arrives, repeat this exercise with 5 real orders**
(playbook step 7) — fixtures prove the *logic*, not the *data*.

Window: 2026-03-01 … 03-03 · lookback 7 days · delivery (Meta product-level) is fixed per day, see dataset.

## The five orders

| # | Order | Who / what happened | M1 same-SKU click | M2 halo | M4 last paid touch (Meta) |
|---|---|---|---|---|---|
| 1 | `o1` 03-01 15:00: 2×SKU-A @50 + 1×SKU-D @30 = 130 | u1 clicked **SKU-A** via `ad1` at 10:00 | **ad1/SKU-A: 1 order, 2 units, ₹100** (only the clicked SKU) | **ad1/SKU-A: 1 order, 3 units, ₹130** (whole basket) | ad1/SKU-A ₹100 **and** ad1/SKU-D ₹30 (each purchased SKU credited to the Meta ad) |
| 2 | `o2` 03-02 10:00: 1×SKU-C @40 | u2 clicked **SKU-B** via `ad1` | none — clicked ≠ bought | **ad1/SKU-B ₹40** | **ad1/SKU-C ₹40** (spend 0 that day: `ad1` did not deliver C — the row still survives) |
| 3 | `o3` 03-02 14:00: 2×SKU-C @40 = 80 | u3 clicked **SKU-C** via `ad2` 09:00, then a **Google CPC** touch at 11:00 | **ad2/SKU-C ₹80** | **ad2/SKU-C ₹80** | **none** — last paid touch was Google |
| 4 | `o4` 03-03 12:00: 1×SKU-A @50 | u4 clicked SKU-A via `ad1` on 03-02 | **ad1/SKU-A ₹50** | **ad1/SKU-A ₹50** | **ad1/SKU-A ₹50** |
| 5 | `o5` 03-10 14:00: 1×SKU-D @25 | u5 clicked SKU-D on 03-02 13:00 — **8 days** earlier | none — outside 7-day window | none | none |

Traps in the data that must NOT change results:
- `p1` appears twice with the same `$insert_id` → counted once (staging dedupe).
- An event `p7` with an empty `order_id` is invalid → ignored everywhere (`''` is turned into NULL — Redshift returns `''`, not NULL, for missing JSON keys).
- Order `o6` buys `SKU-Z`, which is **not in the catalog** → counted as *unmatched revenue* in `mart.id_match_report` (not silently dropped, not attributed).
- Two stale/invalid Meta rows (older duplicate of ad1/03-01 with spend 999; a negative-spend row) are removed in staging.
- An older catalog snapshot says SKU-A is *out of stock*; the newest says *in stock* → newest wins.

## M3 (modelled, uses Meta's own purchase value — a proxy)
Meta reports for `ad1` on 03-01: 4 purchases / ₹400. Its products that day have link clicks m1 = 200, m2 = 50 →
shares 0.8 / 0.2 → **SKU-A: 3 orders ₹320, SKU-B: 1 order ₹80**.
`ad2` on 03-03: 2 purchases / ₹200, clicks m3 = 70, m4 = 10 → **SKU-C: 2 orders ₹175, SKU-D: 0 orders ₹25**.

## Resulting mart totals (spend ₹650 in every model)
| Model | Orders | Units | Revenue | ROAS |
|---|---|---|---|---|
| M1 | 3 | 5 | ₹230 | 0.354 |
| M2 | 5 | 8 | ₹310 | 0.477 |
| M3 | 6 | – | ₹600 | 0.923 |
| M4 | 4 | 5 | ₹220 | 0.338 |

The same product can have very different ROAS by model — which is why every ROAS in the UI carries its model badge.

## Other hand-checked outputs
- `mart.spend_reconciliation`: unallocated spend 5 / 2 / 2 (ad-level 235 / 262 / 172 vs product-level 230 / 260 / 170).
- `mart.id_match_report`: spend match 03-02 = 250/260 (product `m9` is not in the catalog); revenue match 03-02 = 120/130 (SKU-Z).
- `mart.oos_spend_daily`: SKU-B is out of stock yet spent ₹50 (03-01) and ₹30 (03-02).
- `mart.product_segments` (thresholds 50 / 0.4 / p50): SKU-A Stars, SKU-C Bleeders, SKU-B and SKU-D Zombies — and the API's Python segmentation returns the identical result.

## Bugs this exercise found (all fixed, each now guarded by a test)
1. `{{ad.id}}` inside a SQL comment was evaluated by Jinja (model failed to compile).
2. `product_performance_daily` selected a column that does not exist (`p.product_key`).
3. Missing JSON keys come back as `''` on Redshift, so every `is not null` filter was a no-op → one order with no `order_id` was credited.
4. A plain `LEFT JOIN` silently dropped attributed revenue when the product had no delivery that day (M2/M4) → now a `FULL OUTER JOIN`.
5. Header-only seed file got integer column types.
