# 02_INSTRUCTIONS.md — Operating Rules for the Coding Agent

> You are building the product-level ad performance platform described in `01_DESIGN.md`, following `04_PLAN.md`.
> These rules override your defaults. If a rule conflicts with a user message, follow the user and log it in `03_CONTEXT.md → Decisions`.

---

## 1. Session start routine (do this every session, in order)

1. Read `03_CONTEXT.md` fully (it is short on purpose).
2. Open `04_PLAN.md` and find the **first unchecked task** in the current phase.
3. Read **only** the `01_DESIGN.md` sections that task references (section numbers are listed in each task). Do not re-read the whole design every session — it wastes tokens.
4. Check `03_CONTEXT.md → Open Questions / Blockers`. If the current task depends on an unanswered item, **ask the user first** (Section 3) and do not start the task.
5. State in one short message: current task ID, what you will do, what you need (if anything).

## 2. Core principles

1. **Practical over clever.** Smallest working solution that meets the acceptance criteria. No speculative abstractions, no premature microservices.
2. **Verify, never assume.** Every external fact (API field, breakdown behaviour, table/column name, event/property name, permission) must be confirmed against the live system or official documentation before code depends on it. Record the verification in CONTEXT.
3. **No fabrication.** Never invent column names, Mixpanel property names, catalog IDs, account IDs, tokens, FX rates, margins, or sample numbers in production paths. Mock data is allowed only in `tests/` and clearly labelled fixtures.
4. **Read-only by default.** Phase 1 never writes to Meta, Mixpanel, or existing Redshift schemas. Writes happen only to our own schemas (`raw_meta`, `raw_mixpanel`, `stg`, `int`, `mart`, `ops`) after the user approves creating them.
5. **Truth over pretty numbers.** Never silently reconcile, clip, or hide discrepancies. Show unallocated spend, match rates, and model labels.
6. **Idempotent and resumable.** Every job can be re-run for any date range without duplicates.
7. **Small, reviewable steps.** One PLAN task per branch/PR where possible.

## 3. The ASK-FIRST protocol (mandatory)

### 3.1 You MUST stop and ask the user when:
- You need any credential, token, ID, URL, account access, or permission.
- You need a table/column/event/property name you have not seen in a live response or a schema the user gave you.
- A business definition is ambiguous (revenue definition, "cost to show", attribution window, currency, timezone, what counts as a "product").
- You are about to create infrastructure, schemas, cloud resources, or anything that costs money.
- You are about to choose between two reasonable designs with different trade-offs the user would care about (cost, speed, accuracy).
- A spike result contradicts `01_DESIGN.md`.
- You would need to perform any write/mutating action on an external system.
- A task is blocked for more than one attempt.

### 3.2 How to ask (use this exact format)

```
🟡 NEED FROM YOU — [Task ID]
What I need: <precise item, e.g., "Meta System User access token with ads_read + catalog read for ad accounts act_…">
Why: <one sentence tied to the task>
How to get it: <step-by-step where to find/create it>
Format to send: <e.g., "paste into .env as META_ACCESS_TOKEN — do not paste secrets in chat if you use a shared log">
Meanwhile I will: <what you can safely do in parallel, or "wait">
```

Batch related questions into one message (max ~5 items). Put every open question into `03_CONTEXT.md → Open Questions` with status.

### 3.3 After the user answers
- Record the answer (non-secret) in `03_CONTEXT.md` → Decisions or Facts.
- Secrets go to `.env` / secret manager only — never into docs, code, logs, commits.

## 4. The INFEASIBILITY protocol (mandatory)

When something cannot be done as specified, say so plainly. Never quietly deliver a lesser version.

```
🔴 NOT POSSIBLE AS SPECIFIED — [Task ID]
Requirement: <what was asked>
Why not: <root cause, e.g., "Meta Insights API does not return off-Meta purchases with the product_id breakdown">
Evidence: <API response snippet / doc link / error code>
Alternatives:
  A) <option> — Feasible: YES/NO/PARTIAL — Accuracy: <…> — Effort: <S/M/L> — Needs from you: <…>
  B) <option> — Feasible: … 
Recommendation: <A or B and why>
Decision needed: <exact question>
```

Known cases where this protocol will likely fire (pre-researched; still verify):
- Product-level purchases/revenue from Meta → not available; alternative = first-party attribution (DESIGN §5).
- Historical ad_id attribution when `{{ad.id}}` UTMs were not set → no backfill possible; alternatives = M3 proportional model for history, fix URL params going forward.
- Product rows for non-catalog ads → not provided by Meta; alternative = URL/naming mapping (Phase 2).
- Exact match to Ads Manager totals → breakdowns are estimated; alternative = show reconciliation with tolerance.

Use `🟢 DONE`, `🟡 NEED FROM YOU`, `🔴 NOT POSSIBLE`, `⚠️ RISK` prefixes consistently so the user can scan.

## 5. Spike-first rule

Before building any integration, run a **spike script** in `/scripts/spikes/` that makes the smallest real call and saves a **redacted** sample response to `/docs/samples/` (strip tokens, emails, phones, names of people). Then:
1. Compare against DESIGN assumptions.
2. Record findings in `03_CONTEXT.md → Verified Facts` (one line each, with date).
3. Only then write the production integration.

Mandatory spikes are listed in PLAN Phase 0.

## 6. Coding standards

**Python (ingestion, backend)**
- Python 3.11+, `uv` or `pip-tools` for locked deps, `ruff` + `black` + `mypy --strict` on new modules.
- Config via `pydantic-settings`; all env var names listed in `.env.example` and `03_CONTEXT.md`.
- HTTP: timeouts on every call; `tenacity` retries with exponential backoff + jitter only for retryable errors; log Meta rate-limit headers.
- Money: `Decimal` in Python, `DECIMAL(18,6)` in Redshift. Never float for spend/revenue.
- Dates: timezone-aware datetimes; store UTC; derive `report_date` in ad-account tz.
- Logging: structured JSON, include `run_id`, `source`, `account_id`, `date`; never log tokens or PII.
- No SQL string concatenation with user input — parameterise; whitelist identifiers.

**SQL / dbt**
- snake_case; one model per file; CTE style; explicit column lists (no `SELECT *` in marts).
- Every mart has: primary-key uniqueness test, not-null tests, and a description.
- Ratios computed from sums at query time; never stored averaged ratios in aggregate tables.

**Frontend**
- TypeScript strict; API types generated from backend OpenAPI schema (`openapi-typescript`), not hand-written.
- Server state via TanStack Query; table via TanStack Table with virtualisation.
- No business logic in components — metric math lives in SQL/backend.

**Tests**
- Unit tests for parsers (product_id parsing, action extraction, FX), attribution models (hand-built fixtures with known answers), API query builders.
- Integration test per ingestion source against recorded redacted fixtures.
- dbt tests run in CI.
- Minimum: every PLAN task's acceptance criteria has at least one automated check where feasible.

**Git**
- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`), branch per task `task/P1.3-product-insights`.
- Never commit `.env`, tokens, raw data dumps, or unredacted samples.

## 7. Definition of Done (per task)

A task is done only when all are true:
1. Acceptance criteria in `04_PLAN.md` are met and demonstrated (command output, screenshot description, or query result).
2. Tests added/updated and passing; linters clean.
3. `03_CONTEXT.md` updated: Status, Verified Facts, Decisions (if any).
4. `04_PLAN.md` checkbox ticked with date and a one-line note.
5. Runbook/README updated if an operator would need to know.
6. Report to the user with `🟢 DONE — [Task ID]`: what changed, how verified, what's next, anything needed.

## 8. Validation discipline (numbers must be right)

- After Meta ingestion works, ask the user for Ads Manager exports/screenshots for 2–3 dates (breakdown: by product, and campaign totals) and compare. Record results in `/docs/validation/`.
- After attribution works, pick 5 real orders and trace them end-to-end (click → landing → order → attributed row). Document in `/docs/validation/`.
- If numbers differ beyond tolerance, investigate before moving on; report with `⚠️ RISK` if unexplained.

## 9. Token-saving rules

- Keep `03_CONTEXT.md` under ~250 lines: facts, decisions, status. Move long material to `/docs/adr/` or `/docs/samples/` and link.
- Refer to design sections by number instead of pasting them.
- Don't re-print entire files in messages; show diffs or the changed function.
- Summaries to the user: max ~15 lines unless they ask for more.

## 10. Things you must never do

- Never change ad budgets, bids, statuses, catalogs, or product sets (until an approved Phase 2+ task says so, with dry-run and audit log).
- Never delete or alter existing Redshift tables outside our schemas.
- Never store or print access tokens, user emails, phone numbers.
- Never mark a task done with failing tests or unverified numbers.
- Never replace a missing data source with synthetic data in the dashboard.
- Never widen scope (creative studio, campaign launcher, own tracking SDK) without the user asking.
