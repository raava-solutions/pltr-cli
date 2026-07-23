"""
Main CLI entry point for pltr.
"""

import typer
from typing_extensions import Annotated

from pltr import __version__
from pltr.utils.agent_output import configure_agent_settings
from pltr.commands import (
    configure,
    verify,
    dataset,
    folder,
    project,
    namespace,
    lineage,
    resource,
    resource_role,
    space,
    ontology,
    orchestration,
    sql,
    admin,
    shell,
    completion,
    alias,
    mediasets,
    connectivity,
    third_party_applications,
    aip_agents,
    functions,
    streams,
    language_models,
    models,
    data_health,
    audit,
    widgets,
    proposal,
    dependency,
    capabilities,
    notepad,
)
from pltr.commands.cp import cp_command
from pltr.commands.search import search_command

app = typer.Typer(
    name="pltr",
    help="Command-line interface for Palantir Foundry APIs",
    no_args_is_help=True,
)

# Add subcommands
app.add_typer(configure.app, name="configure", help="Manage authentication profiles")
app.add_typer(verify.app, name="verify", help="Verify authentication")
app.add_typer(dataset.app, name="dataset", help="Manage datasets")
app.add_typer(folder.app, name="folder", help="Manage folders")
app.add_typer(project.app, name="project", help="Manage projects")
app.add_typer(namespace.app, name="namespace", help="Discover Compass namespaces")
app.add_typer(lineage.app, name="lineage", help="Inspect bounded resource graphs")
app.add_typer(resource.app, name="resource", help="Manage resources")
app.add_typer(
    resource_role.app, name="resource-role", help="Manage resource permissions"
)
app.add_typer(space.app, name="space", help="Manage spaces")
app.add_typer(ontology.app, name="ontology", help="Ontology operations")
app.add_typer(
    orchestration.app, name="orchestration", help="Manage builds, jobs, and schedules"
)
app.add_typer(sql.app, name="sql", help="Execute SQL queries")
app.add_typer(
    mediasets.app, name="media-sets", help="Manage media sets and media content"
)
app.add_typer(
    connectivity.app, name="connectivity", help="Manage connections and data imports"
)
app.add_typer(
    third_party_applications.app,
    name="third-party-apps",
    help="Manage third-party applications",
)
app.add_typer(
    aip_agents.app,
    name="aip-agents",
    help="Manage AIP Agents, sessions, and versions",
)
app.add_typer(
    functions.app,
    name="functions",
    help="Manage Functions queries and value types",
)
app.add_typer(
    streams.app,
    name="streams",
    help="Manage streaming datasets and streams",
)
app.add_typer(
    language_models.app,
    name="language-models",
    help="Interact with language models (Claude, OpenAI embeddings)",
)
app.add_typer(
    models.app,
    name="models",
    help="Manage ML models and versions",
)
app.add_typer(
    data_health.app,
    name="data-health",
    help="Manage data health checks and reports",
)
app.add_typer(
    audit.app,
    name="audit",
    help="Audit log operations for compliance and security monitoring",
)
app.add_typer(
    widgets.app,
    name="widgets",
    help="Manage widget sets, releases, and repositories",
)
app.add_typer(
    proposal.app,
    name="proposal",
    help="Manage code pull requests and Ontology Global Proposals",
)
app.add_typer(
    admin.app,
    name="admin",
    help="Admin operations for user, group, and organization management",
)
app.add_typer(
    dependency.app,
    name="dependency",
    help="Analyze Foundry dependency graphs and coverage",
)
app.add_typer(
    capabilities.app,
    name="capabilities",
    help="Inspect native agent-first Foundry capabilities",
)
app.add_typer(notepad.app, name="notepad", help="Read Foundry notepad contents")
app.command("search", help="Search Foundry resources by title (read-only)")(
    search_command
)
app.add_typer(shell.shell_app, name="shell", help="Interactive shell mode")
app.add_typer(completion.app, name="completion", help="Manage shell completions")
app.add_typer(alias.app, name="alias", help="Manage command aliases")
app.command("cp", help="Copy datasets or folders into another Compass folder")(
    cp_command
)


def version_callback(value: bool):
    """Show version and exit."""
    if value:
        typer.echo(f"pltr {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=version_callback, help="Show version")
    ] = False,
    agent: bool = typer.Option(
        False,
        "--agent",
        help="Use the stable machine-readable agent output contract",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable prompts and require explicit mutation confirmation flags",
    ),
):
    """
    Command-line interface for Palantir Foundry APIs.

    Built on top of the official foundry-platform-sdk, pltr provides
    intuitive commands for dataset management, ontology operations,
    SQL queries, and more.
    """
    configure_agent_settings(enabled=agent, non_interactive=non_interactive)


@app.command()
def hello():
    """Test command to verify CLI is working."""
    typer.echo("Hello from pltr! 🚀")
    typer.echo("CLI is working correctly.")


if __name__ == "__main__":
    app()
