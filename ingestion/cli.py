"""
ingestion/cli.py — command-line entry point for backfills and trailing re-pulls.

  python -m ingestion.cli trailing --days 7
  python -m ingestion.cli backfill --source meta_ad --from 2026-01-01 --to 2026-03-31 [--accounts act_1,act_2]
  python -m ingestion.cli backfill --source mixpanel --from 2026-03-01 --to 2026-03-03
  python -m ingestion.cli catalog | objects
  python -m ingestion.cli init-schemas --i-have-approval      # creates OUR schemas (raw_meta/raw_mixpanel/ops)

All loads are idempotent and resumable (ops.ingestion_checkpoints). Read-only against Meta and Mixpanel.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import click

from ingestion.common.config import get_settings
from ingestion.common.logging_utils import setup_logging
from ingestion.common.redshift import RedshiftLoader, get_connection
from ingestion.jobs import (
    JobResult,
    days_between,
    run_meta_catalog,
    run_meta_insights,
    run_meta_objects,
    run_mixpanel,
)

SOURCES = ("meta_ad", "meta_product", "mixpanel")


def _loader() -> RedshiftLoader:
    r = get_settings().redshift
    if not r.is_configured():
        raise click.ClickException("Redshift not configured (REDSHIFT_HOST/DB/USER/PASSWORD).")
    return RedshiftLoader(get_connection(r.host, r.port, r.db, r.user, r.password), r.iam_role_arn)


def _accounts(accounts: str | None) -> list[str]:
    ids = [a.strip() for a in accounts.split(",")] if accounts else get_settings().meta.ad_account_ids
    if not ids:
        raise click.ClickException("No ad accounts: pass --accounts or set META_AD_ACCOUNT_IDS.")
    return ids


def _report(results: list[JobResult]) -> None:
    for r in results:
        click.echo(f"{r.source}: rows={r.rows_loaded} done={r.chunks_done} skipped={r.chunks_skipped} failed={len(r.failures)}")
        for f in r.failures:
            click.echo(f"  FAILED {f}", err=True)
    if any(not r.ok for r in results):
        sys.exit(1)


@click.group()
def cli() -> None:
    setup_logging()


@cli.command()
@click.option("--source", type=click.Choice(SOURCES), required=True)
@click.option("--from", "start", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--to", "end", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--accounts", default=None, help="Comma-separated ad account ids (default: META_AD_ACCOUNT_IDS)")
@click.option("--force", is_flag=True, help="Ignore checkpoints and reload")
def backfill(source: str, start, end, accounts: str | None, force: bool) -> None:  # type: ignore[no-untyped-def]
    days = days_between(start.date(), end.date())
    loader = _loader()
    if source == "mixpanel":
        res = run_mixpanel(loader, days, force=force)
    else:
        res = run_meta_insights(loader, "ad" if source == "meta_ad" else "product", _accounts(accounts), days, force=force)
    _report([res])


@cli.command()
@click.option("--days", default=7, show_default=True, type=click.IntRange(1, 28))
def trailing(days: int) -> None:
    """Re-pull the trailing N days (Meta restates conversions for ~28 days)."""
    yesterday = date.today() - timedelta(days=1)
    window = days_between(yesterday - timedelta(days=days - 1), yesterday)
    loader = _loader()
    accts = _accounts(None)
    _report([
        run_meta_insights(loader, "ad", accts, window, force=True),
        run_meta_insights(loader, "product", accts, window, force=True),
    ])


@cli.command()
def catalog() -> None:
    ids = get_settings().meta.catalog_ids
    if not ids:
        raise click.ClickException("No catalogs: set META_CATALOG_IDS.")
    _report([run_meta_catalog(_loader(), ids, date.today())])


@cli.command()
def objects() -> None:
    _report([run_meta_objects(_loader(), _accounts(None), date.today())])


@cli.command("init-schemas")
@click.option("--i-have-approval", is_flag=True, help="The warehouse owner approved creating these schemas.")
def init_schemas(i_have_approval: bool) -> None:
    _loader().bootstrap_owned_schemas("redshift", approved=i_have_approval)
    click.echo("Created raw_meta / raw_mixpanel / ops tables.")


if __name__ == "__main__":
    cli()
