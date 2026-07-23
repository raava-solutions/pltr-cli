"""Read-only Foundry dependency analysis commands."""

from __future__ import annotations

import json
import os
import stat
from enum import Enum
from pathlib import Path
from typing import Any, Callable, NoReturn, Optional

import typer

from ..auth.base import MissingCredentialsError, ProfileNotFoundError
from ..auth.manager import AuthManager
from ..services.dependency import (
    CHANGE_TYPES,
    DependencyFatalError,
    DependencyGraphService,
    DiscoveryBudget,
)
from ..services.dependency_providers import ConjureRestProvider
from ..services.foundry_internal_client import FoundryInternalClient
from ..utils.completion import complete_output_format, complete_profile
from ..utils.dependency_artifacts import (
    ArtifactWriteError,
    artifact_identity,
    default_artifact_path,
    serialize_dependency_result,
    write_dependency_artifact,
)
from ..utils.formatting import OutputFormatter, ProtectedOutputCollisionError


app = typer.Typer(help="Analyze Foundry dependencies without modifying resources")
formatter = OutputFormatter()

DEFAULT_MAX_REQUESTS = 200
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_ITEMS = 10_000
DEFAULT_MAX_NODES = 150
DEFAULT_MAX_DEPTH = 2
DEFAULT_TIME_BUDGET_SECONDS = 60.0
DEFAULT_INTERNAL_PROVIDERS = frozenset({"sdk", "conjure", "graphql"})
SDK_ONLY_PROVIDERS = frozenset({"sdk"})
PROVIDER_NAMES = ("sdk", "conjure", "graphql")
INTERNAL_TRANSPORTS = frozenset({"conjure-rest", "graphql-sse"})

HARD_CEILINGS = {
    "max_requests": 1_000,
    "max_pages": 500,
    "max_items": 100_000,
    "max_nodes": 1_000,
    "max_depth": 10,
    "time_budget_seconds": 600.0,
}

# --compare-artifact is untrusted input read before any Foundry SDK call.
# Bound its size and shape so a malicious/corrupt file cannot cause a large
# memory allocation, a blocking read on a non-regular file (FIFO/device), or
# a full bounded discovery run only to fail deep inside `_diff_graphs`.
MAX_COMPARISON_ARTIFACT_BYTES = 64 * 1024 * 1024  # 64 MiB
MAX_COMPARISON_GRAPH_NODES = int(HARD_CEILINGS["max_nodes"])
MAX_COMPARISON_GRAPH_EDGES = int(HARD_CEILINGS["max_items"])
MAX_COMPARISON_READ_CONTEXTS = 64


class ChangeType(str, Enum):
    RENAME = "rename"
    TYPE_CHANGE = "type-change"
    OPTIONAL_TO_REQUIRED = "optional-to-required"
    REQUIRED_TO_OPTIONAL = "required-to-optional"
    REMOVE_DELETE = "remove-delete"
    ACTION_INPUT_CHANGE = "action-input-change"
    QUERY_OUTPUT_CHANGE = "query-output-change"


class OutputMode(str, Enum):
    AGENT = "agent"
    CI = "ci"
    GRAPH = "graph"


class _ComparisonArtifactError(ValueError):
    """Raised when a comparison artifact cannot be loaded as a JSON object."""

    error_class = "invalid-invocation"
    retryable = False


def _selected_providers(
    providers: Optional[str],
    *,
    no_internal: bool,
    internal_default: bool,
) -> frozenset[str]:
    """Resolve CLI provider selection without weakening the SDK authority path."""
    if no_internal:
        return SDK_ONLY_PROVIDERS
    if providers is None:
        return DEFAULT_INTERNAL_PROVIDERS if internal_default else SDK_ONLY_PROVIDERS
    selected = frozenset(part.strip().lower() for part in providers.split(","))
    unknown = selected.difference(PROVIDER_NAMES)
    if "" in selected or unknown:
        detail = ", ".join(sorted(unknown or {""})) or "empty provider"
        raise typer.BadParameter(
            f"unknown provider selection {detail!r}; choose from: "
            f"{', '.join(PROVIDER_NAMES)}",
            param_hint="--providers",
        )
    if "sdk" not in selected:
        raise typer.BadParameter(
            "must include sdk because target resolution and authoritative "
            "structure use the public SDK",
            param_hint="--providers",
        )
    return selected


def _normalize_internal_degradation(
    result: dict[str, Any], *, internal_enabled: bool
) -> None:
    """Keep internal transport failures fail-closed at the command boundary.

    The shared SDK classifier uses ``partial`` for retryable connection and
    timeout failures. Internal providers cannot make the same claim: no
    internal response means absence was not tested, so their records and gaps
    must render as ``inconclusive``.
    """
    if not internal_enabled:
        return

    for record in result.get("coverage", result.get("coverage_records", ())):
        if (
            isinstance(record, dict)
            and record.get("transport") in INTERNAL_TRANSPORTS
            and record.get("status") == "partial"
        ):
            record["status"] = "inconclusive"
    for gap in result.get("gaps", ()):
        if (
            isinstance(gap, dict)
            and str(gap.get("operation", "")).startswith("ACP-")
            and gap.get("coverage") == "partial"
        ):
            gap["coverage"] = "inconclusive"


def _validate_options(
    *,
    format_type: str,
    direction: str,
    max_requests: int,
    max_pages: int,
    max_items: int,
    max_nodes: int,
    max_depth: int,
    time_budget_seconds: float,
    change_type: Optional[str] = None,
    output_mode: str = "graph",
) -> None:
    if format_type not in {"table", "json", "csv"}:
        raise typer.BadParameter("must be table, json, or csv", param_hint="--format")
    if direction not in {"both", "upstream", "downstream", "adjacent"}:
        raise typer.BadParameter(
            "must be both, upstream, downstream, or adjacent", param_hint="--direction"
        )
    if change_type is not None and change_type not in CHANGE_TYPES:
        raise typer.BadParameter(
            f"must be one of: {', '.join(CHANGE_TYPES)}", param_hint="--change-type"
        )
    if output_mode not in {"agent", "ci", "graph"}:
        raise typer.BadParameter(
            "must be agent, ci, or graph", param_hint="--output-mode"
        )
    values = {
        "max_requests": max_requests,
        "max_pages": max_pages,
        "max_items": max_items,
        "max_nodes": max_nodes,
        "max_depth": max_depth,
        "time_budget_seconds": time_budget_seconds,
    }
    for name, value in values.items():
        option = "--depth" if name == "max_depth" else f"--{name.replace('_', '-')}"
        if value <= 0:
            raise typer.BadParameter("must be greater than zero", param_hint=option)
        if value > HARD_CEILINGS[name]:
            raise typer.BadParameter(
                f"must not exceed the hard ceiling {HARD_CEILINGS[name]:g}",
                param_hint=option,
            )


def _paths_alias(first: Path, second: Path) -> bool:
    """Return whether two user paths name the same filesystem destination."""
    first_path = first.expanduser()
    second_path = second.expanduser()
    if first_path.resolve(strict=False) == second_path.resolve(strict=False):
        return True
    try:
        return os.path.samefile(first_path, second_path)
    except (FileNotFoundError, OSError):
        return False


def _validate_output_paths(output: Optional[Path], graph_output: Path) -> None:
    if output is not None and _paths_alias(output, graph_output):
        raise typer.BadParameter(
            "must identify different files; rendered output cannot replace the graph artifact",
            param_hint="--output/--graph-output",
        )


def _resolve_source_metadata(profile: Optional[str]) -> tuple[str, str]:
    """Resolve the one effective profile and retain only its host for provenance."""
    auth_manager = AuthManager()
    effective_profile = profile or auth_manager.get_current_profile()
    if not effective_profile:
        raise ProfileNotFoundError(
            "No profile specified and no default profile configured. "
            "Run 'pltr configure configure' to set up authentication."
        )
    credentials = auth_manager.storage.get_profile(effective_profile)
    host = credentials.get("host")
    if not host:
        raise MissingCredentialsError(
            f"Host URL not specified in credentials for profile '{effective_profile}'"
        )
    return effective_profile, str(host)


def _fatal_payload(error: BaseException, error_class: str) -> dict[str, Any]:
    if isinstance(error, DependencyFatalError):
        payload = error.to_dict()
        if isinstance(payload, dict):
            return payload
    return {
        "error_class": error_class,
        "message": str(error),
        "retryable": bool(getattr(error, "retryable", False)),
    }


def _render_fatal(error: BaseException, error_class: str, format_type: str) -> None:
    payload = _fatal_payload(error, error_class)
    if format_type == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif format_type == "csv":
        formatter.format_dependency_result({"errors": [payload]}, "csv")
    else:
        typer.echo(
            f"Dependency analysis failed [{payload.get('error_class', error_class)}]: "
            f"{payload.get('message', str(error))}"
        )


def _open_comparison_artifact_bytes(path: Path) -> bytes:
    """Read `path` without following a trailing symlink or blocking on a
    non-regular file (FIFO/device), enforcing the size ceiling before any
    bytes are read into memory."""
    flags = os.O_RDONLY
    for flag_name in ("O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag_name, 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _ComparisonArtifactError(
            f"cannot load comparison artifact {path}: {exc}"
        ) from exc
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise _ComparisonArtifactError(
                f"comparison artifact {path} must be a regular file"
            )
        size = os.fstat(descriptor).st_size
        if size > MAX_COMPARISON_ARTIFACT_BYTES:
            raise _ComparisonArtifactError(
                f"comparison artifact {path} exceeds the "
                f"{MAX_COMPARISON_ARTIFACT_BYTES} byte limit"
            )
        # A regular file ignores O_NONBLOCK for reads, so this cannot block.
        # Read one byte past the ceiling rather than an unbounded read: the
        # file can grow between `fstat` and this read, and a short bounded
        # read still lets us detect and reject that race instead of
        # buffering an arbitrarily large payload into memory.
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(MAX_COMPARISON_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_COMPARISON_ARTIFACT_BYTES:
            raise _ComparisonArtifactError(
                f"comparison artifact {path} exceeds the "
                f"{MAX_COMPARISON_ARTIFACT_BYTES} byte limit"
            )
        return raw
    except OSError as exc:
        raise _ComparisonArtifactError(
            f"cannot load comparison artifact {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_comparison_artifact_shape(path: Path, payload: dict[str, Any]) -> None:
    """Reject a structurally invalid baseline before `_diff_graphs` runs.

    A valid comparison baseline is a writer-shaped artifact: the minimum
    document `write_dependency_artifact` can ever produce. Every field
    checked here is required -- a missing or mistyped field means the file
    cannot safely be diffed against (e.g. `{}` or `{"artifact": {}}`), so it
    is rejected here, before any auth or SDK work happens.
    """

    def fail(message: str) -> NoReturn:
        raise _ComparisonArtifactError(f"comparison artifact {path} {message}")

    def require_object(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            fail(f"must have an object '{label}'")
        return value

    def require_object_array(
        value: Any, label: str, max_len: int, *, allow_empty: bool = True
    ) -> list[Any]:
        if not isinstance(value, list):
            fail(f"must have an array '{label}'")
        if not allow_empty and not value:
            fail(f"must have a non-empty array '{label}'")
        if len(value) > max_len:
            fail(f"'{label}' exceeds the {max_len} entry ceiling")
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                fail(f"'{label}[{index}]' must be an object")
        return value

    def require_string(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            fail(f"must have a non-empty string '{label}'")
        return value

    graph = require_object(payload.get("graph"), "graph")
    require_object_array(graph.get("nodes"), "graph.nodes", MAX_COMPARISON_GRAPH_NODES)
    require_object_array(graph.get("edges"), "graph.edges", MAX_COMPARISON_GRAPH_EDGES)
    require_object(payload.get("target"), "target")
    require_object_array(
        payload.get("read_contexts"),
        "read_contexts",
        MAX_COMPARISON_READ_CONTEXTS,
        allow_empty=False,
    )
    budget = require_object(payload.get("budget"), "budget")
    require_object(budget.get("limits"), "budget.limits")
    artifact = require_object(payload.get("artifact"), "artifact")
    require_string(artifact.get("analysis_id"), "artifact.analysis_id")
    require_string(artifact.get("sha256"), "artifact.sha256")
    artifact_path = artifact.get("path")
    if artifact_path is not None and not isinstance(artifact_path, str):
        fail("must have a string 'artifact.path'")


def _load_comparison_artifact(path: Path) -> dict[str, Any]:
    raw = _open_comparison_artifact_bytes(path)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _ComparisonArtifactError(
            f"cannot load comparison artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise _ComparisonArtifactError(
            f"comparison artifact {path} must contain a JSON object"
        )
    _validate_comparison_artifact_shape(path, payload)
    return payload


def _run(
    resolver: Callable[[DependencyGraphService, Any], Any],
    *,
    ontology_rid: Optional[str],
    profile: Optional[str],
    branch: Optional[str],
    format_type: str,
    output: Optional[Path],
    graph_output: Optional[Path],
    change: Optional[str],
    direction: str,
    depth: int,
    max_nodes: int,
    max_requests: int,
    max_pages: int,
    max_items: int,
    time_budget_seconds: float,
    full: bool,
    change_type: Optional[str | ChangeType] = None,
    output_mode: str | OutputMode = "graph",
    compare_artifact: Optional[Path] = None,
    providers: Optional[str] = None,
    no_internal: bool = False,
    positive_controls: bool = False,
    internal_default: bool = False,
) -> None:
    change_type_value = (
        change_type.value if isinstance(change_type, ChangeType) else change_type
    )
    output_mode_value = (
        output_mode.value if isinstance(output_mode, OutputMode) else output_mode
    )
    _validate_options(
        format_type=format_type,
        direction=direction,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        max_nodes=max_nodes,
        max_depth=depth,
        time_budget_seconds=time_budget_seconds,
        change_type=change_type_value,
        output_mode=output_mode_value,
    )
    selected_providers = _selected_providers(
        providers,
        no_internal=no_internal,
        internal_default=internal_default,
    )
    if graph_output is not None:
        _validate_output_paths(output, graph_output)
    try:
        baseline_artifact = (
            _load_comparison_artifact(compare_artifact)
            if compare_artifact is not None
            else None
        )
        effective_profile, host = _resolve_source_metadata(profile)
        budget = DiscoveryBudget(
            max_requests=max_requests,
            max_pages=max_pages,
            max_items=max_items,
            max_nodes=max_nodes,
            max_depth=depth,
            time_budget_seconds=time_budget_seconds,
        )
        service_kwargs: dict[str, Any] = {"profile": effective_profile}
        internal_client: Optional[FoundryInternalClient] = None
        bootstrap_provider: Optional[ConjureRestProvider] = None
        if selected_providers.intersection({"conjure", "graphql"}):
            internal_client = FoundryInternalClient(effective_profile)
            # U9 supplies the ACP implementations; U8 carries the explicit
            # command gate on the one shared client without enabling controls
            # for ordinary invocations.
            setattr(internal_client, "positive_controls_enabled", positive_controls)
            bootstrap_provider = ConjureRestProvider(internal_client)
            service_kwargs["conjure_provider"] = bootstrap_provider
        service = DependencyGraphService(**service_kwargs)
        if internal_client is not None:
            service._conjure_provider = (
                bootstrap_provider if "conjure" in selected_providers else None
            )
            service._graphql_client = (
                internal_client if "graphql" in selected_providers else None
            )
        context = service.create_context(
            host=host,
            ontology_rid=ontology_rid,
            requested_branch=branch,
            dataset_branch=branch,
            budget=budget,
        )
        target = resolver(service, context)
        raw_result = service.analyze(
            target,
            context,
            direction=direction,
            change=change,
            change_type=change_type_value,
            compare_artifact=baseline_artifact,
        )
        result = serialize_dependency_result(raw_result)
        _normalize_internal_degradation(
            result,
            internal_enabled=bool(
                selected_providers.intersection({"conjure", "graphql"})
            ),
        )
        analysis_id, _ = artifact_identity(result)
        artifact_path = graph_output or default_artifact_path(analysis_id)
        _validate_output_paths(output, artifact_path)
        result["artifact"] = write_dependency_artifact(result, artifact_path)
        agent = result.get("agent")
        if isinstance(agent, dict):
            agent["artifact_reference"] = {
                "artifact_id": result["artifact"]["analysis_id"],
                "path": result["artifact"]["path"],
                "sha256": result["artifact"]["sha256"],
            }
        # Recheck after creation so case-insensitive/filesystem-equivalent leaf
        # names that could not be compared while both destinations were absent
        # are rejected before the renderer opens either path.
        _validate_output_paths(output, artifact_path)
        if output_mode_value == "ci":
            agent = result.get("agent") or {}
            status = agent.get("status", "clean")
            typer.echo(
                json.dumps(
                    {
                        "status": status,
                        "analysis_id": analysis_id,
                        "artifact": result["artifact"]["path"],
                        "must_verify": len(
                            (agent.get("verification") or {}).get(
                                "must_verify_before_merge", []
                            )
                        ),
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(0 if status == "clean" else 2)
        formatter.format_dependency_result(
            result,
            format_type=format_type,
            output_file=str(output) if output else None,
            full=full,
            protected_output_file=str(artifact_path) if output else None,
            output_mode=output_mode_value,
        )
    except typer.BadParameter:
        raise
    except typer.Exit:
        raise
    except _ComparisonArtifactError as exc:
        if output_mode_value == "ci":
            _render_fatal(exc, exc.error_class, "json")
            raise typer.Exit(1)
        raise typer.BadParameter(str(exc), param_hint="--compare-artifact") from exc
    except (ProfileNotFoundError, MissingCredentialsError) as exc:
        _render_fatal(exc, "authentication", format_type)
        raise typer.Exit(1)
    except DependencyFatalError as exc:
        _render_fatal(exc, getattr(exc, "error_class", "unknown"), format_type)
        raise typer.Exit(1)
    except ArtifactWriteError as exc:
        _render_fatal(exc, "artifact-write-failed", format_type)
        raise typer.Exit(1)
    except ProtectedOutputCollisionError as exc:
        raise typer.BadParameter(
            str(exc), param_hint="--output/--graph-output"
        ) from exc
    except Exception as exc:
        _render_fatal(exc, "unknown", format_type)
        raise typer.Exit(1)


@app.command("object-type")
def object_type(
    ontology_rid: str = typer.Argument(..., help="Ontology RID"),
    object_type: str = typer.Argument(..., help="Object type API name"),
    branch: Optional[str] = typer.Option(
        None, "--branch", help="Requested Foundry branch"
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Authentication profile",
        autocompletion=complete_profile,
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Rendered output path"
    ),
    graph_output: Optional[Path] = typer.Option(
        None, "--graph-output", help="Mandatory complete graph artifact path"
    ),
    change: Optional[str] = typer.Option(
        None, "--change", help="Intended change to assess"
    ),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(
        None, "--compare-artifact", help="Prior graph artifact to diff against"
    ),
    direction: str = typer.Option(
        "both", "--direction", help="both, upstream, downstream, or adjacent"
    ),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full", help="Expand table rendering only"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze an ontology object type."""
    _run(
        lambda service, context: service.resolve_object_type(
            context, ontology_rid, object_type
        ),
        ontology_rid=ontology_rid,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
        internal_default=True,
    )


@app.command("property")
def property_command(
    ontology_rid: str = typer.Argument(..., help="Ontology RID"),
    object_type: str = typer.Argument(..., help="Object type API name"),
    property: str = typer.Argument(..., help="Property API name"),
    branch: Optional[str] = typer.Option(None, "--branch"),
    profile: Optional[str] = typer.Option(
        None, "--profile", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    graph_output: Optional[Path] = typer.Option(None, "--graph-output"),
    change: Optional[str] = typer.Option(None, "--change"),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(None, "--compare-artifact"),
    direction: str = typer.Option("both", "--direction"),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze one property on an ontology object type."""
    _run(
        lambda service, context: service.resolve_property(
            context, ontology_rid, object_type, property
        ),
        ontology_rid=ontology_rid,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
        internal_default=True,
    )


@app.command("link-type")
def link_type(
    ontology_rid: str = typer.Argument(...),
    object_type: str = typer.Argument(...),
    link_type: str = typer.Argument(...),
    branch: Optional[str] = typer.Option(None, "--branch"),
    profile: Optional[str] = typer.Option(
        None, "--profile", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    graph_output: Optional[Path] = typer.Option(None, "--graph-output"),
    change: Optional[str] = typer.Option(None, "--change"),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(None, "--compare-artifact"),
    direction: str = typer.Option("both", "--direction"),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze an ontology link type."""
    _run(
        lambda service, context: service.resolve_link_type(
            context, ontology_rid, object_type, link_type
        ),
        ontology_rid=ontology_rid,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
    )


@app.command("action-type")
def action_type(
    ontology_rid: str = typer.Argument(...),
    action_type: str = typer.Argument(...),
    branch: Optional[str] = typer.Option(None, "--branch"),
    profile: Optional[str] = typer.Option(
        None, "--profile", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    graph_output: Optional[Path] = typer.Option(None, "--graph-output"),
    change: Optional[str] = typer.Option(None, "--change"),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(None, "--compare-artifact"),
    direction: str = typer.Option("both", "--direction"),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze an ontology action type using full metadata."""
    _run(
        lambda service, context: service.resolve_action_type(
            context, ontology_rid, action_type
        ),
        ontology_rid=ontology_rid,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
    )


@app.command("query-type")
def query_type(
    ontology_rid: str = typer.Argument(...),
    query_type: str = typer.Argument(...),
    branch: Optional[str] = typer.Option(None, "--branch"),
    profile: Optional[str] = typer.Option(
        None, "--profile", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    graph_output: Optional[Path] = typer.Option(None, "--graph-output"),
    change: Optional[str] = typer.Option(None, "--change"),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(None, "--compare-artifact"),
    direction: str = typer.Option("both", "--direction"),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze an ontology query type."""
    _run(
        lambda service, context: service.resolve_query_type(
            context, ontology_rid, query_type
        ),
        ontology_rid=ontology_rid,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
    )


@app.command("resource")
def resource(
    resource_rid: str = typer.Argument(..., help="Compass-resolvable resource RID"),
    branch: Optional[str] = typer.Option(None, "--branch"),
    profile: Optional[str] = typer.Option(
        None, "--profile", autocompletion=complete_profile
    ),
    format: str = typer.Option(
        "table", "--format", "-f", autocompletion=complete_output_format
    ),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    graph_output: Optional[Path] = typer.Option(None, "--graph-output"),
    change: Optional[str] = typer.Option(None, "--change"),
    change_type: Optional[ChangeType] = typer.Option(None, "--change-type"),
    output_mode: OutputMode = typer.Option(OutputMode.GRAPH, "--output-mode"),
    compare_artifact: Optional[Path] = typer.Option(None, "--compare-artifact"),
    direction: str = typer.Option("both", "--direction"),
    depth: int = typer.Option(DEFAULT_MAX_DEPTH, "--depth"),
    max_nodes: int = typer.Option(DEFAULT_MAX_NODES, "--max-nodes"),
    max_requests: int = typer.Option(DEFAULT_MAX_REQUESTS, "--max-requests"),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, "--max-pages"),
    max_items: int = typer.Option(DEFAULT_MAX_ITEMS, "--max-items"),
    time_budget_seconds: float = typer.Option(
        DEFAULT_TIME_BUDGET_SECONDS, "--time-budget-seconds"
    ),
    full: bool = typer.Option(False, "--full"),
    no_internal: bool = typer.Option(
        False, "--no-internal", help="Use SDK-only dependency discovery"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help="Comma-separated subset: sdk,conjure,graphql",
    ),
    positive_controls: bool = typer.Option(
        False,
        "--positive-controls",
        help="Enable config-gated internal ACP canaries",
    ),
) -> None:
    """Analyze a Compass RID, specializing datasets and applications when resolved."""
    if not resource_rid.startswith("ri."):
        raise typer.BadParameter(
            "resource must be a Compass-resolvable RID, not a Workshop name or variable",
            param_hint="RESOURCE_RID",
        )
    _run(
        lambda service, context: service.resolve_resource(context, resource_rid),
        ontology_rid=None,
        profile=profile,
        branch=branch,
        format_type=format,
        output=output,
        graph_output=graph_output,
        change=change,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        max_requests=max_requests,
        max_pages=max_pages,
        max_items=max_items,
        time_budget_seconds=time_budget_seconds,
        full=full,
        change_type=change_type,
        output_mode=output_mode,
        compare_artifact=compare_artifact,
        providers=providers,
        no_internal=no_internal,
        positive_controls=positive_controls,
        internal_default=True,
    )
