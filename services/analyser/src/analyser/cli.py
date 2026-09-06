"""Command-line entrypoint.

The brief allows the analyser to run as a command, a background process, or a
scheduled job. The poller covers the second, and this covers the first and
third: `python -m analyser run-once` is equally usable by hand or from cron.
"""

from __future__ import annotations

from datetime import datetime

import typer

app = typer.Typer(
    name="analyser",
    help="KyberShield risk analyser",
    no_args_is_help=True,
)


@app.command("run-once")
def run_once(
    batch_size: int = typer.Option(None, help="Events per batch; defaults to BATCH_SIZE."),
    drain: bool = typer.Option(False, help="Keep going until the backlog is empty."),
) -> None:
    """Analyse pending events and exit.

    Prints a summary of the run. Exits non-zero if any rule raised, so a cron
    wrapper can alert on a broken detection instead of failing silently.
    """
    raise NotImplementedError


@app.command("backfill")
def backfill(
    since: datetime = typer.Option(None, help="Only re-analyse events at or after this time."),
) -> None:
    """Re-run every rule over historical events.

    Does not move the live cursor, and the alert unique constraint means
    existing findings are skipped, so this is safe to run repeatedly. Use it
    after adding or retuning a rule.
    """
    raise NotImplementedError


@app.command("list-rules")
def list_rules() -> None:
    """Print the registered rules with their effective configuration."""
    raise NotImplementedError


@app.command("show-cursor")
def show_cursor() -> None:
    """Print the current watermark and how many events sit beyond it."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
