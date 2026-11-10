# ADR 0004 — Product ROAS comes from first-party data, in four labelled models

**Status:** accepted · **Date:** 2026-09-23 (re-confirmed 2026-10-21)

Meta removed per-product conversion breakdowns off-Meta (April 2021), so per-product revenue must come from
Mixpanel/Redshift. Four models are computed and stored (M1 same-SKU click, M2 halo, M3 modelled, M4 last paid touch);
the UI shows a model badge next to every ROAS. Revenue attributed with no same-day delivery is kept (spend 0) instead
of dropped. `docs/validation/attribution_trace.md` documents the rules on worked examples.
