"""Unified, explicitly typed proposal lifecycle commands."""

from typing import Any, Callable, Optional

import typer

from ..services.proposal import (
    ProposalAction,
    ProposalService,
    ProposalType,
    ProposalValidationError,
    normalize_proposal_error,
    parse_proposal_type,
)
from ..utils.completion import complete_output_format, complete_profile
from ..utils.formatting import OutputFormatter


app = typer.Typer(help="Manage typed Foundry proposals", no_args_is_help=True)
formatter = OutputFormatter()


def _emit(data: Any, output_format: str) -> None:
    formatter.format_output(data, output_format)


def _fail(error: Exception, output_format: str) -> None:
    proposal_error = normalize_proposal_error(error)
    if output_format == "json":
        _emit(proposal_error.to_payload(), "json")
    else:
        formatter.print_error(f"{proposal_error.category}: {proposal_error}")
    raise typer.Exit(proposal_error.exit_code)


def _run(
    proposal_type: str,
    profile: Optional[str],
    output_format: str,
    operation: Callable[[ProposalService, ProposalType], Any],
) -> None:
    try:
        parsed_type = parse_proposal_type(proposal_type)
        service = ProposalService(profile=profile)
        result = operation(service, parsed_type)
        _emit(result, output_format)
    except Exception as error:
        _fail(error, output_format)


def _profile_option() -> Any:
    return typer.Option(
        None, "--profile", "-p", help="Profile name", autocompletion=complete_profile
    )


def _format_option() -> Any:
    return typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv)",
        autocompletion=complete_output_format,
    )


@app.command("create")
def create_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    parent_rid: str = typer.Option(
        ..., "--parent-rid", help="Repository or ontology RID"
    ),
    title: str = typer.Option(..., "--title", help="Proposal title"),
    source_ref: str = typer.Option(
        ..., "--source-ref", help="Source branch or Global Branch RID"
    ),
    target_ref: Optional[str] = typer.Option(
        None, "--target-ref", help="Target branch for code-pr"
    ),
    description: Optional[str] = typer.Option(
        None, "--description", help="Proposal description"
    ),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Create a proposal when the pinned client exposes the operation."""

    _run(
        proposal_type,
        profile,
        format,
        lambda service, kind: service.create(
            kind,
            parent_rid=parent_rid,
            title=title,
            source_ref=source_ref,
            target_ref=target_ref,
            description=description,
        ),
    )


@app.command("list")
def list_proposals(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    parent_rid: str = typer.Argument(..., help="Repository or ontology RID"),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """List proposals when supported for the selected type."""

    _run(
        proposal_type,
        profile,
        format,
        lambda service, kind: service.list(kind, parent_rid=parent_rid),
    )


@app.command("get")
def get_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(
        None, "--parent-rid", help="Repository or ontology RID"
    ),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Get a proposal."""

    _run(
        proposal_type,
        profile,
        format,
        lambda service, kind: service.get(kind, proposal_id, parent_rid=parent_rid),
    )


@app.command("comment")
def comment_on_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    message: str = typer.Argument(..., help="Comment text"),
    parent_rid: Optional[str] = typer.Option(
        None, "--parent-rid", help="Repository or ontology RID"
    ),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Add a proposal comment when supported."""

    _run(
        proposal_type,
        profile,
        format,
        lambda service, kind: service.comment(
            kind, proposal_id, message, parent_rid=parent_rid
        ),
    )


def _decision_command(
    action: ProposalAction,
    proposal_type: str,
    proposal_id: str,
    parent_rid: Optional[str],
    message: Optional[str],
    profile: Optional[str],
    output_format: str,
) -> None:
    method_name = action.value.replace("-", "_")
    _run(
        proposal_type,
        profile,
        output_format,
        lambda service, kind: getattr(service, method_name)(
            kind, proposal_id, parent_rid=parent_rid, message=message
        ),
    )


@app.command("approve")
def approve_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(None, "--parent-rid"),
    message: Optional[str] = typer.Option(None, "--message"),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Record approval, or return unsupported-capability."""

    _decision_command(
        ProposalAction.APPROVE,
        proposal_type,
        proposal_id,
        parent_rid,
        message,
        profile,
        format,
    )


@app.command("request-changes")
def request_proposal_changes(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(None, "--parent-rid"),
    message: Optional[str] = typer.Option(None, "--message"),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Request changes, or return unsupported-capability."""

    _decision_command(
        ProposalAction.REQUEST_CHANGES,
        proposal_type,
        proposal_id,
        parent_rid,
        message,
        profile,
        format,
    )


def _unsupported_terminal_command(
    action: ProposalAction,
    proposal_type: str,
    proposal_id: str,
    parent_rid: Optional[str],
    profile: Optional[str],
    output_format: str,
) -> None:
    _run(
        proposal_type,
        profile,
        output_format,
        lambda service, kind: getattr(service, action.value)(
            kind, proposal_id, parent_rid=parent_rid
        ),
    )


@app.command("merge")
def merge_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(None, "--parent-rid"),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirmation if this action becomes supported"
    ),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Merge a code PR, or return unsupported-capability."""

    _unsupported_terminal_command(
        ProposalAction.MERGE, proposal_type, proposal_id, parent_rid, profile, format
    )


@app.command("accept")
def accept_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(None, "--parent-rid"),
    yes: bool = typer.Option(
        False, "--yes", help="Skip confirmation if this action becomes supported"
    ),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Accept a Global Proposal, or return unsupported-capability."""

    _unsupported_terminal_command(
        ProposalAction.ACCEPT, proposal_type, proposal_id, parent_rid, profile, format
    )


@app.command("close")
def close_proposal(
    proposal_type: str = typer.Argument(..., help="code-pr or global-proposal"),
    proposal_id: str = typer.Argument(..., help="Proposal identifier"),
    parent_rid: Optional[str] = typer.Option(None, "--parent-rid"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
    profile: Optional[str] = _profile_option(),
    format: str = _format_option(),
) -> None:
    """Refresh and close a proposal after explicit confirmation."""

    try:
        kind = parse_proposal_type(proposal_type)
        if format == "json" and not yes:
            raise ProposalValidationError(
                "--yes is required for close with --format json so output remains JSON-only"
            )

        service = ProposalService(profile=profile)
        service.require_capability(kind, ProposalAction.CLOSE)
        current = service.get(kind, proposal_id, parent_rid=parent_rid)
        if not yes:
            target = current.get("title") or current.get("id") or proposal_id
            if not typer.confirm(f"Close {kind.value} '{target}' ({proposal_id})?"):
                raise ProposalValidationError("Close cancelled")

        result = service.close(kind, proposal_id, parent_rid=parent_rid)
        _emit(result, format)
    except Exception as error:
        _fail(error, format)
