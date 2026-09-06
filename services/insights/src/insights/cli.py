"""Command-line mirror of the insights API.

The brief allows an API or a CLI; both are here because they cost little once
the repository exists, and a CLI makes the demo far easier to narrate than
curl. Every command talks to the database directly rather than to the HTTP
service, so it works even when the API container is down.
"""

from __future__ import annotations

from datetime import datetime

import typer

app = typer.Typer(
    name="insights",
    help="KyberShield risk insights",
    no_args_is_help=True,
)


@app.command("alerts")
def alerts(
    agent_id: str = typer.Option(None, help="Filter to one agent."),
    rule: str = typer.Option(None, help="Filter to one rule id."),
    severity_min: str = typer.Option(None, help="Minimum severity: low|medium|high|critical."),
    window: str = typer.Option("24h", help="Lookback window, e.g. 30m, 24h, 7d."),
    limit: int = typer.Option(50, help="Maximum rows."),
    offset: int = typer.Option(0, help="Rows to skip."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List recent alerts.

    Renders a rich table by default; `--json` emits the same shape the HTTP
    endpoint returns, so it pipes into `jq` and matches the API contract.
    """
    raise NotImplementedError


@app.command("summary")
def summary(
    agent_id: str = typer.Argument(..., help="Agent to summarise."),
    window: str = typer.Option("24h", help="Window, e.g. 30m, 24h, 7d."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Show one agent's risk posture: totals, peak severity, and top rules."""
    raise NotImplementedError


@app.command("timeline")
def timeline(
    agent_id: str = typer.Argument(..., help="Agent to inspect."),
    window: str = typer.Option("24h", help="Window, e.g. 30m, 24h, 7d."),
    limit: int = typer.Option(100, help="Maximum entries."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Show one agent's events and alerts interleaved in time.

    Alerts are visually distinguished by severity in table mode, so the moment
    activity turned risky is obvious at a glance.
    """
    raise NotImplementedError


@app.command("agents")
def agents(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List known agents with their first and last seen times."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
