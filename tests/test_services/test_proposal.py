from unittest.mock import Mock

import pytest

from pltr.services.proposal import (
    MCP_VERIFIED_CAPABILITIES,
    SDK_REACHABLE_CAPABILITIES,
    ProposalAction,
    ProposalAuthenticationError,
    ProposalConflictError,
    ProposalRemoteServiceError,
    ProposalService,
    ProposalType,
    ProposalValidationError,
    UnsupportedProposalCapabilityError,
    normalize_proposal_error,
    parse_proposal_type,
)


def test_capability_matrix_distinguishes_mcp_from_sdk_reachability():
    assert (ProposalType.CODE_PR, ProposalAction.CREATE) in MCP_VERIFIED_CAPABILITIES
    assert (
        ProposalType.GLOBAL_PROPOSAL,
        ProposalAction.CLOSE,
    ) in MCP_VERIFIED_CAPABILITIES
    assert SDK_REACHABLE_CAPABILITIES == frozenset()


@pytest.mark.parametrize(
    ("method_name", "proposal_type", "args", "kwargs", "action"),
    [
        (
            "create",
            ProposalType.CODE_PR,
            (),
            {"parent_rid": "repo", "title": "T", "source_ref": "feature"},
            ProposalAction.CREATE,
        ),
        ("list", ProposalType.CODE_PR, (), {"parent_rid": "repo"}, ProposalAction.LIST),
        ("get", ProposalType.CODE_PR, ("1",), {}, ProposalAction.GET),
        ("comment", ProposalType.CODE_PR, ("1", "note"), {}, ProposalAction.COMMENT),
        ("approve", ProposalType.CODE_PR, ("1",), {}, ProposalAction.APPROVE),
        (
            "request_changes",
            ProposalType.CODE_PR,
            ("1",),
            {},
            ProposalAction.REQUEST_CHANGES,
        ),
        ("merge", ProposalType.CODE_PR, ("1",), {}, ProposalAction.MERGE),
        ("close", ProposalType.CODE_PR, ("1",), {}, ProposalAction.CLOSE),
        (
            "create",
            ProposalType.GLOBAL_PROPOSAL,
            (),
            {"parent_rid": "ontology", "title": "T", "source_ref": "branch"},
            ProposalAction.CREATE,
        ),
        (
            "list",
            ProposalType.GLOBAL_PROPOSAL,
            (),
            {"parent_rid": "ontology"},
            ProposalAction.LIST,
        ),
        ("get", ProposalType.GLOBAL_PROPOSAL, ("gp",), {}, ProposalAction.GET),
        (
            "comment",
            ProposalType.GLOBAL_PROPOSAL,
            ("gp", "note"),
            {},
            ProposalAction.COMMENT,
        ),
        ("approve", ProposalType.GLOBAL_PROPOSAL, ("gp",), {}, ProposalAction.APPROVE),
        (
            "request_changes",
            ProposalType.GLOBAL_PROPOSAL,
            ("gp",),
            {},
            ProposalAction.REQUEST_CHANGES,
        ),
        ("accept", ProposalType.GLOBAL_PROPOSAL, ("gp",), {}, ProposalAction.ACCEPT),
        ("close", ProposalType.GLOBAL_PROPOSAL, ("gp",), {}, ProposalAction.CLOSE),
    ],
)
def test_every_unreachable_operation_fails_before_client_access(
    method_name, proposal_type, args, kwargs, action
):
    service = ProposalService(profile="selected")
    service.auth_manager.get_client = Mock(
        side_effect=AssertionError("client accessed")
    )

    with pytest.raises(UnsupportedProposalCapabilityError) as exc_info:
        getattr(service, method_name)(proposal_type, *args, **kwargs)

    assert exc_info.value.action is action
    assert exc_info.value.proposal_type is proposal_type
    service.auth_manager.get_client.assert_not_called()


def test_unsupported_error_payload_is_stable():
    error = UnsupportedProposalCapabilityError(
        ProposalType.CODE_PR, ProposalAction.MERGE
    )

    assert error.exit_code == 6
    assert error.to_payload() == {
        "ok": False,
        "error": {
            "category": "unsupported-capability",
            "message": str(error),
            "proposal_type": "code-pr",
            "action": "merge",
        },
    }


def test_capability_preflight_reports_requested_action_without_client_access():
    service = ProposalService(profile="selected")
    service.auth_manager.get_client = Mock(
        side_effect=AssertionError("client accessed")
    )

    with pytest.raises(UnsupportedProposalCapabilityError) as exc_info:
        service.require_capability(ProposalType.GLOBAL_PROPOSAL, ProposalAction.CLOSE)

    assert exc_info.value.action is ProposalAction.CLOSE
    service.auth_manager.get_client.assert_not_called()


def test_explicit_type_parser_accepts_only_documented_types():
    assert parse_proposal_type("code-pr") is ProposalType.CODE_PR
    assert parse_proposal_type("global-proposal") is ProposalType.GLOBAL_PROPOSAL
    with pytest.raises(ProposalValidationError):
        parse_proposal_type("infer-it")


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (
            type("UnauthorizedError", (Exception,), {})("no token"),
            ProposalAuthenticationError,
        ),
        (ValueError("bad provider response"), ProposalRemoteServiceError),
        (type("ConflictError", (Exception,), {})("changed"), ProposalConflictError),
    ],
)
def test_provider_errors_map_to_stable_categories(error, expected_type):
    assert isinstance(normalize_proposal_error(error), expected_type)
