"""False-safety invariants for internal dependency providers."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from pltr.services.dependency import (
    AnalysisContext,
    BudgetExhausted,
    DependencyGraphService,
    DependencyTarget,
    DiscoveryBudget,
)
from pltr.services.dependency_internal_specs import ACP_OPERATION_SPECS
from pltr.services.dependency_providers import (
    ConjureRestProvider,
    ResultSemantics,
    SdkProvider,
    classify_conjure_response,
)
from pltr.services.foundry_internal_client import TokenExpiredError


def _context() -> AnalysisContext:
    return AnalysisContext.create(profile="test", host="https://example.test")


@pytest.mark.parametrize("empty", [[], {}])
def test_internal_200_empty_is_inconclusive_never_covered_empty(empty):
    spec = ACP_OPERATION_SPECS["ACP-04"]
    assert ResultSemantics(spec, (200, empty, "")) == "empty"

    client = Mock()
    client.conjure.return_value = (200, empty, "")
    context = _context()
    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "empty"
    assert result.coverage_status == "inconclusive"
    assert result.coverage_status != "covered-empty"
    assert context.budget.used_requests == 0
    assert context.internal_budget.used_requests == 1


def test_operation_specific_empty_collection_is_also_inconclusive():
    spec = ACP_OPERATION_SPECS["ACP-04"]
    assert ResultSemantics(spec, (200, {"datasources": []}, "{}")) == "empty"


def test_internal_next_page_token_is_truncated():
    spec = ACP_OPERATION_SPECS["ACP-04"]
    payload = {
        "datasources": [
            {
                "definition": {
                    "type": "dataset",
                    "propertyMapping": {"employeeId": "employee_id"},
                }
            }
        ],
        "nextPageToken": "abc123",
    }

    assert ResultSemantics(spec, (200, payload, "...")) == "truncated"


def test_internal_truncated_response_is_inconclusive_never_covered():
    client = Mock()
    client.conjure.return_value = (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "propertyMapping": {"employeeId": "employee_id"},
                    }
                }
            ],
            "nextPageToken": "abc123",
        },
        "...",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "truncated"
    assert result.coverage_status == "inconclusive"
    assert result.coverage_status not in {"covered", "covered-empty"}


def test_missing_required_discriminator_emits_shape_drift_gap_without_crashing():
    client = Mock()
    client.conjure.return_value = (
        200,
        {"datasources": [{"definition": {"type": "dataset"}}]},
        "{}",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "shape-drift"
    assert result.error_class == "response-shape-drift"
    assert any(
        gap.reason_code == "response-shape-drift" and gap.coverage == "inconclusive"
        for gap in context.gaps.values()
    )


def test_conforming_acp_04_response_is_covered_without_gap():
    client = Mock()
    client.conjure.return_value = (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "propertyMapping": {"employeeId": "employee_id"},
                    },
                    "additiveServerField": True,
                }
            ],
            "additiveTopLevelField": {"ignored": True},
        },
        "{}",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "ok"
    assert result.coverage_status == "covered"
    assert result.error_class is None
    assert context.gaps == {}


@pytest.mark.parametrize(
    ("status", "payload", "expected_class", "expected_coverage"),
    [
        (
            400,
            {"errorName": "Default:InvalidArgument", "parameters": {}},
            "missing-required-field",
            "inconclusive",
        ),
        (
            422,
            {"errorName": "Conjure:UnprocessableEntity"},
            "invalid-request",
            "inconclusive",
        ),
        (
            403,
            {"errorName": "Default:PermissionDenied"},
            "inaccessible",
            "inaccessible",
        ),
        (200, {}, "inconclusive", "inconclusive"),
        (
            404,
            {"errorName": "Route:RouteNotMounted"},
            "route-not-mounted",
            "inconclusive",
        ),
    ],
)
def test_conjure_taxonomy(status, payload, expected_class, expected_coverage):
    classified = classify_conjure_response(status, payload)
    assert classified.error_class == expected_class
    assert classified.coverage == expected_coverage


def test_permission_denied_stays_inaccessible_even_when_semantics_are_ambiguous():
    client = Mock()
    client.conjure.return_value = (
        403,
        {"errorName": "Default:PermissionDenied"},
        "denied",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "permission-ambiguous"
    assert result.coverage_status == "inaccessible"
    assert result.error_class == "inaccessible"
    assert any(gap.coverage == "inaccessible" for gap in context.gaps.values())


def test_provider_propagates_token_expired_without_inconclusive_result():
    client = Mock()
    client.conjure.side_effect = TokenExpiredError("expired")
    context = _context()

    with pytest.raises(TokenExpiredError) as raised:
        ConjureRestProvider(client).invoke(
            context,
            "ACP-04",
            "GET",
            "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
            None,
            target="property-node",
        )

    assert raised.value.error_class == "token-expired"
    assert not context.gaps
    classification = classify_conjure_response(
        401, {"errorName": "Default:Unauthorized"}
    )
    assert classification.coverage == "token-expired"
    assert classification.coverage != "inconclusive"


@pytest.mark.parametrize(
    ("error", "expected_class"),
    [
        (requests.ConnectionError("offline"), "connection"),
        (requests.Timeout("slow"), "timeout"),
        (requests.exceptions.SSLError("bad certificate"), "connection"),
    ],
)
def test_internal_transport_failure_degrades_to_retryable_coverage_gap(
    error, expected_class
):
    client = Mock()
    client.conjure.side_effect = error
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.payload is None
    assert result.result_semantics is None
    assert result.coverage_status == "partial"
    assert result.error_class == expected_class
    assert result.retryable is True
    assert any(
        gap.reason_code == expected_class
        and gap.coverage == "partial"
        and gap.retryable is True
        for gap in context.gaps.values()
    )
    assert result.operation_provenance_id in context.operation_provenance


def test_finish_coverage_rejects_internal_covered_empty():
    service = DependencyGraphService(client=SimpleNamespace())
    record = service._coverage_record(
        _context(),
        "property",
        "property-column-mapping",
        "property-node",
        operation="ACP-04",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )

    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(record, "covered-empty")


def test_matrix_seeded_record_merges_internal_metadata_before_covered_empty_guard():
    service = DependencyGraphService(client=SimpleNamespace())
    context = _context()
    node = service._add_node(
        context,
        "property",
        "employeeId",
        {"property": "employeeId"},
        is_target=True,
    )
    target = DependencyTarget(
        "property",
        {"property": "employeeId"},
        "employeeId",
        node.id,
    )

    service._initialize_matrix(context, target)
    record = service._coverage_record(
        context,
        "property",
        "property-column-mapping",
        node.id,
        operation="ACP-04",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )

    assert record.operation == "ACP-04"
    assert record.transport == "conjure-rest"
    assert record.empty_is_inconclusive is True
    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(record, "covered-empty")


def test_phase_a_registry_contains_only_get_acp_04_and_acp_08():
    assert set(ACP_OPERATION_SPECS) == {"ACP-04", "ACP-08"}
    for acp_id, spec in ACP_OPERATION_SPECS.items():
        assert spec.acp_id == acp_id
        assert spec.verb == "GET"
        assert spec.contract_pins == {"mcp": "0.397.0", "verified_on": "2026-07-21"}
        assert spec.shape_descriptor
        assert callable(spec.positive_control)
        assert spec.positive_control_enabled is False


def test_internal_budget_exhaustion_does_not_starve_sdk_requests():
    context = AnalysisContext.create(
        profile="test",
        host="https://example.test",
        internal_budget=DiscoveryBudget(max_requests=1),
    )
    internal_client = Mock()
    internal_client.conjure.return_value = (200, {}, "{}")
    internal = ConjureRestProvider(internal_client)
    internal.invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    with pytest.raises(BudgetExhausted):
        internal.invoke(
            context,
            "ACP-04",
            "GET",
            "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
            None,
            target="property-node",
        )

    sdk_result = SdkProvider(Mock(return_value={"rid": "build"})).invoke(
        context, "build.get", {}, target="build"
    )
    assert sdk_result.result_semantics == "ok"
    assert context.internal_budget.used_requests == 1
    assert context.budget.used_requests == 1


def test_internal_provider_forwards_the_budgeted_request_timeout():
    context = AnalysisContext.create(
        profile="test",
        host="https://example.test",
        request_timeout_seconds=7,
    )
    client = Mock()
    client.conjure.return_value = (200, {}, "{}")

    ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert client.conjure.call_args.kwargs["request_timeout"] == 7
