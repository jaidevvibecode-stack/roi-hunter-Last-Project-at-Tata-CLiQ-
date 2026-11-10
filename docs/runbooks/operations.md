# Operations runbook

All commands run from the repo root with the project environment active. Everything is idempotent: re-running a day
replaces that day's partition, it never duplicates rows.

## Daily operation
The scheduler container runs the whole pipeline every day at 06:30 (`REPORTING_TZ`, default Asia/Kolkata):
objects + catalog snapshots -> Meta Pull A/B (trailing 7 days; **28 days on Mondays**) -> Mixpanel (last 3 days) -> `dbt build` -> data-quality checks -> Slack alert on any failure.

```bash
docker compose -f infra/docker-compose.yml up -d pipeline        # long-running scheduler
python -m pipeline.run_daily                                      # run once now
python -m pipeline.run_daily --steps dbt,dq                      # subset
python -m pipeline.run_daily --date 2026-03-04 --dry-run         # show the plan, run nothing
python -m pipeline.doctor                                         # read-only readiness check (env, tokens, scopes, grants)
```

## Backfill / re-pull
```bash
python -m ingestion.cli trailing --days 7
python -m ingestion.cli backfill --source meta_ad      --from 2026-01-01 --to 2026-03-31
python -m ingestion.cli backfill --source meta_product --from 2026-01-01 --to 2026-03-31 --accounts act_1,act_2
python -m ingestion.cli backfill --source mixpanel     --from 2026-03-01 --to 2026-03-03
python -m ingestion.cli backfill --source meta_ad --from 2026-03-01 --to 2026-03-03 --force   # ignore checkpoints
```
Finished day-chunks are skipped on re-run (`ops.ingestion_checkpoints`); failed ones are retried automatically.
Oversized Pull B reports are split by campaign, then ad set.

## dbt
```bash
cd transform && dbt deps && dbt build                     # models + tests + attribution unit tests
dbt build --select staging+                               # staging and everything downstream
```

## Check health
```sql
SELECT check_name, status, observed, threshold, run_at FROM ops.dq_results ORDER BY run_at DESC LIMIT 20;
SELECT source, status, rows_loaded, error FROM ops.ingestion_runs ORDER BY started_at DESC LIMIT 20;
```
The same data feeds the dashboard's **Data Health** page.

## Token rotation (Meta)
1. Business Manager -> System Users -> select the service user -> Generate New Token (`ads_read` + catalog read only).
2. Update `META_ACCESS_TOKEN` in the secret manager; restart the `pipeline` container.
3. `python -m pipeline.doctor` — confirms validity and that the token is read-only.
4. Log the rotation date in `03_CONTEXT.md` -> Decisions.

## Adding an ad account
1. Append it to `META_AD_ACCOUNT_IDS`; make sure the system user has `ads_read` on it.
2. `python -m ingestion.cli backfill --source meta_ad --from <90d ago> --to <yesterday> --accounts act_NEW` (then `meta_product`).

## Incident response
1. Slack alert or non-zero exit -> read the summary (which step failed, which DQ checks).
2. `ops.ingestion_runs.error` has the failed chunks; re-run the same command, only failed chunks are retried.
3. Meta rate-limited: wait 30–60 min and re-run. Redshift unreachable: check security group / VPC.
4. Wrong numbers on the dashboard: check **Data Health** first (freshness, ID-match rates, reconciliation gap).
