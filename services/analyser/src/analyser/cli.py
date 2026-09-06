"""Command-line entrypoint.

The brief allows the analyser to run as a command, a background process, or a
scheduled job. The poller covers the second, and this covers the first and
third: `python -m analyser run-once` is equally usable by hand or from cron.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import typer
from pycommon import Database, configure_logging

from analyser.config import get_config, rule_config
from analyser.engine import AnalysisEngine, RunReport
from analyser.repository import PgAnalysisRepository
from analyser.rules import default_rules

app = typer.Typer(
    name="analyser",
    help="KyberShield risk analyser",
    no_args_is_help=True,
)


@contextmanager
def _engine() -> Iterator[AnalysisEngine]:
    """Build an engine over a short-lived pool, closed on exit.

    Every command needs the same four objects; a CLI invocation is a single
    pass, so the pool is opened and drained around it rather than kept warm.
    """
    config = get_config()
    configure_logging(config.log_level)
    db = Database(
        config.psycopg_conninfo,
        min_size=1,
        max_size=config.db_pool_max_size,
        application_name="kybershield-analyser-cli",
    )
    db.open()
    try:
        yield AnalysisEngine(
            default_rules(),
            PgAnalysisRepository(db),
            config,
            batch_size=config.batch_size,
        )
    finally:
        db.close()


def _print_report(report: RunReport) -> None:
    """Print a run report as one JSON object.

    JSON rather than the dataclass repr so `run-once` output pipes into `jq`
    from a cron wrapper.
    """
    print(json.dumps(dataclasses.asdict(report), indent=2, default=str))


@app.command("run-once")
def run_once(
    batch_size: int | None = typer.Option(None, help="Events per batch; defaults to BATCH_SIZE."),
    drain: bool = typer.Option(False, help="Keep going until the backlog is empty."),
) -> None:
    """Analyse pending events and exit.

    Prints a summary of the run. Exits non-zero if any rule raised, so a cron
    wrapper can alert on a broken detection instead of failing silently.
    """
    with _engine() as engine:
        report = engine.run_until_caught_up() if drain else engine.run_once(batch_size)
    _print_report(report)
    if report.rule_failures:
        raise typer.Exit(1)


@app.command("backfill")
def backfill(
    since: datetime | None = typer.Option(
        None, help="Only re-analyse events at or after this time."
    ),
) -> None:
    """Re-run every rule over historical events.

    Does not move the live cursor, and the alert unique constraint means
    existing findings are skipped, so this is safe to run repeatedly. Use it
    after adding or retuning a rule.
    """
    with _engine() as engine:
        report = engine.backfill(since)
    _print_report(report)


@app.command("list-rules")
def list_rules() -> None:
    """Print the registered rules with their effective configuration."""
    config = get_config()
    with _engine() as engine:
        rules = [
            {
                "id": rule.id,
                "description": rule.description,
                "config": rule_config(rule.id, config),
            }
            for rule in engine.rules
        ]
    print(json.dumps(rules, indent=2))


@app.command("show-cursor")
def show_cursor() -> None:
    """Print the analysis watermark, the highest `ingest_seq` already handled."""
    with _engine() as engine:
        print(engine.repo.get_cursor())


if __name__ == "__main__":
    app()
