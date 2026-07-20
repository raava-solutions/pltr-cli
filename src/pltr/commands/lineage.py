"""Native bounded Compass resource graph commands."""

from typing import Optional

import typer

from ..auth.base import MissingCredentialsError, ProfileNotFoundError
from ..services.lineage import LineageService
from ..utils.agent_output import agent_mode_enabled, render_agent_json
from ..utils.completion import complete_output_format, complete_profile, complete_rid
from ..utils.formatting import OutputFormatter

app = typer.Typer()
formatter = OutputFormatter()


@app.command("graph")
def get_resource_graph(
    resource_rid: str = typer.Argument(
        ...,
        help="Resource RID at which graph traversal starts",
        autocompletion=complete_rid,
    ),
    direction: str = typer.Option(
        "both", "--direction", help="Traversal direction: upstream, downstream, or both"
    ),
    max_depth: int = typer.Option(2, "--max-depth", min=0),
    max_nodes: int = typer.Option(100, "--max-nodes", min=1),
    max_edges: int = typer.Option(200, "--max-edges", min=1),
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
    """Build a bounded graph from native filesystem relationships."""
    try:
        graph = LineageService(profile=profile).get_resource_graph(
            resource_rid,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            page_size=page_size,
            page_token=page_token,
        )
        if agent_mode_enabled() or format == "agent":
            payload = dict(graph)
            pagination = payload.pop("pagination", None)
            rendered = render_agent_json(
                payload,
                meta={"operation": "get_resource_graph"},
                warnings=graph.get("coverage", {}).get("gaps", []),
                pagination=pagination,
            )
            if output:
                with open(output, "w", encoding="utf-8") as handle:
                    handle.write(rendered)
            else:
                print(rendered, end="")
        elif format == "json":
            formatter.format_dict(graph, format, output)
        elif format == "csv":
            formatter.format_list(graph.get("edges", []), format, output)
        else:
            formatter.format_list(graph.get("edges", []), format, output)
    except (ProfileNotFoundError, MissingCredentialsError) as e:
        formatter.print_error(f"Authentication error: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        formatter.print_error(f"Failed to get resource graph: {e}")
        raise typer.Exit(1) from e
