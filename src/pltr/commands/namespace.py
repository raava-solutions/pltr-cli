"""Native Compass namespace discovery commands."""

from typing import Optional

import typer

from ..auth.base import MissingCredentialsError, ProfileNotFoundError
from ..services.compass import CompassService
from ..utils.agent_output import agent_mode_enabled, render_agent_json
from ..utils.completion import complete_output_format, complete_profile
from ..utils.formatting import OutputFormatter

app = typer.Typer()
formatter = OutputFormatter()


def _emit_result(
    data: list[dict[str, object]],
    pagination: dict[str, object],
    format: str,
    output: Optional[str],
) -> None:
    if agent_mode_enabled() or format == "agent":
        rendered = render_agent_json(
            data,
            meta={"operation": "list_foundry_namespaces"},
            pagination=pagination,
        )
        if output:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
        return

    if format == "json":
        formatter.format_dict({"data": data, "pagination": pagination}, format, output)
    else:
        formatter.format_list(data, format, output)


@app.command("list")
def list_namespaces(
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Profile name", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv, agent)",
        autocompletion=complete_output_format,
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    page_size: Optional[int] = typer.Option(None, "--page-size", min=1),
    page_token: Optional[str] = typer.Option(None, "--page-token"),
):
    """List top-level Compass Spaces as namespace discovery records."""
    try:
        result = CompassService(profile=profile).list_namespaces(
            page_size=page_size, page_token=page_token
        )
        _emit_result(result.data, result.metadata.to_dict(), format, output)
    except (ProfileNotFoundError, MissingCredentialsError) as e:
        formatter.print_error(f"Authentication error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        formatter.print_error(f"Failed to list namespaces: {e}")
        raise typer.Exit(1) from e
