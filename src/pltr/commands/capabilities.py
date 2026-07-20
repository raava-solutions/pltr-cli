"""Inspect the native agent-first Foundry CLI capability manifest."""

import json
from pathlib import Path
from typing import Any, Mapping, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..capabilities import ManifestValidationError, capability_manifest
from ..utils.agent_output import render_agent_json

app = typer.Typer(help="Inspect native Foundry CLI capabilities")
console = Console()


def _render_table(manifest: Mapping[str, Any]) -> str:
    """Render a compact human-readable capability summary."""
    table = Table(title="Native Foundry CLI Capabilities")
    table.add_column("Group", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Planned", justify="right")
    table.add_column("Implemented", justify="right")
    table.add_column("Blocked", justify="right")
    table.add_column("Unsupported", justify="right")

    capabilities = manifest["capabilities"]
    groups: dict[str, dict[str, int]] = {}
    for capability in capabilities:
        group = groups.setdefault(
            capability["group"],
            {
                "total": 0,
                "planned": 0,
                "implemented": 0,
                "blocked": 0,
                "unsupported": 0,
            },
        )
        group["total"] += 1
        group[capability["status"]] += 1

    for group_name in sorted(groups):
        values = groups[group_name]
        table.add_row(
            group_name,
            str(values["total"]),
            str(values["planned"]),
            str(values["implemented"]),
            str(values["blocked"]),
            str(values["unsupported"]),
        )

    from io import StringIO

    output = StringIO()
    capture = Console(file=output, force_terminal=False, color_system=None)
    capture.print(table)
    capture.print(
        f"Catalog: {manifest['catalog']['version']} | "
        f"Tools: {manifest['catalog']['tool_count']} | "
        f"Workflows: {manifest['catalog']['workflow_count']}"
    )
    return output.getvalue()


def _render(manifest: Mapping[str, Any], format_type: str) -> str:
    if format_type == "agent":
        return render_agent_json(manifest, meta={"result_type": "capability_manifest"})
    if format_type == "json":
        return json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if format_type == "table":
        return _render_table(manifest)
    raise ValueError("Unsupported format. Choose: agent, json, or table")


@app.callback(invoke_without_command=True)
def capabilities(
    ctx: typer.Context,
    format: str = typer.Option(
        "agent",
        "--format",
        "-f",
        help="Output format: agent, json, or table",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the manifest to a file",
    ),
) -> None:
    """Show the native agent-first Foundry CLI capability manifest."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        manifest = capability_manifest()
        rendered = _render(manifest, format)
    except ManifestValidationError as error:
        console.print_json(
            json.dumps(
                {
                    "error": {
                        "type": "capability-manifest-invalid",
                        "messages": list(error.errors),
                    }
                }
            )
        )
        raise typer.Exit(1)
    except ValueError as error:
        console.print(f"[red]Error:[/red] {error}")
        raise typer.Exit(2)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    elif format in {"agent", "json"}:
        typer.echo(rendered, nl=False)
    else:
        typer.echo(rendered, nl=False)
