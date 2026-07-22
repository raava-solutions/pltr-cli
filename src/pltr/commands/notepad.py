"""Read-only commands for Foundry notepads."""

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
from ..services.notepad import NotepadService
from ..utils.completion import complete_output_format, complete_profile, complete_rid
from .dependency import OutputMode


app = typer.Typer(help="Read Foundry notepad contents without modifying them")


@app.command("get")
def get_notepad(
    notepad_rid: str = typer.Argument(
        ..., help="Foundry notepad RID", autocompletion=complete_rid
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name",
        autocompletion=complete_profile,
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
    """Read a notepad's latest body and embedded resource references."""

    if format not in {"table", "json", "csv"}:
        raise typer.BadParameter("must be table, json, or csv", param_hint="--format")
    try:
        result = NotepadService(profile=profile).get(notepad_rid)
    except TokenExpiredError:
        typer.echo(
            "DEGRADED [token-expired]: Foundry session token expired; "
            "re-authenticate before retrying this notepad read"
        )
        raise typer.Exit(1)
    except (ProfileNotFoundError, MissingCredentialsError) as exc:
        typer.echo(f"Authentication Error: {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)

    rendered = _render_result(result, format, output_mode)
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
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
    status = result.get("status")
    if status == "inconclusive":
        return _inconclusive_banner(result) + "\n"
    if status == "empty-document":
        return (
            f"Notepad: {result.get('name') or result.get('rid') or 'unknown'}\n"
            f"Version: {result.get('version') or 'unknown'}\n"
            "EMPTY DOCUMENT: the notepad has a valid empty body and no references\n"
        )

    prefix = "NOTEPAD READ [readable]\n" if agent_mode else ""
    lines = [
        prefix + f"Notepad: {result.get('name') or result.get('rid') or 'unknown'}",
        f"Version: {result.get('version') or 'unknown'}",
        "Body:",
        str(result.get("body_text") or ""),
        "References:",
    ]
    references = result.get("references")
    if not isinstance(references, list) or not references:
        lines.append("none")
        return "\n".join(lines) + "\n"

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("kind")
    table.add_column("section_type_id")
    table.add_column("identifier")
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        config = reference.get("config")
        table.add_row(
            str(reference.get("kind") or ""),
            str(reference.get("section_type_id") or ""),
            _reference_identifier(config if isinstance(config, Mapping) else {}),
        )
    console.print(table)
    return "\n".join(lines) + "\n" + output.getvalue()


def _reference_identifier(config: Mapping[str, Any]) -> str:
    identifying_keys = ("rid", "id", "snapshotRid", "name")
    values = [
        f"{key}={config[key]}"
        for key in identifying_keys
        if config.get(key) is not None
    ]
    return ", ".join(values) or "unknown"


def _inconclusive_banner(result: Mapping[str, Any]) -> str:
    return (
        f"INCONCLUSIVE: {result.get('reason', 'unknown')} — this is NOT proof "
        "the notepad is empty"
    )


def _render_csv(result: Mapping[str, Any]) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_kind",
            "status",
            "name",
            "version",
            "kind",
            "section_type_id",
            "identifier",
            "body_text",
            "reason",
            "warning",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_kind": "notepad",
            "status": result.get("status"),
            "name": result.get("name"),
            "version": result.get("version"),
            "body_text": result.get("body_text"),
            "reason": result.get("reason"),
            "warning": result.get("warning"),
        }
    )
    references = result.get("references")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            config = reference.get("config")
            writer.writerow(
                {
                    "row_kind": "reference",
                    "status": result.get("status"),
                    "name": result.get("name"),
                    "version": result.get("version"),
                    "kind": reference.get("kind"),
                    "section_type_id": reference.get("section_type_id"),
                    "identifier": _reference_identifier(
                        config if isinstance(config, Mapping) else {}
                    ),
                }
            )
    return output.getvalue()
