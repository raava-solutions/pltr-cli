import json
from unittest.mock import call, patch

import pytest
import typer
from typer.testing import CliRunner

from pltr.commands.proposal import app as proposal_app
from pltr.services.proposal import (
    ProposalAction,
    ProposalRemoteServiceError,
    ProposalType,
    UnsupportedProposalCapabilityError,
)


runner = CliRunner()
app = typer.Typer()
app.add_typer(proposal_app, name="proposal")


@pytest.fixture
def proposal_service():
    with patch("pltr.commands.proposal.ProposalService") as service_class:
        yield service_class.return_value, service_class


def test_create_routes_explicit_type_payload_and_profile(proposal_service):
    service, service_class = proposal_service
    service.create.return_value = {"id": "pr-1", "state": "OPEN"}

    result = runner.invoke(
        app,
        [
            "proposal",
            "create",
            "code-pr",
            "--parent-rid",
            "repo-rid",
            "--title",
            "Add feature",
            "--source-ref",
            "feature",
            "--target-ref",
            "main",
            "--profile",
            "work",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"id": "pr-1", "state": "OPEN"}
    service_class.assert_called_once_with(profile="work")
    service.create.assert_called_once_with(
        ProposalType.CODE_PR,
        parent_rid="repo-rid",
        title="Add feature",
        source_ref="feature",
        target_ref="main",
        description=None,
    )


@pytest.mark.parametrize(
    ("arguments", "method_name", "expected_call"),
    [
        (
            ["list", "code-pr", "repo"],
            "list",
            call(ProposalType.CODE_PR, parent_rid="repo"),
        ),
        (
            ["get", "global-proposal", "gp-1", "--parent-rid", "ontology"],
            "get",
            call(ProposalType.GLOBAL_PROPOSAL, "gp-1", parent_rid="ontology"),
        ),
        (
            ["comment", "code-pr", "12", "Looks good", "--parent-rid", "repo"],
            "comment",
            call(ProposalType.CODE_PR, "12", "Looks good", parent_rid="repo"),
        ),
    ],
)
def test_safe_commands_route_supported_service_results_as_json(
    proposal_service, arguments, method_name, expected_call
):
    service, _ = proposal_service
    getattr(service, method_name).return_value = {"ok": True, "id": "result"}

    result = runner.invoke(app, ["proposal", *arguments, "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"ok": True, "id": "result"}
    assert result.stdout.lstrip().startswith("{")
    assert result.stdout.rstrip().endswith("}")
    assert getattr(service, method_name).call_args == expected_call


@pytest.mark.parametrize(
    ("verb", "proposal_type", "action"),
    [
        ("approve", "code-pr", ProposalAction.APPROVE),
        ("request-changes", "code-pr", ProposalAction.REQUEST_CHANGES),
        ("merge", "code-pr", ProposalAction.MERGE),
        ("close", "code-pr", ProposalAction.CLOSE),
        ("list", "global-proposal", ProposalAction.LIST),
        ("comment", "global-proposal", ProposalAction.COMMENT),
        ("approve", "global-proposal", ProposalAction.APPROVE),
        ("request-changes", "global-proposal", ProposalAction.REQUEST_CHANGES),
        ("accept", "global-proposal", ProposalAction.ACCEPT),
    ],
)
def test_unsupported_verbs_return_clean_typed_json(
    proposal_service, verb, proposal_type, action
):
    service, _ = proposal_service
    method_name = "request_changes" if verb == "request-changes" else verb
    if verb == "close":
        service.require_capability.side_effect = UnsupportedProposalCapabilityError(
            ProposalType.CODE_PR, ProposalAction.CLOSE
        )
    else:
        getattr(service, method_name).side_effect = UnsupportedProposalCapabilityError(
            ProposalType(proposal_type), action
        )
    arguments = ["proposal", verb, proposal_type]
    if verb == "list":
        arguments.append("parent")
    elif verb == "comment":
        arguments.extend(["id", "message"])
    else:
        arguments.append("id")
    arguments.extend(["--format", "json"])
    if verb == "close":
        arguments.append("--yes")

    result = runner.invoke(app, arguments)

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["category"] == "unsupported-capability"
    assert payload["error"]["action"] == action.value
    assert result.stdout.lstrip().startswith("{")
    assert result.stdout.rstrip().endswith("}")


def test_missing_explicit_type_fails_before_service_construction(proposal_service):
    _, service_class = proposal_service

    result = runner.invoke(app, ["proposal", "get"])

    assert result.exit_code != 0
    service_class.assert_not_called()


def test_invalid_explicit_type_is_clean_json(proposal_service):
    _, service_class = proposal_service

    result = runner.invoke(
        app, ["proposal", "get", "unknown", "id", "--format", "json"]
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["category"] == "validation"
    service_class.assert_not_called()


def test_close_refreshes_then_prompts_and_decline_prevents_write(proposal_service):
    service, _ = proposal_service
    service.get.return_value = {"id": "gp-1", "title": "Change schema"}

    result = runner.invoke(
        app,
        ["proposal", "close", "global-proposal", "gp-1"],
        input="n\n",
    )

    assert result.exit_code == 4
    service.get.assert_called_once_with(
        ProposalType.GLOBAL_PROPOSAL, "gp-1", parent_rid=None
    )
    service.require_capability.assert_called_once_with(
        ProposalType.GLOBAL_PROPOSAL, ProposalAction.CLOSE
    )
    service.close.assert_not_called()
    assert "Change schema" in result.stdout


def test_close_yes_refreshes_before_write_and_forwards_profile(proposal_service):
    service, service_class = proposal_service
    calls = []
    service.require_capability.side_effect = lambda *args, **kwargs: calls.append(
        "capability"
    )
    service.get.side_effect = lambda *args, **kwargs: calls.append("get") or {
        "id": "gp-1"
    }
    service.close.side_effect = lambda *args, **kwargs: calls.append("close") or {
        "id": "gp-1",
        "state": "CLOSED",
    }

    result = runner.invoke(
        app,
        [
            "proposal",
            "close",
            "global-proposal",
            "gp-1",
            "--parent-rid",
            "ontology",
            "--yes",
            "--profile",
            "work",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"id": "gp-1", "state": "CLOSED"}
    assert calls == ["capability", "get", "close"]
    service_class.assert_called_once_with(profile="work")
    service.get.assert_called_once_with(
        ProposalType.GLOBAL_PROPOSAL, "gp-1", parent_rid="ontology"
    )
    service.require_capability.assert_called_once_with(
        ProposalType.GLOBAL_PROPOSAL, ProposalAction.CLOSE
    )
    service.close.assert_called_once_with(
        ProposalType.GLOBAL_PROPOSAL, "gp-1", parent_rid="ontology"
    )


def test_close_json_without_yes_is_json_only_and_does_not_read(proposal_service):
    service, service_class = proposal_service

    result = runner.invoke(
        app,
        ["proposal", "close", "global-proposal", "gp-1", "--format", "json"],
    )

    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["category"] == "validation"
    service_class.assert_not_called()
    service.get.assert_not_called()
    service.close.assert_not_called()


def test_close_surfaces_provider_error_faithfully_as_json(proposal_service):
    service, _ = proposal_service
    service.get.return_value = {"id": "gp-1"}
    service.close.side_effect = ProposalRemoteServiceError("provider refused close")

    result = runner.invoke(
        app,
        [
            "proposal",
            "close",
            "global-proposal",
            "gp-1",
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 7
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": {
            "category": "remote-service",
            "message": "provider refused close",
        },
    }


def test_proposal_group_is_registered():
    result = runner.invoke(app, ["proposal", "--help"])

    assert result.exit_code == 0
    assert "create" in result.stdout
    assert "request-changes" in result.stdout
    assert "close" in result.stdout


@pytest.mark.parametrize(
    ("arguments", "action"),
    [
        (
            [
                "create",
                "code-pr",
                "--parent-rid",
                "repo",
                "--title",
                "Title",
                "--source-ref",
                "feature",
            ],
            "create",
        ),
        (["get", "global-proposal", "gp-1"], "get"),
        (["close", "global-proposal", "gp-1", "--yes"], "close"),
    ],
)
def test_real_service_denial_is_json_only_and_pre_auth(arguments, action):
    result = runner.invoke(
        app, ["proposal", *arguments, "--profile", "unused", "--format", "json"]
    )

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert payload["error"]["category"] == "unsupported-capability"
    assert payload["error"]["action"] == action
