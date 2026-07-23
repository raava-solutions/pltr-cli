"""Read-only cross-resource search of a Foundry stack."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..auth.base import MissingCredentialsError, ProfileNotFoundError
from ..services.foundry_internal_client import TokenExpiredError
from ..services.search import SearchService
from ..utils.completion import complete_output_format, complete_profile
from .dependency import OutputMode


def search_command(
    text: str = typer.Argument(..., help="Title text to search for"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name",
        autocompletion=complete_profile,
    ),
    limit: int = typer.Option(
        25,
        "--limit",
        "-l",
        help="Maximum number of results (the search query has no page token; "
        "matches beyond the limit are silently truncated by the gateway)",
    ),
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv)",
        autocompletion=complete_output_format,
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file path"
    ),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
) -> None:
    """Search Foundry resources by title via the internal GraphQL gateway."""

    if not text.strip():
        raise typer.BadParameter("must not be empty", param_hint="TEXT")
    if format not in {"table", "json", "csv"}:
        raise typer.BadParameter("must be table, json, or csv", param_hint="--format")
    if limit < 1:
        raise typer.BadParameter("must be >= 1", param_hint="--limit")
    if limit > 500:
        raise typer.BadParameter(
            "must be <= 500 (the gateway cap is ~500; live-verified 2026-07-22 "
            "that 500 is accepted and 999/1000 are rejected)",
            param_hint="--limit",
        )
    try:
        result = SearchService(profile=profile).search(text, limit=limit)
    except TokenExpiredError:
        typer.echo(
            "DEGRADED [token-expired]: Foundry session token expired; "
            "re-authenticate before retrying this search"
        )
        raise typer.Exit(1)
    except (ProfileNotFoundError, MissingCredentialsError) as exc:
        typer.echo(f"Authentication Error: {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)

    if output_mode == OutputMode.CI:
        # Repo CI contract (see commands/dependency.py): exit 0 = clean,
        # 2 = needs verification, 1 = fatal.
        results = result.get("results")
        typer.echo(
            json.dumps(
                {
                    "status": result.get("status"),
                    "query": result.get("query", text),
                    "results": len(results) if isinstance(results, list) else None,
                    "reason": result.get("reason"),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(0 if result.get("status") == "ok" else 2)

    rendered = _render_result(result, format, output_mode)
    if output is not None:
        try:
            output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Error writing output file '{output}': {exc}")
            raise typer.Exit(1)
    else:
        typer.echo(rendered, nl=False)

    if result.get("status") == "inconclusive":
        raise typer.Exit(1)


def _render_result(
    result: Mapping[str, Any], format_type: str, output_mode: OutputMode
) -> str:
    rendered_result = dict(result)
    if result.get("status") == "inconclusive":
        rendered_result["warning"] = _inconclusive_banner(result)
    if format_type == "json":
        return json.dumps(rendered_result, indent=2, sort_keys=True) + "\n"
    if format_type == "csv":
        return _render_csv(rendered_result)
    return _render_table(result, agent_mode=output_mode == OutputMode.AGENT)


def _render_table(result: Mapping[str, Any], *, agent_mode: bool) -> str:
    if result.get("status") == "inconclusive":
        return _inconclusive_banner(result) + "\n"

    results = result.get("results")
    if not isinstance(results, list) or not results:
        prefix = "SEARCH [ok]\n" if agent_mode else ""
        return (
            prefix + f"No results for '{result.get('query')}' "
            "(an empty list here means zero matches, not a read failure)\n"
        )

    prefix = "SEARCH [ok]\n" if agent_mode else ""
    header = [
        prefix + f"Query: {result.get('query')}",
        f"Results: {len(results)} (limit {result.get('limit')})",
        f"Note: {result.get('truncation_note')}",
        "",
    ]
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=200)
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("name")
    table.add_column("type")
    table.add_column("rid")
    table.add_column("path")
    for entry in results:
        if not isinstance(entry, Mapping):
            continue
        table.add_row(
            str(entry.get("name") or ""),
            str(entry.get("type") or ""),
            str(entry.get("rid") or ""),
            str(entry.get("path") or ""),
        )
    console.print(table)
    return "\n".join(header) + "\n" + output.getvalue()


def _inconclusive_banner(result: Mapping[str, Any]) -> str:
    return (
        f"INCONCLUSIVE: {result.get('reason', 'unknown')} — this is NOT proof "
        "there are no matching resources"
    )


def _render_csv(result: Mapping[str, Any]) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "status",
            "query",
            "limit",
            "rid",
            "name",
            "type",
            "path",
            "reason",
            "warning",
        ],
    )
    writer.writeheader()
    results = result.get("results")
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, Mapping):
                continue
            writer.writerow(
                {
                    "status": result.get("status"),
                    "query": result.get("query"),
                    "limit": result.get("limit"),
                    "rid": entry.get("rid"),
                    "name": entry.get("name"),
                    "type": entry.get("type"),
                    "path": entry.get("path"),
                    "reason": result.get("reason"),
                    "warning": result.get("warning"),
                }
            )
    else:
        writer.writerow(
            {
                "status": result.get("status"),
                "query": result.get("query"),
                "limit": result.get("limit"),
                "reason": result.get("reason"),
                "warning": result.get("warning"),
            }
        )
    return output.getvalue()
