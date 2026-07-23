import copy
import csv
import hashlib
import json
import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from click.utils import strip_ansi
import pytest
import requests
from typer.testing import CliRunner

from pltr.cli import app
from pltr.commands import dependency as dependency_command
from pltr.services.dependency import (
    DependencyFatalError,
    DependencyGraphService as RealDependencyGraphService,
)
from pltr.utils.dependency_artifacts import (
    ArtifactWriteError,
    artifact_identity,
    default_artifact_path,
    write_dependency_artifact,
)
from pltr.utils.formatting import ProtectedOutputCollisionError


runner = CliRunner()


def _internal_edge_sdk_client() -> SimpleNamespace:
    metadata = SimpleNamespace(
        object_type=SimpleNamespace(properties={"email": SimpleNamespace()}),
        link_types=[],
        implements_interfaces=[],
        implements_interfaces2={},
        shared_property_type_mapping={},
    )
    empty_page = SimpleNamespace(data=[], next_page_token=None)
    return SimpleNamespace(
        ontologies=SimpleNamespace(
            Ontology=SimpleNamespace(
                ObjectType=SimpleNamespace(
                    get_full_metadata=Mock(return_value=metadata)
                ),
                QueryType=SimpleNamespace(list=Mock(return_value=empty_page)),
            ),
            ActionTypeFullMetadata=SimpleNamespace(list=Mock(return_value=empty_page)),
        )
    )


def independent_payload_digest(document):
    payload = {key: value for key, value in document.items() if key != "artifact"}
    agent = payload.get("agent")
    if isinstance(agent, dict):
        payload["agent"] = {
            key: value for key, value in agent.items() if key != "artifact_reference"
        }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def analysis_result():
    return {
        "target": {
            "id": "object:Employee",
            "kind": "object-type",
            "display_name": "Employee",
        },
        "read_contexts": [
            {
                "id": "ctx",
                "profile": "qa",
                "host_fingerprint": "f9137f6af01050c3",
                "requested_branch": "dev",
            }
        ],
        "graph": {
            "nodes": [{"id": "object:Employee", "kind": "object-type"}],
            "edges": [
                {"id": "edge-1", "source": "query:q", "target": "object:Employee"}
            ],
        },
        "paths": [
            {
                "id": "path-1",
                "direction": "upstream",
                "readable_path": "Employee <- Query q",
                "evidence_locator": "output",
                "sdk_namespace": "client.ontologies.Ontology.QueryType",
                "sdk_method": "list",
            }
        ],
        "coverage_records": [{"surface": "query-metadata", "status": "covered"}],
        "gaps": [
            {
                "surface": "schedule-reverse-index",
                "coverage": "partial",
                "reason_code": "schedule-index-may-be-stale",
                "message": "Schedule index may be stale for up to one hour.",
            }
        ],
        "errors": [
            {
                "id": "error-1",
                "error_class": "timeout",
                "message": "One optional reverse lookup timed out.",
            }
        ],
        "evidence": [
            {"id": "ev-1", "operation_provenance_id": "op-1", "locator": "output"}
        ],
        "operation_provenance": [
            {
                "id": "op-1",
                "sdk_namespace": "client.ontologies.Ontology.QueryType",
                "sdk_method": "list",
                "capability_ids": ["CAP-05", "CAP-16"],
                "invocation_sdk_version": "1.95.0",
                "branch_argument": {"mode": "explicit", "value": "dev"},
                "preview_argument": {"mode": "not-applicable", "value": None},
            },
            {
                "id": "op-2",
                "sdk_namespace": "client.filesystem.Resource",
                "sdk_method": "get",
                "capability_ids": ["CAP-16"],
                "invocation_sdk_version": "1.95.0",
                "branch_argument": {"mode": "not-applicable", "value": None},
                "preview_argument": {"mode": "not-applicable", "value": None},
            },
        ],
        "budget": {"used": {"requests": 2}, "limits": {"requests": 200}},
        "summary": {"assessment": "Partial dependency coverage."},
        "agent": {
            "schema_version": "dependency-agent-v1",
            "status": "clean",
            "summary": "One observed relationship; no merge-blocking verification.",
            "change": {
                "text": None,
                "change_type": None,
                "change_type_source": "absent",
            },
            "blast_radius": {
                "score": 3,
                "weight_table_version": "blast-radius-weights-v1",
                "budget_fingerprint": "budget-1",
                "groups": {
                    "critical_paths": [],
                    "structural_dependents": [],
                    "indirect_operational_effects": ["impact-1"],
                    "unknown_manual_verification": [],
                },
            },
            "release_risk": {
                "score": None,
                "weight_table_version": "release-risk-weights-v1",
                "budget_fingerprint": "budget-1",
                "change_type_source": "absent",
            },
            "verification": {
                "must_verify_before_merge": [],
                "should_verify_before_deploy": [
                    {
                        "subject_node_id": "query:q",
                        "subject_display_name": "Query q",
                        "related_impact_ids": ["impact-1"],
                        "reason": "impact",
                        "message": "Verify the query relationship.",
                    }
                ],
                "unsupported_manual_surfaces": [],
            },
            "coverage_completeness": {
                "complete": True,
                "budget_exhausted": False,
                "exhausted_dimensions": [],
                "truncated_surfaces": [],
            },
            "action_query_contracts": {"actions": [], "queries": []},
            "diff": None,
        },
    }


def _valid_comparison_baseline() -> dict:
    """Minimal writer-shaped baseline: the smallest document
    `write_dependency_artifact` can ever produce."""
    return {
        "graph": {
            "nodes": [{"id": "node-a", "kind": "object-type"}],
            "edges": [{"id": "edge-a", "source": "node-a", "target": "node-b"}],
        },
        "target": {
            "kind": "object-type",
            "identifiers": {"object_type": "Employee"},
            "display_name": "Employee",
            "node_id": "node-a",
        },
        "read_contexts": [
            {"id": "ctx", "profile": "qa", "host_fingerprint": "f9137f6af01050c3"}
        ],
        "budget": {"used": {"requests": 1}, "limits": {"requests": 200}},
        "artifact": {
            "analysis_id": "dep-baseline",
            "sha256": "a" * 64,
            "path": "/tmp/dep-baseline.json",
        },
    }


def _drop(payload: dict, *path: str) -> dict:
    mutated = copy.deepcopy(payload)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return mutated


def _set(payload: dict, value, *path: str) -> dict:
    mutated = copy.deepcopy(payload)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return mutated


@pytest.fixture
def service():
    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch("pltr.commands.dependency.DependencyGraphService") as constructor,
    ):
        auth_manager = auth_constructor.return_value
        auth_manager.get_current_profile.return_value = "active"
        auth_manager.storage.get_profile.side_effect = lambda profile: {
            "host": f"https://{profile}.example.com",
            "token": "must-not-enter-provenance",
        }
        instance = constructor.return_value
        context = object()
        target = object()
        instance.create_context.return_value = context
        for method_name in (
            "resolve_object_type",
            "resolve_property",
            "resolve_link_type",
            "resolve_action_type",
            "resolve_query_type",
            "resolve_resource",
        ):
            getattr(instance, method_name).return_value = target
        instance.analyze.return_value = analysis_result()
        yield constructor, instance, context, target


@pytest.mark.parametrize(
    ("arguments", "resolver", "resolver_arguments", "ontology_rid", "internal"),
    [
        (
            ["object-type", "ri.ontology", "Employee"],
            "resolve_object_type",
            ("ri.ontology", "Employee"),
            "ri.ontology",
            True,
        ),
        (
            ["property", "ri.ontology", "Employee", "email"],
            "resolve_property",
            ("ri.ontology", "Employee", "email"),
            "ri.ontology",
            True,
        ),
        (
            ["link-type", "ri.ontology", "Employee", "manager"],
            "resolve_link_type",
            ("ri.ontology", "Employee", "manager"),
            "ri.ontology",
            False,
        ),
        (
            ["action-type", "ri.ontology", "promote"],
            "resolve_action_type",
            ("ri.ontology", "promote"),
            "ri.ontology",
            False,
        ),
        (
            ["query-type", "ri.ontology", "findEmployee"],
            "resolve_query_type",
            ("ri.ontology", "findEmployee"),
            "ri.ontology",
            False,
        ),
        (
            ["resource", "ri.foundry.main.dataset.abc"],
            "resolve_resource",
            ("ri.foundry.main.dataset.abc",),
            None,
            True,
        ),
    ],
)
def test_each_command_resolves_and_analyzes_once(
    tmp_path, service, arguments, resolver, resolver_arguments, ontology_rid, internal
):
    constructor, instance, context, target = service
    graph_path = tmp_path / f"{resolver}.json"
    result = runner.invoke(
        app,
        [
            "dependency",
            *arguments,
            "--profile",
            "qa",
            "--branch",
            "dev",
            "--change",
            "rename field",
            "--direction",
            "downstream",
            "--depth",
            "4",
            "--max-nodes",
            "250",
            "--max-requests",
            "300",
            "--max-pages",
            "120",
            "--max-items",
            "12000",
            "--time-budget-seconds",
            "90",
            "--graph-output",
            str(graph_path),
        ],
    )
    assert result.exit_code == 0, result.output
    constructor.assert_called_once()
    constructor_kwargs = constructor.call_args.kwargs
    assert constructor_kwargs["profile"] == "qa"
    if internal:
        provider = constructor_kwargs["conjure_provider"]
        assert provider.client.profile == "qa"
    else:
        assert "conjure_provider" not in constructor_kwargs
    create_kwargs = instance.create_context.call_args.kwargs
    assert create_kwargs["host"] == "https://qa.example.com"
    assert create_kwargs["ontology_rid"] == ontology_rid
    assert create_kwargs["requested_branch"] == "dev"
    assert create_kwargs["dataset_branch"] == "dev"
    budget = create_kwargs["budget"]
    assert budget.max_depth == 4
    assert budget.max_nodes == 250
    assert budget.max_requests == 300
    assert budget.max_pages == 120
    assert budget.max_items == 12000
    assert budget.time_budget_seconds == 90
    getattr(instance, resolver).assert_called_once_with(context, *resolver_arguments)
    instance.analyze.assert_called_once_with(
        target,
        context,
        direction="downstream",
        change="rename field",
        change_type=None,
        compare_artifact=None,
    )
    assert graph_path.exists()


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-requests", "1001"),
        ("--max-pages", "501"),
        ("--max-items", "100001"),
        ("--max-nodes", "1001"),
        ("--depth", "11"),
        ("--time-budget-seconds", "601"),
    ],
)
def test_hard_ceiling_fails_before_service_construction(tmp_path, option, value):
    with patch("pltr.commands.dependency.DependencyGraphService") as constructor:
        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                option,
                value,
                "--graph-output",
                str(tmp_path / "graph.json"),
            ],
        )
    assert result.exit_code != 0
    assert "hard ceiling" in result.output
    constructor.assert_not_called()


def test_output_does_not_replace_graph_output_or_repeat_analysis(tmp_path, service):
    _, instance, _, _ = service
    rendered = tmp_path / "rendered.json"
    graph = tmp_path / "graph.json"
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--format",
            "json",
            "--full",
            "--output",
            str(rendered),
            "--graph-output",
            str(graph),
        ],
    )
    assert result.exit_code == 0, result.output
    assert rendered.exists() and graph.exists()
    assert rendered != graph
    rendered_document = json.loads(rendered.read_text())
    artifact_document = json.loads(graph.read_text())
    assert rendered_document == artifact_document
    retained = {
        key: value
        for key, value in artifact_document.items()
        if key not in {"agent", "artifact"}
    }
    expected = analysis_result()
    assert retained == {key: value for key, value in expected.items() if key != "agent"}
    assert {
        key: value
        for key, value in artifact_document["agent"].items()
        if key != "artifact_reference"
    } == expected["agent"]
    artifact = artifact_document["artifact"]
    expected_digest = independent_payload_digest(artifact_document)
    assert artifact["path"] == str(graph.resolve())
    assert artifact["sha256"] == expected_digest
    assert artifact["analysis_id"] == f"dep-{expected_digest[:20]}"
    instance.analyze.assert_called_once()


@pytest.mark.parametrize("alias_kind", ["equal", "canonical", "symlink"])
def test_output_alias_collision_is_rejected_before_analysis_or_writes(
    tmp_path, alias_kind
):
    graph = tmp_path / "graph.json"
    if alias_kind == "equal":
        output = graph
    elif alias_kind == "canonical":
        (tmp_path / "nested").mkdir()
        output = tmp_path / "nested" / ".." / "graph.json"
    else:
        output = tmp_path / "rendered.json"
        output.symlink_to(graph)

    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch("pltr.commands.dependency.DependencyGraphService") as constructor,
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                "--output",
                str(output),
                "--graph-output",
                str(graph),
            ],
        )

    assert result.exit_code != 0
    assert "rendered output cannot replace the graph artifact" in result.output
    auth_constructor.assert_not_called()
    constructor.assert_not_called()
    assert not graph.exists()


def test_nonexistent_filesystem_equivalent_alias_is_rechecked_after_artifact_write(
    tmp_path, service
):
    graph = tmp_path / "Graph.json"
    output = tmp_path / "graph.json"

    def filesystem_equivalent_after_creation(first, second):
        assert Path(first).name == "graph.json"
        assert Path(second).name == "Graph.json"
        return graph.exists()

    with (
        patch(
            "pltr.commands.dependency._paths_alias",
            side_effect=filesystem_equivalent_after_creation,
        ),
        patch.object(
            dependency_command.formatter,
            "format_dependency_result",
        ) as render,
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                "--output",
                str(output),
                "--graph-output",
                str(graph),
            ],
        )

    assert result.exit_code != 0
    assert "rendered output cannot replace the graph artifact" in result.output
    assert json.loads(graph.read_text())["artifact"]["path"] == str(graph.resolve())
    render.assert_not_called()


def test_renderer_inode_guard_refuses_to_truncate_artifact(tmp_path):
    graph = tmp_path / "graph.json"
    rendered = tmp_path / "rendered.json"
    document = analysis_result()
    document["artifact"] = write_dependency_artifact(document, graph)
    rendered.hardlink_to(graph)
    original = graph.read_bytes()

    with pytest.raises(
        ProtectedOutputCollisionError,
        match="rendered output cannot replace the graph artifact",
    ):
        dependency_command.formatter.format_dependency_result(
            document,
            format_type="json",
            output_file=str(rendered),
            protected_output_file=str(graph),
        )

    retained = json.loads(graph.read_text())
    assert graph.read_bytes() == original
    assert rendered.read_bytes() == original
    assert retained["artifact"]["sha256"] == independent_payload_digest(retained)


def test_active_profile_and_non_secret_host_are_resolved_once(tmp_path):
    graph = tmp_path / "graph.json"
    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch("pltr.commands.dependency.DependencyGraphService") as constructor,
    ):
        auth_manager = auth_constructor.return_value
        auth_manager.get_current_profile.return_value = "prod"
        auth_manager.storage.get_profile.return_value = {
            "host": "https://prod.example.com/",
            "token": "secret-token",
            "client_secret": "secret-client",
        }
        service_instance = constructor.return_value
        service_instance.create_context.return_value = object()
        service_instance.resolve_resource.return_value = object()
        service_instance.analyze.return_value = analysis_result()

        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                "--graph-output",
                str(graph),
            ],
        )

    assert result.exit_code == 0, result.output
    auth_manager.get_current_profile.assert_called_once_with()
    auth_manager.storage.get_profile.assert_called_once_with("prod")
    constructor.assert_called_once()
    constructor_kwargs = constructor.call_args.kwargs
    assert constructor_kwargs["profile"] == "prod"
    assert constructor_kwargs["conjure_provider"].client.profile == "prod"
    create_kwargs = service_instance.create_context.call_args.kwargs
    assert create_kwargs["host"] == "https://prod.example.com/"
    assert "secret-token" not in repr(create_kwargs)
    assert "secret-client" not in repr(create_kwargs)


def test_output_cannot_alias_computed_default_graph_path(
    tmp_path, monkeypatch, service
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    analysis_id, _ = artifact_identity(analysis_result())
    graph = default_artifact_path(analysis_id)

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--output",
            str(graph),
        ],
    )

    assert result.exit_code != 0
    assert "rendered output cannot replace the graph artifact" in result.output
    assert not graph.exists()


def test_csv_has_every_explicit_row_kind(tmp_path, service):
    rendered = tmp_path / "rendered.csv"
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--format",
            "csv",
            "--output",
            str(rendered),
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    kinds = {row["row_kind"] for row in csv.DictReader(StringIO(rendered.read_text()))}
    assert kinds == {
        "agent",
        "artifact",
        "read-context",
        "node",
        "edge",
        "path",
        "coverage",
        "gap",
        "error",
        "evidence",
        "operation-provenance",
    }
    rows = list(csv.DictReader(StringIO(rendered.read_text())))
    artifact_row = next(row for row in rows if row["row_kind"] == "artifact")
    read_context_row = next(row for row in rows if row["row_kind"] == "read-context")
    artifact = json.loads(artifact_row["record"])
    read_context = json.loads(read_context_row["record"])
    assert artifact_row["id"] == artifact["analysis_id"]
    assert artifact["path"] == str((tmp_path / "graph.json").resolve())
    assert artifact["sha256"]
    assert read_context_row["id"] == "ctx"
    assert read_context["profile"] == "qa"
    assert read_context["host_fingerprint"] == "f9137f6af01050c3"


@pytest.mark.parametrize(
    "arguments",
    [
        ["object-type", "ri.ontology", "Employee"],
        ["property", "ri.ontology", "Employee", "email"],
        ["link-type", "ri.ontology", "Employee", "manager"],
        ["action-type", "ri.ontology", "promote"],
        ["query-type", "ri.ontology", "findEmployee"],
        ["resource", "ri.foundry.main.dataset.abc"],
    ],
)
def test_all_commands_accept_agent_options_and_project_comparison_artifact(
    tmp_path, service, arguments
):
    _, instance, _, target = service
    baseline = tmp_path / "baseline.json"
    baseline_payload = _valid_comparison_baseline()
    baseline.write_text(json.dumps(baseline_payload))

    result = runner.invoke(
        app,
        [
            "dependency",
            *arguments,
            "--change-type",
            "rename",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "agent",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dependency impact assessment [dependency-agent-v1]" in result.output
    assert instance.analyze.call_args.args[0] is target
    assert instance.analyze.call_args.kwargs["change_type"] == "rename"
    assert instance.analyze.call_args.kwargs["compare_artifact"] == baseline_payload


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--change-type", "breaking"),
        ("--output-mode", "human"),
    ],
)
def test_agent_options_are_closed_enums_before_service_construction(option, value):
    with (
        patch("pltr.commands.dependency._run") as run,
        patch("pltr.commands.dependency.DependencyGraphService") as constructor,
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                option,
                value,
            ],
        )

    output = strip_ansi(result.output)
    assert result.exit_code == 2
    assert f"Invalid value for '{option}'" in output
    assert value in output
    run.assert_not_called()
    constructor.assert_not_called()


def test_graph_json_and_csv_modes_retain_full_agent_contract(tmp_path, service):
    graph_result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--graph-output",
            str(tmp_path / "graph-table.json"),
        ],
    )
    assert graph_result.exit_code == 0, graph_result.output
    assert "Agent verification: must=0 should=1 unsupported=0" in graph_result.output
    assert (
        "Agent blast radius: critical=0 structural=0 indirect=1 unknown=0"
        in graph_result.output
    )

    json_result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--output-mode",
            "agent",
            "--format",
            "json",
            "--graph-output",
            str(tmp_path / "graph-json.json"),
        ],
    )
    assert json_result.exit_code == 0, json_result.output
    assert json.loads(json_result.output)["agent"]["schema_version"] == (
        "dependency-agent-v1"
    )

    csv_result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--output-mode",
            "agent",
            "--format",
            "csv",
            "--graph-output",
            str(tmp_path / "graph-csv.json"),
        ],
    )
    assert csv_result.exit_code == 0, csv_result.output
    agent_row = next(
        row
        for row in csv.DictReader(StringIO(csv_result.output))
        if row["row_kind"] == "agent"
    )
    assert json.loads(agent_row["record"])["schema_version"] == "dependency-agent-v1"


@pytest.mark.parametrize(
    ("status", "must_verify", "expected_exit"),
    [("clean", [], 0), ("needs-verification", [{"reason": "coverage-gap"}], 2)],
)
def test_ci_mode_uses_zero_or_two_without_reusing_fatal_exit_one(
    tmp_path, service, status, must_verify, expected_exit
):
    _, instance, _, _ = service
    payload = analysis_result()
    payload["agent"]["status"] = status
    payload["agent"]["verification"]["must_verify_before_merge"] = must_verify
    instance.analyze.return_value = payload

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == expected_exit
    summary = json.loads(result.output)
    assert summary["status"] == status
    assert summary["must_verify"] == len(must_verify)


@pytest.mark.parametrize(
    ("contents", "expected_message"),
    [
        (None, "cannot load comparison artifact"),
        ("{not-json", "cannot load comparison artifact"),
        ("[]", "must contain a JSON object"),
    ],
)
def test_ci_comparison_artifact_errors_use_fatal_machine_exit_one(
    tmp_path, service, contents, expected_message
):
    constructor, _, _, _ = service
    baseline = tmp_path / "baseline.json"
    if contents is not None:
        baseline.write_text(contents)

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == {
        "error_class": "invalid-invocation",
        "message": payload["message"],
        "retryable": False,
    }
    assert expected_message in payload["message"]
    constructor.assert_not_called()
    assert not (tmp_path / "graph.json").exists()


@pytest.mark.skipif(
    not hasattr(os, "mkfifo"), reason="mkfifo is unavailable on this platform"
)
def test_compare_artifact_rejects_non_regular_file_without_blocking(tmp_path, service):
    constructor, _, _, _ = service
    baseline = tmp_path / "baseline.fifo"
    os.mkfifo(baseline)

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_class"] == "invalid-invocation"
    assert "must be a regular file" in payload["message"]
    constructor.assert_not_called()


@pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is unavailable on this platform"
)
def test_compare_artifact_does_not_follow_a_symlink(tmp_path, service):
    constructor, _, _, _ = service
    real = tmp_path / "real-baseline.json"
    real.write_text(json.dumps({"artifact": {"analysis_id": "dep-baseline"}}))
    link = tmp_path / "linked-baseline.json"
    link.symlink_to(real)

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(link),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_class"] == "invalid-invocation"
    assert "cannot load comparison artifact" in payload["message"]
    constructor.assert_not_called()


def test_compare_artifact_rejects_files_over_the_byte_limit(tmp_path, service):
    constructor, _, _, _ = service
    baseline = tmp_path / "oversized.json"
    oversize = dependency_command.MAX_COMPARISON_ARTIFACT_BYTES + 1
    with open(baseline, "wb") as handle:
        handle.seek(oversize - 1)
        handle.write(b"0")

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_class"] == "invalid-invocation"
    assert "exceeds the" in payload["message"]
    assert "byte limit" in payload["message"]
    constructor.assert_not_called()


_MALFORMED_BASELINE = _valid_comparison_baseline()


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        ({}, "must have an object 'graph'"),
        ({"artifact": {}}, "must have an object 'graph'"),
        (_drop(_MALFORMED_BASELINE, "graph"), "must have an object 'graph'"),
        (
            _set(_MALFORMED_BASELINE, "not-an-object", "graph"),
            "must have an object 'graph'",
        ),
        (
            _drop(_MALFORMED_BASELINE, "graph", "nodes"),
            "must have an array 'graph.nodes'",
        ),
        (
            _set(_MALFORMED_BASELINE, "not-a-list", "graph", "nodes"),
            "must have an array 'graph.nodes'",
        ),
        (
            _set(_MALFORMED_BASELINE, [1, 2], "graph", "nodes"),
            "'graph.nodes[0]' must be an object",
        ),
        (
            _drop(_MALFORMED_BASELINE, "graph", "edges"),
            "must have an array 'graph.edges'",
        ),
        (
            _set(_MALFORMED_BASELINE, "not-a-list", "graph", "edges"),
            "must have an array 'graph.edges'",
        ),
        (
            _set(_MALFORMED_BASELINE, [{"id": "e"}, "bad"], "graph", "edges"),
            "'graph.edges[1]' must be an object",
        ),
        (_drop(_MALFORMED_BASELINE, "target"), "must have an object 'target'"),
        (
            _set(_MALFORMED_BASELINE, "not-an-object", "target"),
            "must have an object 'target'",
        ),
        (
            _drop(_MALFORMED_BASELINE, "read_contexts"),
            "must have an array 'read_contexts'",
        ),
        (
            _set(_MALFORMED_BASELINE, "not-a-list", "read_contexts"),
            "must have an array 'read_contexts'",
        ),
        (
            _set(_MALFORMED_BASELINE, [], "read_contexts"),
            "must have a non-empty array 'read_contexts'",
        ),
        (
            _set(_MALFORMED_BASELINE, [1], "read_contexts"),
            "'read_contexts[0]' must be an object",
        ),
        (_drop(_MALFORMED_BASELINE, "budget"), "must have an object 'budget'"),
        (
            _set(_MALFORMED_BASELINE, "not-an-object", "budget"),
            "must have an object 'budget'",
        ),
        (
            _drop(_MALFORMED_BASELINE, "budget", "limits"),
            "must have an object 'budget.limits'",
        ),
        (
            _set(_MALFORMED_BASELINE, "not-an-object", "budget", "limits"),
            "must have an object 'budget.limits'",
        ),
        (_drop(_MALFORMED_BASELINE, "artifact"), "must have an object 'artifact'"),
        (
            _set(_MALFORMED_BASELINE, "not-an-object", "artifact"),
            "must have an object 'artifact'",
        ),
        (
            _drop(_MALFORMED_BASELINE, "artifact", "analysis_id"),
            "must have a non-empty string 'artifact.analysis_id'",
        ),
        (
            _set(_MALFORMED_BASELINE, 5, "artifact", "analysis_id"),
            "must have a non-empty string 'artifact.analysis_id'",
        ),
        (
            _set(_MALFORMED_BASELINE, "", "artifact", "analysis_id"),
            "must have a non-empty string 'artifact.analysis_id'",
        ),
        (
            _drop(_MALFORMED_BASELINE, "artifact", "sha256"),
            "must have a non-empty string 'artifact.sha256'",
        ),
        (
            _set(_MALFORMED_BASELINE, 5, "artifact", "sha256"),
            "must have a non-empty string 'artifact.sha256'",
        ),
        (
            _set(_MALFORMED_BASELINE, 5, "artifact", "path"),
            "must have a string 'artifact.path'",
        ),
    ],
)
def test_compare_artifact_rejects_invalid_container_shapes(
    tmp_path, service, payload, expected_fragment
):
    constructor, _, _, _ = service
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    result_payload = json.loads(result.output)
    assert result_payload["error_class"] == "invalid-invocation"
    assert expected_fragment in result_payload["message"]
    constructor.assert_not_called()


def test_compare_artifact_rejects_containers_exceeding_the_hard_ceiling(
    tmp_path, service, monkeypatch
):
    constructor, _, _, _ = service
    monkeypatch.setattr(dependency_command, "MAX_COMPARISON_GRAPH_NODES", 1)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"graph": {"nodes": [{"id": "a"}, {"id": "b"}]}}))

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--output-mode",
            "ci",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "'graph.nodes' exceeds the 1 entry ceiling" in payload["message"]
    constructor.assert_not_called()


def test_compare_artifact_error_raises_bad_parameter_outside_ci_mode(tmp_path, service):
    constructor, _, _, _ = service
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{not-json")

    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--compare-artifact",
            str(baseline),
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for --compare-artifact" in strip_ansi(result.output)
    constructor.assert_not_called()
    assert not (tmp_path / "graph.json").exists()


def test_success_result_and_persisted_artifact_share_artifact_reference(
    tmp_path, service
):
    graph = tmp_path / "graph.json"
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--output-mode",
            "agent",
            "--format",
            "json",
            "--graph-output",
            str(graph),
        ],
    )

    assert result.exit_code == 0, result.output
    returned = json.loads(result.output)
    persisted = json.loads(graph.read_text())
    expected_reference = {
        "artifact_id": persisted["artifact"]["analysis_id"],
        "path": persisted["artifact"]["path"],
        "sha256": persisted["artifact"]["sha256"],
    }
    assert returned["agent"]["artifact_reference"] == expected_reference
    assert persisted["agent"]["artifact_reference"] == expected_reference


def test_partial_gap_exits_zero_and_table_references_complete_artifact(
    tmp_path, service
):
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )
    assert result.exit_code == 0
    assert "schedule-index-may-be-stale" in result.output
    assert "up to one hour" in result.output
    assert "Graph artifact:" in result.output
    assert "SHA-256:" in result.output
    assert "Employee <- Query q" in result.output
    assert "output" in result.output
    assert "client.ontologies.Ontology.QueryType.list" in result.output


def test_no_internal_preserves_sdk_only_graph_and_constructs_no_internal_client(
    tmp_path, service
):
    constructor, instance, _, _ = service
    expected = analysis_result()
    expected["coverage_records"] = [{"surface": "query-metadata", "status": "partial"}]
    instance.analyze.return_value = expected
    with (
        patch("pltr.commands.dependency.FoundryInternalClient") as internal_client,
        patch("pltr.commands.dependency.ConjureRestProvider") as provider,
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "property",
                "ri.ontology",
                "Employee",
                "email",
                "--profile",
                "qa",
                "--no-internal",
                "--format",
                "json",
                "--graph-output",
                str(tmp_path / "graph.json"),
            ],
        )

    assert result.exit_code == 0, result.output
    internal_client.assert_not_called()
    provider.assert_not_called()
    constructor.assert_called_once_with(profile="qa")
    rendered = json.loads(result.output)
    assert rendered["graph"] == expected["graph"]
    assert rendered["coverage_records"] == expected["coverage_records"]
    assert all(
        operation.get("transport", "sdk") == "sdk"
        for operation in rendered["operation_provenance"]
    )
    assert (
        json.loads((tmp_path / "graph.json").read_text())["graph"] == expected["graph"]
    )


@pytest.mark.parametrize("positive_controls", [False, True])
def test_positive_controls_configure_the_shared_internal_client_once(
    tmp_path, service, positive_controls
):
    _, _, _, _ = service
    with patch("pltr.commands.dependency.FoundryInternalClient") as client_constructor:
        arguments = [
            "dependency",
            "object-type",
            "ri.ontology",
            "Employee",
            "--profile",
            "qa",
            "--graph-output",
            str(tmp_path / f"controls-{positive_controls}.json"),
        ]
        if positive_controls:
            arguments.append("--positive-controls")
        result = runner.invoke(app, arguments)

    assert result.exit_code == 0, result.output
    client_constructor.assert_called_once_with("qa")
    assert (
        client_constructor.return_value.positive_controls_enabled is positive_controls
    )


def test_sdk_conjure_subset_never_invokes_graphql_and_records_no_graphql_provenance(
    tmp_path,
):
    graph_path = tmp_path / "conjure-only.json"
    sdk_client = _internal_edge_sdk_client()
    sdk_client.ontologies.Ontology.ObjectType.get_full_metadata.return_value.object_type.rid = "ri.ontology.main.object-type.employee"
    internal_client = Mock()
    internal_client.conjure.return_value = (200, {"datasources": []}, "{}")

    def build_service(*, profile, conjure_provider=None):
        assert profile == "qa"
        return RealDependencyGraphService(
            client=sdk_client,
            conjure_provider=conjure_provider,
        )

    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch(
            "pltr.commands.dependency.DependencyGraphService",
            side_effect=build_service,
        ),
        patch(
            "pltr.commands.dependency.FoundryInternalClient",
            return_value=internal_client,
        ) as client_constructor,
    ):
        auth_constructor.return_value.storage.get_profile.return_value = {
            "host": "https://qa.example.com",
            "token": "command-token",
        }
        result = runner.invoke(
            app,
            [
                "dependency",
                "object-type",
                "ri.ontology",
                "Employee",
                "--profile",
                "qa",
                "--providers",
                "sdk,conjure",
                "--format",
                "json",
                "--graph-output",
                str(graph_path),
            ],
        )

    assert result.exit_code == 0, result.output
    client_constructor.assert_called_once_with("qa")
    internal_client.conjure.assert_called_once()
    internal_client.graphql.assert_not_called()
    artifact = json.loads(graph_path.read_text())
    transports = {
        operation.get("transport", "sdk")
        for operation in artifact["operation_provenance"]
    }
    assert "conjure-rest" in transports
    assert "graphql-sse" not in transports


@pytest.mark.parametrize(
    ("providers", "conjure_enabled", "graphql_enabled"),
    [
        ("sdk,conjure", True, False),
        ("sdk,graphql", False, True),
        ("sdk,conjure,graphql", True, True),
    ],
)
def test_provider_subset_configures_only_selected_internal_transports(
    tmp_path, service, providers, conjure_enabled, graphql_enabled
):
    constructor, instance, _, _ = service
    payload = analysis_result()
    if conjure_enabled:
        payload["operation_provenance"].append(
            {
                "id": "op-conjure",
                "transport": "conjure-rest",
                "acp_id": "ACP-04",
            }
        )
    if graphql_enabled:
        payload["operation_provenance"].append(
            {
                "id": "op-graphql",
                "transport": "graphql-sse",
                "acp_id": "ACP-05",
            }
        )
    instance.analyze.return_value = payload
    with (
        patch("pltr.commands.dependency.FoundryInternalClient") as client_constructor,
        patch("pltr.commands.dependency.ConjureRestProvider") as provider_constructor,
    ):
        internal_client = client_constructor.return_value
        provider = provider_constructor.return_value
        result = runner.invoke(
            app,
            [
                "dependency",
                "object-type",
                "ri.ontology",
                "Employee",
                "--profile",
                "qa",
                "--providers",
                providers,
                "--format",
                "json",
                "--graph-output",
                str(tmp_path / "graph.json"),
            ],
        )

    assert result.exit_code == 0, result.output
    client_constructor.assert_called_once_with("qa")
    provider_constructor.assert_called_once_with(internal_client)
    constructor.assert_called_once_with(profile="qa", conjure_provider=provider)
    assert (instance._conjure_provider is provider) is conjure_enabled
    assert (instance._graphql_client is internal_client) is graphql_enabled
    artifact = json.loads((tmp_path / "graph.json").read_text())
    transports = {
        operation.get("transport", "sdk")
        for operation in artifact["operation_provenance"]
    }
    expected = {"sdk"}
    if conjure_enabled:
        expected.add("conjure-rest")
    if graphql_enabled:
        expected.add("graphql-sse")
    assert transports == expected


@pytest.mark.parametrize("providers", ["", "sdk,unknown", "conjure,graphql"])
def test_invalid_provider_subset_fails_before_internal_provider_construction(
    tmp_path, providers
):
    with (
        patch("pltr.commands.dependency.FoundryInternalClient") as internal_client,
        patch("pltr.commands.dependency.DependencyGraphService") as service_constructor,
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "object-type",
                "ri.ontology",
                "Employee",
                "--providers",
                providers,
                "--graph-output",
                str(tmp_path / "graph.json"),
            ],
        )

    assert result.exit_code == 2
    assert "--providers" in strip_ansi(result.output)
    internal_client.assert_not_called()
    service_constructor.assert_not_called()


@pytest.mark.parametrize(
    ("format_type", "full"),
    [("table", False), ("table", True), ("json", False), ("csv", False)],
)
def test_each_rendering_mode_analyzes_and_writes_artifact_once(
    tmp_path, service, format_type, full
):
    _, instance, _, _ = service
    graph_path = tmp_path / f"{format_type}-{full}.json"
    real_writer = dependency_command.write_dependency_artifact
    with patch(
        "pltr.commands.dependency.write_dependency_artifact", wraps=real_writer
    ) as writer:
        arguments = [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--format",
            format_type,
            "--graph-output",
            str(graph_path),
        ]
        if full:
            arguments.append("--full")
        result = runner.invoke(app, arguments)

    assert result.exit_code == 0, result.output
    instance.create_context.assert_called_once()
    instance.analyze.assert_called_once()
    writer.assert_called_once()


def _internal_rendering_result() -> dict:
    payload = analysis_result()
    payload["graph"]["nodes"].extend(
        [
            {"id": "app:payroll", "kind": "application"},
            {"id": "workshop:payroll", "kind": "workshop-module"},
            {"id": "transform:payroll", "kind": "transform"},
            {"id": "repo:payroll", "kind": "code-repository"},
            {"id": "dataset:payroll", "kind": "dataset"},
        ]
    )
    payload["graph"]["edges"].extend(
        [
            {
                "id": "edge-app",
                "source": "object:Employee",
                "target": "app:payroll",
                "relation_kind": "object-consumed-by-app",
                "evidence_ids": ["ev-graphql"],
                "attributes": {
                    "consumer_osdk_impact": {
                        "oldest": "0.4.0",
                        "latest": "0.6.0",
                    }
                },
            },
            {
                "id": "edge-workshop",
                "source": "object:Employee",
                "target": "workshop:payroll",
                "relation_kind": "object-consumed-by-workshop",
                "evidence_ids": ["ev-graphql"],
            },
            {
                "id": "edge-transform",
                "source": "transform:payroll",
                "target": "dataset:payroll",
                "relation_kind": "transform-builds-dataset",
                "evidence_ids": ["ev-conjure"],
            },
            {
                "id": "edge-lineage",
                "source": "repo:payroll",
                "target": "dataset:payroll",
                "relation_kind": "code-repo-builds-dataset",
                "evidence_ids": ["ev-conjure"],
            },
        ]
    )
    payload["ranked_relationships"] = [
        {
            "readable_path": "Employee -> Payroll app (OSDK 0.4.0-0.6.0)",
            "direction": "downstream",
            "relation_kind": "object-consumed-by-app",
            "evidence_summary": {
                "locator": "objectTypeV2.dependents.values[0]",
                "transport": "graphql-sse",
                "acp_id": "ACP-05",
            },
        },
        {
            "readable_path": "Employee -> Payroll workshop",
            "direction": "downstream",
            "relation_kind": "object-consumed-by-workshop",
            "evidence_summary": {
                "locator": "objectTypeV2.dependents.values[1]",
                "transport": "graphql-sse",
                "acp_id": "ACP-05",
            },
        },
        {
            "readable_path": "Payroll transform -> Payroll dataset",
            "direction": "downstream",
            "relation_kind": "transform-builds-dataset",
            "evidence_summary": {
                "locator": "jobspec.outputs[0]",
                "transport": "conjure-rest",
                "acp_id": "ACP-01",
            },
        },
        {
            "readable_path": "Payroll repo -> Payroll dataset",
            "direction": "downstream",
            "relation_kind": "code-repo-builds-dataset",
            "evidence_summary": {
                "locator": "transforms.py:10-14",
                "transport": "conjure-rest",
                "acp_id": "ACP-03",
            },
        },
    ]
    payload["gaps"] = [
        {
            "surface": "object-type-consumers",
            "coverage": "inconclusive",
            "reason_code": "route-not-mounted",
            "message": "Internal route is not mounted.",
            "operation": "ACP-05",
        },
        {
            "surface": "schedule-reverse-index",
            "coverage": "partial",
            "reason_code": "schedule-index-may-be-stale",
            "message": "Schedule index is stale.",
        },
    ]
    payload["operation_provenance"].extend(
        [
            {
                "id": "op-conjure",
                "transport": "conjure-rest",
                "acp_id": "ACP-03",
            },
            {
                "id": "op-graphql",
                "transport": "graphql-sse",
                "acp_id": "ACP-05",
            },
        ]
    )
    return payload


@pytest.mark.parametrize("format_type", ["table", "json", "csv"])
def test_internal_edges_provenance_and_gap_severity_render_in_every_format(
    tmp_path, service, format_type
):
    _, instance, _, _ = service
    instance.analyze.return_value = _internal_rendering_result()
    result = runner.invoke(
        app,
        [
            "dependency",
            "object-type",
            "ri.ontology",
            "Employee",
            "--format",
            format_type,
            "--full",
            "--graph-output",
            str(tmp_path / f"{format_type}.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    if format_type == "table":
        output = strip_ansi(result.output)
        assert "object-consumed-by-app" in output
        assert "object-consumed-by-workshop" in output
        assert "transform-builds-dataset" in output
        assert "code-repo-builds-dataset" in output
        assert "OSDK 0.4.0-0.6.0" in output
        assert "graphql-sse ACP-05" in output
        assert "inconclusive:route-not-mounted" in output
        assert "partial:schedule-index-may-be-stale" in output
    elif format_type == "json":
        document = json.loads(result.output)
        assert {edge.get("relation_kind") for edge in document["graph"]["edges"]} >= {
            "object-consumed-by-app",
            "object-consumed-by-workshop",
            "transform-builds-dataset",
            "code-repo-builds-dataset",
        }
        app_edge = next(
            edge
            for edge in document["graph"]["edges"]
            if edge.get("relation_kind") == "object-consumed-by-app"
        )
        assert app_edge["attributes"]["consumer_osdk_impact"] == {
            "oldest": "0.4.0",
            "latest": "0.6.0",
        }
        assert {
            operation.get("transport") for operation in document["operation_provenance"]
        } >= {"conjure-rest", "graphql-sse"}
        assert {gap["coverage"] for gap in document["gaps"]} == {
            "inconclusive",
            "partial",
        }
    else:
        rows = list(csv.DictReader(StringIO(result.output)))
        edge_records = {
            json.loads(row["record"]).get("relation_kind")
            for row in rows
            if row["row_kind"] == "edge"
        }
        gap_records = [
            json.loads(row["record"]) for row in rows if row["row_kind"] == "gap"
        ]
        provenance_records = [
            json.loads(row["record"])
            for row in rows
            if row["row_kind"] == "operation-provenance"
        ]
        assert edge_records >= {
            "object-consumed-by-app",
            "object-consumed-by-workshop",
            "transform-builds-dataset",
            "code-repo-builds-dataset",
        }
        assert {gap["coverage"] for gap in gap_records} == {
            "inconclusive",
            "partial",
        }
        assert {record.get("transport") for record in provenance_records} >= {
            "conjure-rest",
            "graphql-sse",
        }


@pytest.mark.parametrize(
    ("status", "payload", "reason", "expected"),
    [
        (
            404,
            {"errorName": "Route:RouteNotMounted"},
            "route-not-mounted",
            "inconclusive:route-not-mounted",
        ),
        (
            401,
            {"errorName": "Default:Unauthorized"},
            "token-expired",
            "DEGRADED [token-expired]",
        ),
    ],
)
def test_mocked_internal_http_degradation_exits_zero_with_sdk_graph(
    tmp_path, status, payload, reason, expected
):
    graph_path = tmp_path / f"{reason}.json"
    response = Mock(status_code=status, text=json.dumps(payload))
    response.json.return_value = payload

    def build_service(*, profile, conjure_provider=None):
        assert profile == "qa"
        return RealDependencyGraphService(
            client=_internal_edge_sdk_client(),
            conjure_provider=conjure_provider,
        )

    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch(
            "pltr.commands.dependency.DependencyGraphService",
            side_effect=build_service,
        ),
        patch(
            "pltr.services.foundry_internal_client.CredentialStorage"
        ) as credential_storage,
        patch(
            "pltr.services.foundry_internal_client.requests.request",
            return_value=response,
        ) as request,
    ):
        auth_constructor.return_value.storage.get_profile.return_value = {
            "host": "https://qa.example.com",
            "token": "command-token",
        }
        credential_storage.return_value.get_profile.return_value = {
            "host": "https://qa.example.com",
            "token": "request-token",
        }
        result = runner.invoke(
            app,
            [
                "dependency",
                "property",
                "ri.ontology",
                "Employee",
                "email",
                "--profile",
                "qa",
                "--graph-output",
                str(graph_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert expected in strip_ansi(result.output)
    request.assert_called_once()
    artifact = json.loads(graph_path.read_text())
    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == artifact["target"]["node_id"]
        for edge in artifact["graph"]["edges"]
    )
    assert any(gap["reason_code"] == reason for gap in artifact["gaps"])


def test_internal_connection_error_degrades_to_inconclusive_with_sdk_graph(tmp_path):
    graph_path = tmp_path / "connection.json"

    def build_service(*, profile, conjure_provider=None):
        assert profile == "qa"
        return RealDependencyGraphService(
            client=_internal_edge_sdk_client(),
            conjure_provider=conjure_provider,
        )

    with (
        patch("pltr.commands.dependency.AuthManager") as auth_constructor,
        patch(
            "pltr.commands.dependency.DependencyGraphService",
            side_effect=build_service,
        ),
        patch(
            "pltr.services.foundry_internal_client.CredentialStorage"
        ) as credential_storage,
        patch(
            "pltr.services.foundry_internal_client.requests.request",
            side_effect=requests.ConnectionError("endpoint unreachable"),
        ) as request,
    ):
        auth_constructor.return_value.storage.get_profile.return_value = {
            "host": "https://qa.example.com",
            "token": "command-token",
        }
        credential_storage.return_value.get_profile.return_value = {
            "host": "https://qa.example.com",
            "token": "request-token",
        }
        result = runner.invoke(
            app,
            [
                "dependency",
                "property",
                "ri.ontology",
                "Employee",
                "email",
                "--profile",
                "qa",
                "--graph-output",
                str(graph_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "inconclusive:connection" in strip_ansi(result.output)
    request.assert_called_once()
    artifact = json.loads(graph_path.read_text())
    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == artifact["target"]["node_id"]
        for edge in artifact["graph"]["edges"]
    )
    connection_gap = next(
        gap for gap in artifact["gaps"] if gap["reason_code"] == "connection"
    )
    assert connection_gap["coverage"] == "inconclusive"
    connection_coverage = next(
        record
        for record in artifact["coverage"]
        if record["operation"] == "ACP-04" and record["transport"] == "conjure-rest"
    )
    assert connection_coverage["status"] == "inconclusive"


def test_internal_column_edge_renders_in_compact_and_json_with_transport(
    tmp_path, service
):
    _, instance, _, _ = service
    payload = analysis_result()
    payload["graph"]["nodes"].append(
        {
            "id": "ri.foundry.main.dataset.programs#program_id",
            "kind": "dataset-column",
            "display_name": "program_id",
        }
    )
    payload["graph"]["edges"].append(
        {
            "id": "edge-column",
            "source": "ri.foundry.main.dataset.programs#program_id",
            "target": "object:Employee",
            "relation_kind": "column-backs-property",
            "evidence_ids": ["ev-internal"],
        }
    )
    payload["ranked_relationships"] = [
        {
            "readable_path": "program_id -> Employee.email",
            "direction": "downstream",
            "relation_kind": "column-backs-property",
            "evidence_summary": {
                "locator": "datasources[0].definition.propertyMapping.email",
                "transport": "conjure-rest",
                "acp_id": "ACP-04",
            },
        }
    ]
    payload["evidence"].append(
        {
            "id": "ev-internal",
            "operation_provenance_id": "op-internal",
            "locator": "datasources[0].definition.propertyMapping.email",
        }
    )
    payload["operation_provenance"].append(
        {
            "id": "op-internal",
            "transport": "conjure-rest",
            "acp_id": "ACP-04",
            "http_verb": "GET",
            "path": "/api/v2/ontologies/ri.ontology/objectTypes/Employee",
        }
    )
    instance.analyze.return_value = payload

    compact = runner.invoke(
        app,
        [
            "dependency",
            "property",
            "ri.ontology",
            "Employee",
            "email",
            "--profile",
            "qa",
            "--graph-output",
            str(tmp_path / "compact.json"),
        ],
    )
    assert compact.exit_code == 0, compact.output
    compact_output = strip_ansi(compact.output)
    assert "column-backs-property" in compact_output
    assert "conjure-rest ACP-04" in compact_output

    rendered_json = runner.invoke(
        app,
        [
            "dependency",
            "property",
            "ri.ontology",
            "Employee",
            "email",
            "--profile",
            "qa",
            "--format",
            "json",
            "--graph-output",
            str(tmp_path / "json.json"),
        ],
    )
    assert rendered_json.exit_code == 0, rendered_json.output
    document = json.loads(rendered_json.output)
    assert any(
        edge.get("relation_kind") == "column-backs-property"
        for edge in document["graph"]["edges"]
    )
    assert any(
        operation.get("transport") == "conjure-rest"
        and operation.get("acp_id") == "ACP-04"
        for operation in document["operation_provenance"]
    )


def test_json_preserves_branchless_operation_provenance(tmp_path, service):
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--branch",
            "dev",
            "--format",
            "json",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    branchless = document["operation_provenance"][1]
    assert branchless["branch_argument"] == {"mode": "not-applicable", "value": None}


def test_only_six_direct_target_commands_are_advertised():
    result = runner.invoke(app, ["dependency", "--help"])
    assert result.exit_code == 0
    for command in (
        "object-type",
        "property",
        "link-type",
        "action-type",
        "query-type",
        "resource",
    ):
        assert command in result.output
    for excluded in ("function", "schedule", "workshop-variable"):
        assert f"  {excluded} " not in result.output


def test_resource_rejects_workshop_name_before_service_construction():
    with patch("pltr.commands.dependency.DependencyGraphService") as constructor:
        result = runner.invoke(app, ["dependency", "resource", "my-workshop-variable"])
    assert result.exit_code != 0
    assert "Compass-resolvable RID" in result.output
    constructor.assert_not_called()


def test_fatal_error_is_stable_json_without_artifact(tmp_path, service):
    _, instance, _, _ = service
    instance.resolve_resource.side_effect = DependencyFatalError(
        "permission-denied",
        "ri.foundry.main.dataset.secret",
        "filesystem.resource.get",
        "Access denied",
        False,
        "ctx-1",
    )
    graph = tmp_path / "graph.json"
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.secret",
            "--format",
            "json",
            "--graph-output",
            str(graph),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_class"] == "permission-denied"
    assert not graph.exists()
    instance.analyze.assert_not_called()


def test_unknown_exception_is_structured_without_traceback(tmp_path, service):
    _, instance, _, _ = service
    instance.analyze.side_effect = RuntimeError("unexpected")
    result = runner.invoke(
        app,
        [
            "dependency",
            "resource",
            "ri.foundry.main.dataset.abc",
            "--format",
            "json",
            "--graph-output",
            str(tmp_path / "graph.json"),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_class"] == "unknown"
    assert payload["message"] == "unexpected"
    assert "Traceback" not in result.output


def test_artifact_failure_prevents_compact_success_output(tmp_path, service):
    with patch(
        "pltr.commands.dependency.write_dependency_artifact",
        side_effect=ArtifactWriteError("read only"),
    ):
        result = runner.invoke(
            app,
            [
                "dependency",
                "resource",
                "ri.foundry.main.dataset.abc",
                "--graph-output",
                str(tmp_path / "graph.json"),
            ],
        )
    assert result.exit_code == 1
    assert "artifact-write-failed" in result.output
    assert "Dependency analysis\n" not in result.output
